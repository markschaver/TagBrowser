import sublime
import sublime_plugin
import os
import re
import threading


TAG_PATTERN = re.compile(r'(?<![\w\\/])#([A-Za-z_]\w*)\b')

# File extensions to scan (text-based files)
TEXT_EXTENSIONS = {
    '.txt', '.md', '.markdown',
}

SKIP_DIRS = {
    '.git', '.svn', '.hg', 'node_modules', '__pycache__', '.tox',
    'venv', '.venv', 'env', '.env', 'dist', 'build', '.build',
    'vendor', 'target', '.cache', '.idea', '.vscode',
}

# Max file size to scan (1MB)
MAX_FILE_SIZE = 1024 * 1024

# Track state per window
_panel_state = {}  # window.id() -> {"sheet": Sheet, "tag_data": dict, "original_layout": dict}


def _should_scan_file(filepath):
    """Check if a file should be scanned for tags."""
    _, ext = os.path.splitext(filepath)
    basename = os.path.basename(filepath)

    # Include extensionless files with known names
    if ext == '' and basename.lower() in ('makefile', 'dockerfile', 'readme', 'todo', 'notes'):
        return True

    return ext.lower() in TEXT_EXTENSIONS


def scan_project_for_tags(window):
    """Scan all project folders for hashtag patterns.

    Returns {tag: {filepath: [(line_number, line_text), ...]}}.
    """
    tag_files = {}
    folders = window.folders()

    for folder in folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]

            for filename in files:
                filepath = os.path.join(root, filename)

                if not _should_scan_file(filepath):
                    continue

                try:
                    if os.path.getsize(filepath) > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                except (IOError, OSError):
                    continue

                for line_num, line in enumerate(lines, 1):
                    found_tags = set(TAG_PATTERN.findall(line))
                    for tag in found_tags:
                        if tag not in tag_files:
                            tag_files[tag] = {}
                        if filepath not in tag_files[tag]:
                            tag_files[tag][filepath] = []
                        tag_files[tag][filepath].append((line_num, line.rstrip('\n\r')))

    return tag_files


def generate_html(tag_data):
    """Build minihtml content for the tag browser panel."""
    if not tag_data:
        return '''
        <body id="tag-browser">
            <style>
                body { padding: 10px; background-color: var(--background); }
                p { color: color(var(--foreground) alpha(0.6)); font-style: italic; }
            </style>
            <p>No tags found in project.</p>
        </body>
        '''

    sorted_tags = sorted(tag_data.keys(), key=lambda t: t.lower())
    total_tags = len(sorted_tags)
    total_files = len(set(f for files in tag_data.values() for f in files))

    # Find the longest tag name to calculate padding
    max_tag_len = max(len(t) for t in sorted_tags) if sorted_tags else 0
    max_count_len = max(len(str(len(tag_data[t]))) for t in sorted_tags) if sorted_tags else 0

    rows = ""
    for tag in sorted_tags:
        file_count = len(tag_data[tag])
        url = sublime.command_url("tag_browser_search", {"tag": tag})
        # Pad count with non-breaking spaces so numbers right-align
        count_str = str(file_count).rjust(max_count_len).replace(' ', '&nbsp;')
        # Pad between tag and count with dots or spaces
        tag_display = '#' + tag
        pad_len = max_tag_len - len(tag) + 2
        padding = '&nbsp;' * pad_len
        rows += (
            '<div class="row">'
            '<a class="tag" href="{url}">{tag_display}</a>'
            '{padding}'
            '<span class="count">{count}</span>'
            '</div>\n'
        ).format(url=url, tag_display=tag_display, padding=padding, count=count_str)

    return '''
    <body id="tag-browser">
        <style>
            body {{
                padding: 8px 10px;
                background-color: var(--background);
                margin: 0;
            }}
            h2 {{
                color: var(--foreground);
                margin: 4px 0 2px 0;
                font-size: 1.1rem;
                padding-bottom: 4px;
                border-bottom: 1px solid color(var(--foreground) alpha(0.15));
            }}
            .summary {{
                color: color(var(--foreground) alpha(0.5));
                font-size: 0.85rem;
                margin: 2px 0 8px 0;
            }}
            .row {{
                line-height: 1.6;
                padding: 1px 4px;
                white-space: nowrap;
            }}
            a.tag {{
                text-decoration: none;
                color: var(--bluish);
            }}
            .count {{
                color: color(var(--foreground) alpha(0.5));
                font-size: 0.9rem;
            }}
            .refresh-link {{
                margin-top: 10px;
                padding-top: 6px;
                border-top: 1px solid color(var(--foreground) alpha(0.15));
            }}
            .refresh-link a {{
                text-decoration: none;
                color: color(var(--foreground) alpha(0.4));
                font-size: 0.8rem;
            }}
        </style>
        <h2>Tags</h2>
        <div class="summary">{total_tags} tags in {total_files} files</div>
        {rows}
        <div class="refresh-link">
            <a href="{refresh_url}">Refresh</a>
        </div>
    </body>
    '''.format(
        rows=rows,
        total_tags=total_tags,
        total_files=total_files,
        refresh_url=sublime.command_url("tag_browser_refresh", {})
    )


