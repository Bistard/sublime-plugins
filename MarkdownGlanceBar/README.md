# MarkdownGlanceBar

Lightweight companion launcher for [**MarkdownGlance**](https://github.com/feibuilds/MarkdownGlance) on **Sublime Text 4** (Build 4205+ / Python `3.14` `plugin_host`).

## Features

1. **Top-Right Editor Toolbar (`annotation`)**
   - Renders compact, theme-adaptive clickable actions (`分屏预览 · 全屏 · 目录`) along the right edge of line 1 in Markdown views.
   - Zero vertical line shift and zero conflict with `MarkdownFold`'s left-side `▾` / `▸` heading fold arrows.
   - Automatically highlights active states (`分屏预览` / `目录`) and skips `MarkdownGlance`'s own preview and outline tabs.
2. **Markdown-Only Editor & Tab Right-Click Menus**
   - Adds 4 flat items directly to both the editor context menu and the tab context menu (`Markdown 分屏预览`, `Markdown 全屏预览`, `Markdown 目录面板`, `Markdown 浏览器打开`).
   - Completely hidden on non-Markdown views/tabs (including inactive background tabs) via `is_visible()` with `(group, index)` targeting.
3. **Smart Side-by-Side Toggle & Source Focus Retention**
   - Clicking **分屏预览** while side-by-side preview is already open closes the split preview cleanly.
   - Opening side-by-side preview or toggling the outline panel keeps cursor focus in the Markdown source editor.
4. **Automatic Dependency Sync via `install.ps1`**
   - Declares `MarkdownGlance` in `package-control-deps.json`; running `.\scripts\install.ps1` automatically ensures `"MarkdownGlance"` is present in `User/Package Control.sublime-settings` so Package Control installs and updates it automatically.

## Settings

Accessible via `Preferences -> Package Settings -> MarkdownGlanceBar -> Settings`:

```json
{
    "enabled": true,
    "show_toolbar": true,
    "toggle_side_by_side": true,
    "keep_source_focus": true,
    "toolbar_separator": " · ",
    "annotation_color": "transparent",
    "buttons": [
        { "action": "side_by_side", "label": "分屏预览" },
        { "action": "full_screen", "label": "全屏" },
        { "action": "outline", "label": "目录" }
    ]
}
```
