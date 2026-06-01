# TagBrowser

Sublime Text plugin to browse #tags in Markdown and text files.

Supports Obsidian-style tags, including hyphens (`#global-warming`) and nested tags (`#topic/subtopic`).

## Installation

### Via Package Control (recommended)

1. Open the command palette (`Cmd+Shift+P` on macOS, `Ctrl+Shift+P` on Linux/Windows).
2. Run **Package Control: Add Repository** and paste:
   ```
   https://github.com/markschaver/TagBrowser
   ```
3. Run **Package Control: Install Package** and choose **TagBrowser**.

To update later, run **Package Control: Upgrade Package** and pick **TagBrowser**.

### Manual installation

1. In Sublime Text, open **Preferences → Browse Packages…** to reveal your `Packages` directory.
2. Clone this repo into that directory as `TagBrowser`:
   ```
   git clone https://github.com/markschaver/TagBrowser.git TagBrowser
   ```
3. Restart Sublime Text. Pull the repo to update.

## Usage

- **View → Tag Browser → Toggle Panel** opens a side panel listing every `#tag` found in your project's text and Markdown files.
- Click a tag to see all files and lines that reference it. The results view is reused across clicks.
- Use the sort bar at the top of the panel to sort by name or count; click an active label again to flip its direction.
- The panel auto-refreshes when you save a file, or you can click **Refresh** at the bottom.