def _get_state(window):
    wid = window.id()
    if wid not in _panel_state:
        _panel_state[wid] = {"sheet": None, "tag_data": {}, "original_layout": None}
    return _panel_state[wid]


def _close_panel(window):
    """Close the tag browser panel and restore original layout."""
    state = _get_state(window)
    if state["sheet"] is not None:
        try:
            state["sheet"].close()
        except Exception:
            pass
        state["sheet"] = None

        # Restore original layout
        if state["original_layout"]:
            window.set_layout(state["original_layout"])
            state["original_layout"] = None
        else:
            window.set_layout({
                "cols": [0.0, 1.0],
                "rows": [0.0, 1.0],
                "cells": [[0, 0, 1, 1]]
            })
        return True
    return False


def _is_panel_open(window):
    state = _get_state(window)
    if state["sheet"] is None:
        return False
    # Verify the sheet is still valid
    try:
        state["sheet"].id()
        return True
    except Exception:
        state["sheet"] = None
        return False


class TagBrowserToggleCommand(sublime_plugin.WindowCommand):
    """Toggle the tag browser side panel."""

    def run(self):
        window = self.window

        if _is_panel_open(window):
            _close_panel(window)
            return

        state = _get_state(window)

        # Save original layout before modifying
        state["original_layout"] = window.layout()

        # Create side group layout (narrow left panel)
        window.set_layout({
            "cols": [0.0, 0.2, 1.0],
            "rows": [0.0, 1.0],
            "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]
        })

        # Move any views that ended up in group 0 to group 1
        for view in window.views_in_group(0):
            window.set_view_index(view, 1, -1)

        # Show loading state
        loading_html = '''
        <body id="tag-browser">
            <style>
                body { padding: 10px; background-color: var(--background); }
                p { color: color(var(--foreground) alpha(0.6)); font-style: italic; }
            </style>
            <p>Scanning project for tags...</p>
        </body>
        '''
        state["sheet"] = window.new_html_sheet("Tags", loading_html, group=0)

        # Focus main editing area
        window.focus_group(1)

        # Scan asynchronously
        sublime.set_timeout_async(lambda: self._scan_and_update(window), 0)

    def _scan_and_update(self, window):
        tag_data = scan_project_for_tags(window)
        state = _get_state(window)
        state["tag_data"] = tag_data
        html = generate_html(tag_data)

        # Update on main thread
        sublime.set_timeout(lambda: self._update_sheet(window, html), 0)

    def _update_sheet(self, window, html):
        state = _get_state(window)
        if state["sheet"] is not None:
            try:
                state["sheet"].close()
            except Exception:
                pass
            state["sheet"] = window.new_html_sheet("Tags", html, group=0)
            # Refocus main area
            window.focus_group(1)


