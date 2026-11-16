# MarkdownFlow

Lightweight Markdown authoring assistant for **Sublime Text 4** (Build 4205+ / Python 3.14 `plugin_host`).

## Features

### 1. List & Blockquote Editing Flow

* **Auto-continue & Mid-line Split (`Enter`)**:
  * Supports unordered lists (`-`, `*`, `+`), ordered lists (`1.`, `1)`), task lists (`- [ ]`, `- [x]`), blockquotes (`>`, `> >`), and lists nested inside blockquotes (`> 1. item`).
  * Completed task items (`- [x] Done`) automatically spawn unchecked items (`- [ ] `) on `Enter`.
  * Placing the cursor *before* a list marker (`|1. First`) and pressing `Enter` inserts a clean blank line above the list.
* **Step-by-Step Outdent on Empty Items (`Enter`)**:
  * Pressing `Enter` on an empty nested list item (`    - `) outdents one level first and inherits the parent list's marker/numbering (`2. `).
  * Pressing `Enter` again on an empty top-level item clears the line to exit the list cleanly.
* **Soft Continuation Line (`Shift+Enter`)**:
  * Breaks the line without creating a new bullet/number, automatically aligning indentation with the current item's text column.
* **Whole-Item Indent / Outdent (`Tab` / `Shift+Tab`)**:
  * Works with the cursor **anywhere** on a list line (as long as autocomplete/snippet fields are not active) as well as multi-line selections.
  * Uses fixed **4-space** nesting per level for universal CommonMark/GFM compatibility and stable child indentation across `9.` -> `10.`.
* **Structure-Aware Ordered List Renumbering**:
  * Automatically renumbers sibling items on `Enter`, `Tab`, `Shift+Tab`, and marker `Backspace` within a single atomic Undo (`Ctrl+Z`) step.
  * Preserves custom starting numbers (e.g. `5. Alpha`), resets newly indented sublists to `1.`, and skips fenced code blocks inside lists.
  * Also available manually via Command Palette: **`MarkdownFlow: Renumber Ordered Lists`**.
* **One-Key Marker Removal (`Backspace`)**:
  * Pressing `Backspace` right after a list marker (`- [ ] |text` or `2. |`) deletes the entire list marker in one keystroke while keeping indentation intact.

### 2. CJK-Friendly Inline Formatting & Smart Paste

* **Streaming Pair Input & 2-Bit Emphasis Toggle**:
  * With no selection, pressing `Ctrl+B` inserts `**|**` (never greedily swallowing an entire unspaced Chinese clause); type text and press `Ctrl+B` again to jump past the closing `**`, or press immediately on an empty `**|**` to remove it.
  * Placing the cursor inside existing formatted text (`**重|点**`) and pressing `Ctrl+B` unwraps it in one keystroke.
  * Cleanly composes `*` (italic), `**` (bold), and `***` (bold + italic) without corrupting delimiters, and ignores list bullets (`* item`) and inline code spans.
* **Smart URL Paste (`Ctrl+V`)**:
  * Selecting single-line text and pasting an `http(s)://` or `mailto:` URL wraps it into `[selected](url)`.
  * Automatically bypassed inside code blocks/inline code, inside `[...](...)` link destinations, or when replacing an existing URL with another URL.
* **Scope Isolation**:
  * Strictly scoped to Markdown prose (`text.html.markdown` excluding fenced code blocks, frontmatter, HTML comments, and TeX math), and uses `on_query_context` so native Sublime behaviors remain untouched outside active contexts.

## Default Key Bindings (Windows / Linux)

| Shortcut | Action | Notes |
| --- | --- | --- |
| `Enter` | Continue / split / outdent / exit list or blockquote | Native `Enter` elsewhere |
| `Shift+Enter` | Soft continuation line aligned to item text | Inside lists & blockquotes |
| `Tab` / `Shift+Tab` | Indent / outdent list item (+ renumber) | Works anywhere on list line |
| `Backspace` | Delete whole list marker (`- [ ] `, `1. `) | Only right after marker |
| `Ctrl+B` | Toggle Bold (`**`) | Streaming / wrap / unwrap |
| `Ctrl+I` | Toggle Italic (`*`) | Composes cleanly with `**` |
| `Ctrl+E` | Toggle Inline Code (`` ` ``) | Preserves `` Ctrl+` `` Console |
| `Alt+S` (or `~` on selection) | Toggle Strikethrough (`~~`) | — |
| `Alt+K` | Insert Link `[text](url)` / step fields | Preserves `Ctrl+K, Ctrl+B` & `Ctrl+Shift+K` |
| `Ctrl+V` | Smart Paste URL as `[selection](url)` | Only when clipboard is a single URL |

*(On macOS, `Ctrl+B` / `Ctrl+I` / `Ctrl+E` / `Ctrl+V` map to `Cmd+B` / `Cmd+I` / `Cmd+E` / `Cmd+V`, and Strikethrough maps to `Cmd+Shift+X`.)*

## Settings

Accessible via `Preferences -> Package Settings -> MarkdownFlow -> Settings`:

```json
{
    "enabled": true,
    "list_indent_size": 4,
    "smart_paste_url": true
}
```
