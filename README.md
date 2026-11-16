# sublime-plugins

Personal collection of lightweight, fast Sublime Text 4 plugins (targeting Sublime Text Build 4205+ / Python `3.14` plugin host), organized as independent per-plugin directories.

## Plugins

| Plugin | Description |
| --- | --- |
| [`MarkdownFlow`](./MarkdownFlow) | Smooth Markdown list/blockquote authoring (auto-continue, step-by-step outdent, `Tab`/`Shift+Tab` indent + sibling renumbering, single-key marker Backspace), CJK-friendly streaming inline formatting (`**`, `*`, `` ` ``, `~~`), ergonomic links, and smart URL paste. |

## Local Installation (Windows)

Link all plugins (or a specific plugin) into `%APPDATA%\Sublime Text\Packages` via directory junctions (`mklink /J` — no Administrator privileges required, hot-reloads on save):

```powershell
# Link all plugins in this repo
.\scripts\install.ps1

# Or link a single plugin
.\scripts\install.ps1 -Plugin MarkdownFlow

# Unlink without deleting source files
.\scripts\uninstall.ps1 -Plugin MarkdownFlow
```

## Running Tests

Core editing engines are decoupled from `sublime` / `sublime_plugin` so unit tests run directly with standard Python:

```powershell
python -m unittest discover -s MarkdownFlow/tests -t MarkdownFlow -v
```

## License

[MIT](./LICENSE)