class TagBrowserRefreshCommand(sublime_plugin.WindowCommand):
    """Refresh the tag browser panel."""

    def run(self):
        window = self.window

        if not _is_panel_open(window):
            # If not open, just open it
            window.run_command("tag_browser_toggle")
            return

        state = _get_state(window)

        # Show loading
        loading_html = '''
        <body id="tag-browser">
            <style>
                body { padding: 10px; background-color: var(--background); }
                p { color: color(var(--foreground) alpha(0.6)); font-style: italic; }
            </style>
            <p>Scanning project for tags...</p>
        </body>
        '''
        try:
            state["sheet"].close()
        except Exception:
            pass
        state["sheet"] = window.new_html_sheet("Tags", loading_html, group=0)
        window.focus_group(1)

        # Scan asynchronously
        sublime.set_timeout_async(lambda: self._scan_and_update(window), 0)

    def _scan_and_update(self, window):
        tag_data = scan_project_for_tags(window)
        state = _get_state(window)
        state["tag_data"] = tag_data
        html = generate_html(tag_data)
        sublime.set_timeout(lambda: self._update_sheet(window, html), 0)

    def _update_sheet(self, window, html):
        state = _get_state(window)
        if state["sheet"] is not None:
            try:
                state["sheet"].close()
            except Exception:
                pass
            state["sheet"] = window.new_html_sheet("Tags", html, group=0)
            window.focus_group(1)


class TagBrowserSearchCommand(sublime_plugin.WindowCommand):
    """Search for files containing a specific tag. Opens a results view."""

    def run(self, tag):
        window = self.window
        state = _get_state(window)
        tag_data = state.get("tag_data", {})

        file_matches = tag_data.get(tag, {})
        if not file_matches:
            sublime.status_message("No files found for #{}".format(tag))
            return

        # Get project folders for making paths relative
        folders = window.folders()

        def make_relative(path):
            for folder in folders:
                if path.startswith(folder):
                    return os.path.relpath(path, folder)
            return path

        # Determine which group to show results in
        active_group = 1 if _is_panel_open(window) else 0
        window.focus_group(active_group)

        # Build results text
        total_files = len(file_matches)
        total_matches = sum(len(lines) for lines in file_matches.values())
        header = "Tag: #{tag}  —  {files} file{fs}, {matches} match{ms}\n{sep}\n\n".format(
            tag=tag,
            files=total_files,
            fs='s' if total_files != 1 else '',
            matches=total_matches,
            ms='es' if total_matches != 1 else '',
            sep='=' * 60
        )

        body = ""
        sorted_files = sorted(file_matches.keys())
        for filepath in sorted_files:
            rel_path = make_relative(filepath)
            matches = file_matches[filepath]
            body += "{}:\n".format(rel_path)
            for line_num, line_text in matches:
                body += "  {}: {}\n".format(line_num, line_text)
            body += "\n"

        results_text = header + body

        # Create a new scratch view for results
        results_view = window.new_file()
        results_view.set_name("Tag Results: #{}".format(tag))
        results_view.set_scratch(True)
        results_view.set_read_only(False)
        results_view.run_command("append", {"characters": results_text})
        results_view.set_read_only(True)
        results_view.settings().set("tag_browser_results", True)
        results_view.settings().set("tag_browser_tag", tag)
        results_view.settings().set("word_wrap", False)

        # Assign the "Find Results" syntax for navigation support
        results_view.assign_syntax("Packages/Default/Find Results.hidden-tmLanguage")

        # Store file path mapping for navigation
        file_regions = {}
        for filepath in sorted_files:
            rel_path = make_relative(filepath)
            file_regions[rel_path] = filepath

        results_view.settings().set("tag_browser_file_map", file_regions)

        # Move cursor to start
        results_view.sel().clear()
        results_view.sel().add(sublime.Region(0, 0))


