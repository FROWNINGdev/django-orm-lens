[English](README.md) · [Русский](README.ru.md) · [Español](README.es.md) · **中文**

<div align="center">

<img src="media/hero.png" alt="Django ORM Lens — live sidebar and ER diagram for your Django models" width="100%"/>

<br/>
<br/>

# Django ORM Lens

### 在编辑器、终端和 AI 智能体中，一览你的整个 Django 数据结构。

每个 app、每个模型、每个字段、每条关系。分组、可导航，一次按键即可生成实时 ER 图。

<br/>

[![Install from Marketplace](https://img.shields.io/badge/VS_Code-Install-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![PyPI](https://img.shields.io/badge/PyPI-pip_install-3775a9?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/django-orm-lens/)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-listed-6f42c1?style=for-the-badge)](https://registry.modelcontextprotocol.io/)
[![Glama](https://img.shields.io/badge/Glama-listed-0f172a?style=for-the-badge)](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)
[![mcp.so](https://img.shields.io/badge/mcp.so-listed-1f2937?style=for-the-badge)](https://mcp.so/servers/django-orm-lens)
[![Star on GitHub](https://img.shields.io/badge/★-Star_on_GitHub-24292f?style=for-the-badge&logo=github&logoColor=white)](https://github.com/FROWNINGdev/django-orm-lens)
[![Sponsor](https://img.shields.io/badge/♥-Sponsor-db61a2?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/FROWNINGdev)

<br/>

[![Version](https://img.shields.io/visual-studio-marketplace/v/frowningdev.django-orm-lens?color=0c4b33&label=extension&logo=visualstudiocode)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Installs](https://img.shields.io/visual-studio-marketplace/i/frowningdev.django-orm-lens?color=0c4b33&label=installs)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![Rating](https://img.shields.io/visual-studio-marketplace/r/frowningdev.django-orm-lens?color=0c4b33&label=rating)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)
[![PyPI version](https://img.shields.io/pypi/v/django-orm-lens?color=3775a9&label=pypi)](https://pypi.org/project/django-orm-lens/)
[![Python](https://img.shields.io/pypi/pyversions/django-orm-lens?color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![License MIT](https://img.shields.io/badge/license-MIT-0c4b33?style=flat)](LICENSE)
[![CI](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/FROWNINGdev/django-orm-lens/actions/workflows/ci.yml)

</div>

---

## 🎯 选择你的路径

Django ORM Lens 基于同一核心提供**三种发行形式** —— 选择最贴合你工作流的那种。每种都能在 60 秒内跑起来。

**编辑器用户（VS Code / Cursor / Windsurf）：** 安装扩展 → 打开任意 Django 项目 → 侧边栏树形视图与 ER 图立即呈现。

```bash
code --install-extension frowningdev.django-orm-lens
```

**终端 / CI 用户：** 从 PyPI 安装 → 在任意包含 Django app 的目录下运行 `django-orm-lens`。

```bash
pip install django-orm-lens
django-orm-lens               # welcome + commands
django-orm-lens scan          # scan cwd for apps and models
```

**AI 编码智能体用户（Cursor / Aider / Continue / Zed）：** 安装 MCP 附加组件 → 在客户端配置中添加一段 JSON。

```bash
pip install "django-orm-lens[mcp]"
```

然后使用下面 [Integrations](#-integrations) 章节中的 MCP 配置片段。将 `DJANGO_ORM_LENS_ROOT` 指向你的 Django 项目的绝对路径。

---

## 📊 项目动态

<div align="center">

<!-- Headline split-badges (dark label · colored value) -->

[![First-week installs](https://img.shields.io/badge/first--week_installs-1814-3775a9?style=for-the-badge&logo=pypi&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Peak day](https://img.shields.io/badge/peak_day_installs-441-f97316?style=for-the-badge&logo=rocket&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Unique cloners](https://img.shields.io/badge/unique_cloners_14d-279-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![VS Code rating](https://img.shields.io/badge/VS_Code_rating-5.0_%E2%98%85-eab308?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)

<br/>

<!-- Cross-platform reach snapshot -->

[![VS Code installs](https://img.shields.io/badge/VS_Code_installs-6-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![GitHub views](https://img.shields.io/badge/GitHub_views_14d-381-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![LinkedIn posts](https://img.shields.io/badge/LinkedIn_posts_live-7-0a66c2?style=for-the-badge&logo=linkedin&logoColor=white&labelColor=1e293b)](https://linkedin.com/company/django-orm-lens)
[![Awesome-list PRs](https://img.shields.io/badge/awesome--list_PRs-4_pending-16a34a?style=for-the-badge&logo=awesomelists&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev)
[![Community PRs merged](https://img.shields.io/badge/community_PRs_merged-5-8b5cf6?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens/pulls?q=is%3Apr+is%3Amerged+-author%3AFROWNINGdev)

<br/>

<!-- Live counters + directories -->

[![PyPI downloads total](https://img.shields.io/pepy/dt/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=total%20downloads&labelColor=1e293b&color=3775a9)](https://pepy.tech/project/django-orm-lens)
[![PyPI weekly](https://img.shields.io/badge/weekly_downloads-1895-3775a9?style=for-the-badge&logo=pypi&logoColor=white&labelColor=1e293b)](https://pepy.tech/project/django-orm-lens)
[![GitHub stars](https://img.shields.io/github/stars/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=stars&labelColor=1e293b&color=eab308)](https://github.com/FROWNINGdev/django-orm-lens/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=forks&labelColor=1e293b&color=64748b)](https://github.com/FROWNINGdev/django-orm-lens/network/members)

<br/>

<!-- MCP directories -->

[![MCP Registry](https://img.shields.io/badge/MCP_Registry-official_listing-6f42c1?style=for-the-badge&labelColor=1e293b)](https://registry.modelcontextprotocol.io/)
[![CodeTriage](https://img.shields.io/badge/CodeTriage-help_triage-2ec4b6?style=for-the-badge&labelColor=1e293b)](https://www.codetriage.com/frowningdev/django-orm-lens)
[![Glama.ai](https://img.shields.io/badge/Glama.ai-listed-0f172a?style=for-the-badge&labelColor=1e293b)](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)
[![mcp.so](https://img.shields.io/badge/mcp.so-listed-1f2937?style=for-the-badge&labelColor=1e293b)](https://mcp.so/servers/django-orm-lens)

<br/>

<!-- Tech stack + license -->

[![VS Code v0.5.1](https://img.shields.io/badge/VS_Code-v0.5.1-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![PyPI version](https://img.shields.io/pypi/v/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Python](https://img.shields.io/pypi/pyversions/django-orm-lens?style=for-the-badge&logo=python&logoColor=white&label=Python&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Django](https://img.shields.io/badge/Django-4.0_%E2%80%93_5.1-092e20?style=for-the-badge&logo=django&logoColor=white&labelColor=1e293b)](https://www.djangoproject.com/)
[![License MIT](https://img.shields.io/badge/license-MIT-16a34a?style=for-the-badge&labelColor=1e293b)](LICENSE)

</div>

<sub><i>更新于 2026-07-19。GitHub stars / forks 与累计下载量（通过 pepy.tech）实时自动刷新；每周下载量以及 VS Code / PyPI 版本号在每次发布时更新。</i></sub>

> 如果这个工具下次帮你在一个陌生的 Django 项目里省掉一次 `grep` —— **[一颗 star 能帮助更多人发现它](https://github.com/FROWNINGdev/django-orm-lens/stargazers)**。

---

## ⚡ 安装

**VS Code / Cursor / Windsurf / 任意 Code 派生版：**

```bash
code --install-extension frowningdev.django-orm-lens
```

或者在扩展视图中搜索 **`Django ORM Lens`**。

**终端与 AI 编码智能体：**

```bash
pip install django-orm-lens              # CLI only
pip install "django-orm-lens[mcp]"       # + MCP server for AI agents
```

需要 Python 3.9+。CLI 运行时零依赖。

<br/>

## 🎯 待解决的问题

> **离线可用。venv 坏了也能用。在别人的电脑上也能用。在 CI 里也能用。**

你打开一个 Django 项目。它有 20 个 app。你需要回答一个简单的问题：

> _"哪个 app 拥有 `Order` 模型？它是怎么和 `User` 关联的？"_

今天，这意味着：`Ctrl+P`，输入 "models"，在 30 个匹配里滚动，打开五个文件，`Ctrl+F` 搜 `class Order`，翻过 400 行 `ForeignKey('otherapp.Something')` 字符串，努力回忆两个文件之前看到的信息。

**半天没了。每次都这样。每个项目都这样。**

<br/>

## ✨ 有了 Django ORM Lens

<table>
<tr>
<td width="50%" valign="top">

### 📚 一棵覆盖一切的树

每个 app → 每个模型 → 每个字段 → 每个 `Meta` 选项。按应用分组、按字母排序、可展开。

图标能让你一眼分辨 `CharField`、`ForeignKey` 与 `ManyToManyField`。

</td>
<td width="50%" valign="top">

### 🕸️ 实时 ER 图

一条命令即可打开整个数据结构的 Mermaid 实体关系图。编辑代码时它会随之重绘。可导出为 SVG。

`ForeignKey`、`OneToOneField` 与 `ManyToManyField` 会呈现为标准的基数箭头。

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔎 悬停查看关系

在任意 Python 文件中悬停到 `ForeignKey('app.Model')` 上 → 弹出卡片，显示目标模型的字段、关系以及一个 "Jump to" 链接。无需 `Ctrl+F`，无需文件对话框。

</td>
<td width="50%" valign="top">

### 🧭 跳转到定义

在树中点击任意字段 → 光标精准落在对应行。可按 app 或模型名过滤树形视图。完整支持拆分的 `models/` 包。

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ 零配置

无需 `DJANGO_SETTINGS_MODULE`。无需 `runserver`。静态解析 `models.py`。venv 坏了、依赖缺失，甚至在别人的笔记本上也能工作。

</td>
<td width="50%" valign="top">

### 🎨 原生 VS Code UI

深色主题、浅色主题、你自定义的主题。遵循你的图标主题、字体和快捷键。不刺眼，不带品牌噪点。

</td>
</tr>
</table>

<br/>

## 📸 界面预览

<div align="center">
<img src="media/hero.png" alt="Django ORM Lens sidebar showing an app's models with fields, relations, and Meta options" width="90%"/>
</div>

**扩展中还包含：**

- 🕸️ **实时 ER 图** —— Mermaid 基数箭头、连线标签（`CASCADE`、`through Model`、`as related_name`），主题自适应，一键导出 SVG
- 🔎 **悬停卡片** —— 覆盖任意 `ForeignKey('app.Model')` 或 `ManyToManyField(...)`，附一键跳转链接
- 🧭 **CodeLens** —— 在每个 `class Model` 行上方显示：字段数、关系数，以及 **Open ER diagram** 操作
- 🎨 **命名主题** —— 图表 webview 的 `auto` / `default` / `dark` / `forest` / `neutral`

<br/>

## 🤖 面向终端与 AI 编码智能体

驱动 VS Code 扩展的解析器同时作为独立的 Python 包发布 —— 并可选配 **MCP（Model Context Protocol）服务器**，让任意兼容 MCP 的 AI 智能体在无需导入 Django、也无需启动你的应用的情况下浏览 Django 数据结构。

### CLI

```bash
django-orm-lens scan -f json          # every app, every model, every field
django-orm-lens describe blog.Post    # one model in Markdown
django-orm-lens hover blog.Post       # compact hover card
django-orm-lens list | fzf            # flat app.Model — pipes anywhere
django-orm-lens er > schema.mmd       # Mermaid ER diagram
```

每个命令都支持 `--path <dir>` 与 `--exclude <glob>`。

### MCP 服务器

在你的智能体中注册一次，即可暴露五个只读工具：

| 工具 | 用途 |
| --- | --- |
| `list_apps` | 工作区中的每个 Django app 以及模型数量 |
| `list_models` | 扁平的 `app.Model` 列表，可按 app 过滤 |
| `describe_model` | 单个模型的完整字段 / 关系 / Meta 详情 |
| `find_relations` | 单个模型的入向 + 出向关系 |
| `er_diagram` | 覆盖整个工作区的 Mermaid `erDiagram` |

```bash
# Start it directly
django-orm-lens-mcp

# Or via the CLI subcommand
django-orm-lens mcp
```

设置 `DJANGO_ORM_LENS_ROOT=/abs/path/to/project` 即可让它指向任意位置。

<br/>

## 🔌 集成

| 客户端 | 启用方式 | 状态 |
|---|---|:-:|
| **VS Code** | `code --install-extension frowningdev.django-orm-lens` | ✅ |
| **Cursor** | 相同的 VSIX + 可选地在 `~/.cursor/mcp.json` 中添加 MCP 条目 | ✅ |
| **Windsurf / VSCodium / 任意 Code 派生版** | 从 [Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) 或 [GitHub Releases](https://github.com/FROWNINGdev/django-orm-lens/releases) 安装 VSIX | ✅ |
| **Aider** | 将 `django-orm-lens-mcp` 添加到你的 `mcp.json` | ✅ (via MCP) |
| **Continue.dev** | 在 `~/.continue/config.json` 中注册 MCP 服务器 | ✅ (via MCP) |
| **Zed** | 在 Zed 设置中注册 MCP 服务器 | ✅ (via MCP) |
| **任意兼容 MCP 的客户端** | 将 `command` 指向 `django-orm-lens-mcp`，并设置 `DJANGO_ORM_LENS_ROOT` | ✅ |
| **可在 [MCP Registry](https://registry.modelcontextprotocol.io/) 中发现** | 官方 Model Context Protocol 服务器目录 | ✅ |
| **纯终端 / CI** | `pip install django-orm-lens && django-orm-lens scan` | ✅ |

### 示例：Cursor / 任意 MCP 客户端

```jsonc
{
  "mcpServers": {
    "django-orm-lens": {
      "command": "django-orm-lens-mcp",
      "env": { "DJANGO_ORM_LENS_ROOT": "/abs/path/to/your/project" }
    }
  }
}
```

<br/>

## 🚀 快速上手（30 秒）

**在 VS Code 中：**

1. `code --install-extension frowningdev.django-orm-lens`
2. 打开包含 `manage.py` 或 `models.py` 的文件夹
3. 点击活动栏中的 **Django ORM Lens** 图标
4. 展开 apps → models → fields
5. 点击面板顶部的 **type-hierarchy** 图标 → ER 图会在代码旁边打开

**在终端中：**

```bash
pip install django-orm-lens
cd my-django-project
django-orm-lens scan -f table
```

**作为 AI 智能体工具：**

```bash
pip install "django-orm-lens[mcp]"
```

…然后在你的智能体 MCP 配置中注册 `django-orm-lens-mcp`（参见上面的 [Integrations](#-integrations) 表格）。

无设置界面。无需登录。零遥测。

<br/>

## 🎯 适用人群

- **Django 开发者** —— 接手一个 10+ apps 的代码库，在 `models.py` 的丛林里迷路。
- **外包 / 自由职业工程师** —— 需要在第一小时内（而不是第一周内）搞懂一个陌生的 Django 项目。
- **在为新员工做入职的团队** —— 想要一眼看清的数据结构视图，而不必额外搭建一套文档基础设施。
- **AI 智能体重度用户**（Cursor / Aider / Zed / Continue / 任意兼容 MCP 的客户端）—— 需要智能体准确回答关于数据结构的问题，同时又不必给它数据库凭据或启动 Django。
- **CI 流水线** —— 校验数据结构形态（例如 "我们是不是不小心破坏了某个 `related_name`？"），无需导入项目。
- **单干的独立开发者** —— venv 坏了、在别人的电脑上工作 —— 无需 `runserver`，无需 `manage.py migrate`，依然可用。

<br/>

## 🗺️ 市场定位

Django ORM Lens 处在 **编辑器工具** 与 **AI 智能体工具** 的交叉地带 —— 一个此前没有现成方案覆盖的位置：

| 细分 | 现有方案 | 代价 |
|---|---|---|
| 启动后生成图 | `django-extensions graph_models` | 需要 Graphviz + Django settings + 可用的 DB URL |
| Web 查看器 | `django-schema-graph` | 需要运行中的 Django 服务器；又多一个可能出故障的东西 |
| 管理面板 | Django Admin | 需要 runserver + 认证 + 数据库 —— 适合看数据，不适合看架构 |
| 编辑器插件 | PyCharm 的 Django Structure | 锁定 PyCharm；没有 CLI，没有 AI 智能体入口 |
| MCP 服务器 | （此前没有） | AI 智能体只能从源码里靠猜来理解你的数据结构，不完美 |

**Django ORM Lens 是唯一一个基于同一个解析器同时提供三种形态的工具：** 一个 VS Code 扩展（任意 Code 派生版）、一个零依赖 CLI（终端 + CI），以及一个 MCP 服务器（AI 智能体）。全部静态。全部免费。全部 MIT。

<br/>

## 🤔 它与众不同在哪里？

| | **Django ORM Lens** | `django-extensions graph_models` | `django-schema-graph` | Django Admin | PyCharm Django Structure |
|---|:-:|:-:|:-:|:-:|:-:|
| 无需可启动的 Django 项目也能工作 | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| 零安装（无 graphviz、无服务器） | ✅ | ❌ | ❌ | ❌ | ❌（需要 PyCharm） |
| 在 VS Code / Cursor / 任意 Code 派生版中工作 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 编辑器内侧边栏树形视图 | ✅ | ❌ | ❌ | ❌ | ✅ |
| 实时 ER 图 | ✅ | ✅ | ✅ | ❌ | ❌ |
| `ForeignKey` 悬停卡片 | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| 模型类上的 CodeLens | ✅ | ❌ | ❌ | ❌ | ❌ |
| 拆分的 `models/` 包支持 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ |
| 面向终端 / CI 的 CLI | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| 面向 AI 智能体的 MCP 服务器 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 可在 [MCP Registry](https://registry.modelcontextprotocol.io/) 中发现 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 免费开源（MIT） | ✅ | ✅ | ✅ | ✅ | ❌（付费 IDE） |
| Django 版本支持 | **4.0 – 5.2** | latest | 3.2 – 4.1（自 2023 起停更） | latest | latest |

> *`django-schema-graph` 自 2023-05 起未再更新，且未测试 Django 5.x。*

<br/>

## ⚙️ 配置

默认值经过精心设计，通常够用。如果你需要调整：

```jsonc
// .vscode/settings.json
{
  "djangoOrmLens.excludeGlobs": [
    "**/migrations/**",
    "**/node_modules/**",
    "**/venv/**",
    "**/.venv/**",
    "**/env/**"
  ],
  "djangoOrmLens.autoRefresh": true
}
```

| 设置项 | 类型 | 默认值 | 作用 |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | 见上方 | 扫描时要跳过的 glob 模式 |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | 在 `models.py` 变化时重新扫描 |

<br/>

## 🧭 命令

打开命令面板（`Ctrl+Shift+P` / `Cmd+Shift+P`），输入 "Django ORM Lens"：

| 命令 | 作用 |
|---|---|
| `Django ORM Lens: Refresh` | 强制重新扫描工作区 |
| `Django ORM Lens: Show ER Diagram` | 在旁边打开 Mermaid ER 图 |
| `Django ORM Lens: Filter Models` | 按 app / 模型 / 字段名过滤树形视图 |
| `Django ORM Lens: Clear Filter` | 恢复完整的树形视图 |
| `Django ORM Lens: Jump to Model` | 程序化触发 —— 由树中点击与悬停卡片调用 |

<br/>

## 🗺️ 路线图

**已发布**

- [x] 按 app 分组的侧边栏树形视图
- [x] 实时 Mermaid ER 图
- [x] `ForeignKey('app.Model')` 悬停卡片
- [x] 按名称过滤树形视图
- [x] 拆分的 `models/` 包支持
- [x] 将 ER 图导出为 SVG
- [x] 面向终端与 AI 智能体的 Python CLI + MCP 服务器
- [x] 空工作区的欢迎视图
- [x] 路径安全的跳转到定义与经过净化的悬停 markdown
- [x] **v0.3.0** —— 每个模型类上方的 CodeLens（`N fields · N relations · Open ER diagram`）
- [x] **v0.3.0** —— 图表上的连线标签（`CASCADE`、`SET_NULL`、`PROTECT`、`related_name`）
- [x] **v0.3.0** —— 命名的颜色主题（`auto` / `default` / `dark` / `forest` / `neutral`）
- [x] **v0.3.1** —— M2M 连线上的 `through_model`（由 [@kingrubic](https://github.com/kingrubic) 贡献）
- [x] **v0.3.1** —— 收录到 [官方 MCP Registry](https://registry.modelcontextprotocol.io/) 与 [Glama.ai](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)

**下一步**

- [ ] webview 内的缩放 + 缩略图 + 自动布局（[#4](https://github.com/FROWNINGdev/django-orm-lens/issues/4)）
- [ ] `.filter()` / `.exclude()` / `.annotate()` 内的 ORM 查询自动补全（[#3](https://github.com/FROWNINGdev/django-orm-lens/issues/3)）
- [ ] app / 模型的显隐勾选框，用于化繁为简

**长期**

- [ ] 迁移依赖关系图
- [ ] 第三方字段支持（`django-mptt`、`django-taggit`、`django-model-utils`）
- [ ] JetBrains / PyCharm 插件（如有需求）

用 👍 为对应的 [issue](https://github.com/FROWNINGdev/django-orm-lens/issues) 投票。

<br/>

## ❓ 常见问题

<details>
<summary><b>会把我的代码发到某台服务器上吗？</b></summary>
<br/>
不会。每一个字节都留在你的机器上。解析器是纯 TypeScript（扩展）或纯 Python（CLI）。无 LLM 调用、无遥测、无分析、无错误上报。Mermaid 渲染在 VS Code 的 webview 沙箱里运行。
</details>

<details>
<summary><b>它能配合 Poetry / uv / conda / 或者根本没有 venv 工作吗？</b></summary>
<br/>
可以。扩展直接读取 Python 源码 —— 不导入 Django，也不关心你用什么包管理器。CLI 只需要 Python 3.9+，仅此而已。
</details>

<details>
<summary><b>我的模型拆分到了 <code>models/</code> 包下的多个文件里。这样能工作吗？</b></summary>
<br/>
可以，自 v0.2.0 起。扩展与 CLI 都会在遍历经典 <code>models.py</code> 的同时遍历 <code>models/*.py</code>。
</details>

<details>
<summary><b>能配合 DRF serializers、Wagtail、Oscar 或第三方基类模型吗？</b></summary>
<br/>
任何看起来像 Django 模型的类都会被识别：<code>models.Model</code> 的子类、以 <code>Abstract</code> 开头的抽象基类、以 <code>Mixin</code> 结尾的常见混入，以及像 <code>TimeStampedModel</code> 或 <code>PolymorphicModel</code> 这样的已知基类名。非模型类（<code>ModelAdmin</code>、<code>ModelSerializer</code>、<code>Form</code>、<code>View</code>、<code>Manager</code>、……）会被过滤掉。
</details>

<details>
<summary><b>哪些 AI 智能体可以使用 MCP 服务器？</b></summary>
<br/>
任何兼容 MCP 的客户端 —— Cursor、Aider、Continue.dev、Zed，以及任何其他支持该协议的工具。只需将 <code>command</code> 指向已安装的 <code>django-orm-lens-mcp</code> 可执行文件即可。详见 <a href="#-integrations">Integrations</a> 章节。
</details>

<details>
<summary><b>有 JetBrains / PyCharm 版本吗？</b></summary>
<br/>
暂时没有。PyCharm 的 Django Structure 工具窗口本身就不错，价值增量会小一些。如果有足够多的人提出需求，就值得去做。
</details>

<br/>

## 🆘 支持

- 🐛 **Bug 反馈** —— [GitHub Issues](https://github.com/FROWNINGdev/django-orm-lens/issues)（请附上最小可复现的 `models.py` 片段）
- 💡 **功能建议 / 想法** —— [GitHub Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions)
- 📝 **Marketplace 评价** —— [为扩展打分](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)（推动项目前进最快的信号）
- 🐍 **PyPI 页面** —— [pypi.org/project/django-orm-lens](https://pypi.org/project/django-orm-lens/)
- 💚 **赞助** —— [github.com/sponsors/FROWNINGdev](https://github.com/sponsors/FROWNINGdev)

<br/>

## ✨ 贡献者

感谢这些出色的伙伴（[表情释义](https://allcontributors.org/docs/en/emoji-key)）—— 各类贡献都被计入，不仅仅是代码。翻译、文档、截图、bug 反馈、答疑，都是一等公民。

新来的？请阅读 [CONTRIBUTING.md → "How to become a contributor"](.github/CONTRIBUTING.md#how-to-become-a-contributor-all-skill-levels-welcome) 并浏览 [`good first issue`](https://github.com/FROWNINGdev/django-orm-lens/labels/good%20first%20issue)。

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/FROWNINGdev"><img src="https://avatars.githubusercontent.com/u/218313741?v=4?s=80" width="80px;" alt="frowningdev"/><br /><sub><b>frowningdev</b></sub></a><br /><a href="https://github.com/FROWNINGdev/django-orm-lens/commits?author=FROWNINGdev" title="Code">💻</a> <a href="#doc-FROWNINGdev" title="Documentation">📖</a> <a href="#design-FROWNINGdev" title="Design">🎨</a> <a href="#ideas-FROWNINGdev" title="Ideas, Planning, & Feedback">🤔</a> <a href="#maintenance-FROWNINGdev" title="Maintenance">🚧</a> <a href="#review-FROWNINGdev" title="Reviewed Pull Requests">👀</a> <a href="#test-FROWNINGdev" title="Tests">⚠️</a> <a href="#infra-FROWNINGdev" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/kingrubic"><img src="https://avatars.githubusercontent.com/u/116256161?v=4?s=80" width="80px;" alt="Bao"/><br /><sub><b>Bao</b></sub></a><br /><a href="https://github.com/FROWNINGdev/django-orm-lens/commits?author=kingrubic" title="Code">💻</a> <a href="#test-kingrubic" title="Tests">⚠️</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

本项目遵循 [all-contributors](https://allcontributors.org) 规范。想被加入名单，请在任意 issue 或 PR 中评论 `@all-contributors please add @your-username for docs`（或 `code`、`translation`、`design`、`ideas`、`question`、`bug`、`test`、`tutorial`、`example`……）。

<br/>

## 📜 许可证

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)

<br/>

<div align="center">

**为在意自己代码库的开发者而生。**

[Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) · [PyPI](https://pypi.org/project/django-orm-lens/) · [GitHub](https://github.com/FROWNINGdev/django-orm-lens) · [Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) · [Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions) · [Sponsor](https://github.com/sponsors/FROWNINGdev)

</div>
