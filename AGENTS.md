# AGENTS.md

Sublime Text 4 插件合集仓库（面向 Build 4205+ / Python 3.14 插件宿主），每个插件独立存放在根目录子文件夹中。

## 仓库结构

- `MarkdownFlow/` — Markdown 列表/引用编辑流、缩进重编号、CJK 友好行内格式与智能 URL 粘贴
- `MarkdownFold/` — Markdown 标题层级折叠、折叠区编辑护栏、嵌套折叠记忆与跨重开持久化
- `scripts/` — Windows 本地 junction 挂载/卸载脚本（链接到 `%APPDATA%\Sublime Text\Packages`）
- `.github/workflows/test.yml` — Python 3.12 / 3.13 / 3.14 单元测试 CI

插件目录遵循统一布局：

```text
<PluginName>/
├── .python-version        # 固定为 3.14（指定 ST4 插件宿主版本，亦用于 install.ps1 识别）
├── <plugin_snake>.py      # Sublime Text 入口与命令/事件桥接
├── core/                  # 纯 Python 核心引擎（不导入 sublime / sublime_plugin）
├── tests/                 # unittest 单元测试
└── *.sublime-*            # Settings / Keymap / Commands / Menu 等配置
```

## 常用命令

```powershell
# 运行单元测试
python -m unittest discover -s MarkdownFlow/tests -t MarkdownFlow -v
python -m unittest discover -s MarkdownFold/tests -t MarkdownFold -v

# Windows 本地挂载 / 卸载（使用目录联接热重载，无需管理员权限）
.\scripts\install.ps1
.\scripts\install.ps1 -Plugin MarkdownFlow
.\scripts\uninstall.ps1 -Plugin MarkdownFlow
```

## 开发约定

- **核心解耦与零依赖**：业务逻辑放在 `<Plugin>/core/`，不得导入 `sublime` / `sublime_plugin`，且仅使用 Python 标准库，确保可直接用标准 Python 跑单测；顶层 `<plugin_snake>.py` 只做薄桥接层。
- **Python 版本兼容**：插件目录 `.python-version` 为 `3.14`，但 CI 矩阵测试 Python `3.12`–`3.14`，代码需保持 Python 3.12+ 兼容（文件头使用 `from __future__ import annotations`）。
- **测试**：使用标准库 `unittest`，修改 `core/` 逻辑时同步补充或更新对应测试。
- **新增插件**：在根目录新建独立插件文件夹并沿用上述布局，同时更新根目录 `README.md` 与 `.github/workflows/test.yml`。
