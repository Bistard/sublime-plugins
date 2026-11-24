# MarkdownFold

Hierarchical Markdown heading folding and strict folded-region editing guardrails for **Sublime Text 4** (Build 4205+ / Python 3.14 `plugin_host`).

## Features

### 1. Hierarchical Heading Folding (`▾` / `▸`)

* **True Section-Level Folding**:
  * Renders subtle clickable arrows (`▾` expanded / `▸` collapsed) directly to the left of every foldable Markdown heading (ATX `#`–`######` and Setext `===` / `---`).
  * Folding a heading collapses **everything** under it — including nested subheadings, paragraphs, lists, and code blocks — up to the next heading of equal or higher level (or EOF).
  * Automatically ignores `#` inside fenced code blocks (`` ``` `` / `~~~`), YAML/TOML frontmatter, HTML comments, blockquotes, and lists.
* **No Double Arrows**:
  * Includes a scoped `Fold.tmPreferences` override that removes Sublime Text's flat heading fold rule (eliminating duplicate gutter arrows on headings) while preserving native gutter fold buttons for fenced code blocks and indented lists.
  * Keeps gutter fold buttons permanently visible in Markdown views (`fade_fold_buttons: false`, configurable).
* **Editable Blank-Line Buffer**:
  * Excludes trailing blank lines before the next equal/higher heading so collapsed sections naturally retain an editable gap between them:
    ```markdown
    ▸ # Section 1 [...]

    ▾ ## new_title
    Write and delete freely here without unfolding Section 1 or Section 2!

    ▸ # Section 2 [...]
    ```

### 2. Strict Folded-Region Boundary Guardrail

Protects **all** folded regions in Markdown views (headings, code blocks, lists, and manual folds) against accidental auto-unfolding or hidden-content deletion:

* **Free Editing in Gaps**: Type, press `Enter`, delete text, remove extra blank lines, or delete gap lines freely between folded blocks.
* **Safe Boundary Protection**:
  * Blocks `Backspace` at column 0 of the line immediately below a folded block and `Delete` at the end of a non-empty line immediately above a folded block.
  * Pressing `Enter` (or `Ctrl+Enter`) at the end of a folded line (`# Title [...]|`) safely inserts a new blank line **below** the folded section without unfolding it.
  * Allows editing visible heading text to the left of `[...]` (e.g. renaming a collapsed title) while blocking any edit that crosses into `[...]` (such as typing at `[...]|`, splitting the title with `Enter`, or pressing `Delete` at `# Title|[...]`).
  * Blocks bulk/destructive operations intersecting a folded region (`Ctrl+Shift+K` Delete Line, empty-selection `Ctrl+X` Cut, `Delete to EOL/BOL`, line swaps/joins, or cross-fold selection edits) with a subtle status bar hint while keeping read-only `Ctrl+C` Copy allowed.
  * Fully compatible with `MarkdownFlow` (`markdown_flow_enter`, `markdown_flow_backspace`, inline toggles, smart paste).

### 3. Nested Fold Memory & Persistence

* **Nested Fold Memory**: Folding an outer heading remembers any already-folded inner subheadings (arbitrary depth, auto-tracked across buffer edits via Sublime `HIDDEN` regions) and restores them step-by-step when unfolding outer sections. Running `Unfold All` clears memory and expands everything.
* **Cross-Reopen Persistence**: Automatically saves fold states (including nested memory) to Sublime Text's Cache directory (`<cache>/MarkdownFold/folds_v1.json`, never touching your workspace) on save/close, and smartly restores them by heading `(level, title, occurrence)` anchor when reopening.

## Command Palette Commands

No extra global shortcuts are claimed by default (native `Ctrl+Shift+[` / `]` remains untouched; bind any command below in your User keymap if desired):

| Command Palette Caption | Command |
| --- | --- |
| `MarkdownFold: Toggle Current Section` | `markdown_fold_toggle_section` |
| `MarkdownFold: Fold Headings at Level 1` – `6` | `markdown_fold_fold_level` (`{"level": 1..6}`) |
| `MarkdownFold: Fold All Headings` | `markdown_fold_fold_all` |
| `MarkdownFold: Unfold All` | `markdown_fold_unfold_all` |
| `Preferences: MarkdownFold Settings` | `edit_settings` |

## Settings

Accessible via `Preferences -> Package Settings -> MarkdownFold -> Settings`:

```json
{
    "enabled": true,
    "show_heading_arrows": true,
    "always_show_gutter_fold_buttons": true,
    "guard_folded_regions": true,
    "keep_trailing_blank_lines": true,
    "remember_nested_folds": true,
    "persist_folds": true,
    "persist_max_files": 500,
    "arrow_expanded": "▾",
    "arrow_collapsed": "▸",
    "max_arrow_file_size": 500000
}
```