class TagBrowserOpenResultCommand(sublime_plugin.TextCommand):
    """Open the file under cursor in tag browser results."""

    def run(self, edit):
        view = self.view
        if not view.settings().get("tag_browser_results"):
            return

        window = view.window()
        if not window:
            return

        file_map = view.settings().get("tag_browser_file_map", {})
        folders = window.folders()

        # Get the current line
        sel = view.sel()
        if not sel:
            return

        line_region = view.line(sel[0])
        line_text = view.substr(line_region)

        # Check if this is a file path line (ends with ':' and no leading spaces)
        if line_text and not line_text.startswith(' ') and line_text.endswith(':'):
            rel_path = line_text[:-1]  # Remove trailing ':'
            abs_path = file_map.get(rel_path, '')
            if not abs_path:
                # Try to resolve from folders
                for folder in folders:
                    candidate = os.path.join(folder, rel_path)
                    if os.path.exists(candidate):
                        abs_path = candidate
                        break
            if abs_path:
                active_group = 1 if _is_panel_open(window) else 0
                window.focus_group(active_group)
                window.open_file(abs_path)

        # Check if this is a line match (starts with spaces, has line number)
        elif line_text and line_text.startswith('  '):
            match = re.match(r'^\s+(\d+):', line_text)
            if match:
                line_num = int(match.group(1))
                # Walk backwards to find the file path
                row, _ = view.rowcol(line_region.begin())
                for r in range(row - 1, -1, -1):
                    prev_region = view.line(view.text_point(r, 0))
                    prev_text = view.substr(prev_region)
                    if prev_text and not prev_text.startswith(' ') and prev_text.endswith(':'):
                        rel_path = prev_text[:-1]
                        abs_path = file_map.get(rel_path, '')
                        if not abs_path:
                            for folder in folders:
                                candidate = os.path.join(folder, rel_path)
                                if os.path.exists(candidate):
                                    abs_path = candidate
                                    break
                        if abs_path:
                            active_group = 1 if _is_panel_open(window) else 0
                            window.focus_group(active_group)
                            # Open file at specific line using file:line syntax
                            window.open_file(
                                "{}:{}".format(abs_path, line_num),
                                sublime.ENCODED_POSITION
                            )
                        break


class TagBrowserResultsEventListener(sublime_plugin.EventListener):
    """Handle double-click / Enter in tag browser results."""

    def on_text_command(self, view, command_name, args):
        """Intercept Enter/double-click in results view to open files."""
        if not view.settings().get("tag_browser_results"):
            return None

        # Intercept drag_select (double-click) and insert (Enter key)
        if command_name == "drag_select" and args and args.get("by") == "words":
            # Double-click: open the file
            sublime.set_timeout(lambda: view.run_command("tag_browser_open_result"), 50)
            return None

        return None

    def on_post_text_command(self, view, command_name, args):
        """Handle Enter key in results view."""
        if not view.settings().get("tag_browser_results"):
            return

        # Catch move command that might come from Enter key binding
        if command_name in ("insert", "move"):
            return


def _highlight_tag_when_ready(view, tag):
    """Wait for view to finish loading, then highlight the tag."""
    if view.is_loading():
        sublime.set_timeout(lambda: _highlight_tag_when_ready(view, tag), 100)
        return
    _highlight_tag_in_view(view, tag)


def _highlight_tag_in_view(view, tag):
    """Find and select the first occurrence of the tag in the view."""
    pattern = r'#' + re.escape(tag) + r'\b'
    region = view.find(pattern, 0)
    if region is not None and not region.empty():
        view.sel().clear()
        view.sel().add(region)
        view.show_at_center(region)


class TagBrowserEventListener(sublime_plugin.EventListener):
    """Listen for file saves to auto-refresh the tag panel."""

    def on_post_save_async(self, view):
        window = view.window()
        if window and _is_panel_open(window):
            # Debounce: only refresh if no other refresh is pending
            window.run_command("tag_browser_refresh")
