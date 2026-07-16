<div align="center">

<img src="media/hero.png" alt="Django ORM Lens — live sidebar and ER diagram for your Django models" width="100%"/>

<br/>
<br/>

# Django ORM Lens

### 在你的编辑器里、终端里,以及从你的 AI agent 那里,看清整个 Django schema。

每一个 app。每一个 model。每一个字段。每一种关系。分组呈现、可逐级展开,并且一键即可打开实时 ER 图。

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

Django ORM Lens 基于**同一个核心,提供三种分发形态**——选一个契合你工作流的方式。每一种都在 60 秒内完成。

**编辑器用户(VS Code / Cursor / Windsurf):** 安装扩展 → 打开任意 Django 项目 → 侧边栏树形结构 + ER 图自动出现。

```bash
code --install-extension frowningdev.django-orm-lens
```

**终端 / CI 用户:** 从 PyPI 安装 → 在任意包含 Django app 的目录下运行 `django-orm-lens`。

```bash
pip install django-orm-lens
django-orm-lens               # 欢迎信息 + 命令列表
django-orm-lens scan          # 扫描当前工作目录下的 app 与 model
```

**AI coding agent 用户(Cursor / Aider / Continue / Zed):** 带 MCP 额外依赖安装 → 在客户端配置里加一段 JSON。

```bash
pip install "django-orm-lens[mcp]"
```

然后参考下方[集成](#-集成)章节中的 MCP 配置片段。将 `DJANGO_ORM_LENS_ROOT` 指向你的 Django 项目的绝对路径。

---

## 📊 采用情况

<div align="center">

<!-- 头条拆分徽章(深色标签 · 彩色数值) -->

[![First-week installs](https://img.shields.io/badge/first--week_installs-1082%2B-3775a9?style=for-the-badge&logo=pypi&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Peak day](https://img.shields.io/badge/peak_day_installs-441-f97316?style=for-the-badge&logo=rocket&logoColor=white&labelColor=1e293b)](https://pypi.org/project/django-orm-lens/)
[![Unique cloners](https://img.shields.io/badge/unique_cloners_14d-171-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![VS Code rating](https://img.shields.io/badge/VS_Code_rating-5.0_%E2%98%85-eab308?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)

<br/>

<!-- 跨平台覆盖快照 -->

[![VS Code downloads](https://img.shields.io/badge/VS_Code_downloads-113-0c4b33?style=for-the-badge&logo=visualstudiocode&logoColor=white&labelColor=1e293b)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![GitHub views](https://img.shields.io/badge/GitHub_views_14d-256-24292f?style=for-the-badge&logo=github&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev/django-orm-lens)
[![LinkedIn posts](https://img.shields.io/badge/LinkedIn_posts_live-4-0a66c2?style=for-the-badge&logo=linkedin&logoColor=white&labelColor=1e293b)](https://linkedin.com/company/django-orm-lens)
[![Awesome-list PRs](https://img.shields.io/badge/awesome--list_PRs-2_pending-16a34a?style=for-the-badge&logo=awesomelists&logoColor=white&labelColor=1e293b)](https://github.com/FROWNINGdev)

<br/>

<!-- 实时计数器 + 目录 -->

[![PyPI weekly](https://img.shields.io/pypi/dw/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=weekly%20downloads&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![PyPI monthly](https://img.shields.io/pypi/dm/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=monthly%20downloads&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![GitHub stars](https://img.shields.io/github/stars/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=stars&labelColor=1e293b&color=eab308)](https://github.com/FROWNINGdev/django-orm-lens/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/FROWNINGdev/django-orm-lens?style=for-the-badge&logo=github&logoColor=white&label=forks&labelColor=1e293b&color=64748b)](https://github.com/FROWNINGdev/django-orm-lens/network/members)

<br/>

<!-- MCP 目录 -->

[![MCP Registry](https://img.shields.io/badge/MCP_Registry-official_listing-6f42c1?style=for-the-badge&labelColor=1e293b)](https://registry.modelcontextprotocol.io/)
[![CodeTriage](https://www.codetriage.com/frowningdev/django-orm-lens/badges/users.svg)](https://www.codetriage.com/frowningdev/django-orm-lens)
[![Glama.ai](https://img.shields.io/badge/Glama.ai-listed-0f172a?style=for-the-badge&labelColor=1e293b)](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)
[![mcp.so](https://img.shields.io/badge/mcp.so-listed-1f2937?style=for-the-badge&labelColor=1e293b)](https://mcp.so/servers/django-orm-lens)

<br/>

<!-- 技术栈 + 许可证 -->

[![VS Code Marketplace](https://img.shields.io/visual-studio-marketplace/v/frowningdev.django-orm-lens?style=for-the-badge&logo=visualstudiocode&logoColor=white&label=VS%20Code&labelColor=1e293b&color=0c4b33)](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens)
[![PyPI version](https://img.shields.io/pypi/v/django-orm-lens?style=for-the-badge&logo=pypi&logoColor=white&label=PyPI&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Python](https://img.shields.io/pypi/pyversions/django-orm-lens?style=for-the-badge&logo=python&logoColor=white&label=Python&labelColor=1e293b&color=3775a9)](https://pypi.org/project/django-orm-lens/)
[![Django](https://img.shields.io/badge/Django-4.0_%E2%80%93_5.1-092e20?style=for-the-badge&logo=django&logoColor=white&labelColor=1e293b)](https://www.djangoproject.com/)
[![License MIT](https://img.shields.io/badge/license-MIT-16a34a?style=for-the-badge&labelColor=1e293b)](LICENSE)

</div>

<sub><i>更新于 2026-07-15。PyPI 周/月下载量、GitHub stars / forks,以及 PyPI / VS Code 版本徽章均实时自动刷新。</i></sub>

> 如果这个工具下次帮你省下一次 `grep`——** [点个 star 让更多人发现它](https://github.com/FROWNINGdev/django-orm-lens/stargazers)**。

---

## ⚡ 安装

**VS Code / Cursor / Windsurf / 任意 Code 衍生版:**

```bash
code --install-extension frowningdev.django-orm-lens
```

或在扩展视图中搜索 **`Django ORM Lens`**。

**终端与 AI coding agent:**

```bash
pip install django-orm-lens              # 仅 CLI
pip install "django-orm-lens[mcp]"       # + 面向 AI agent 的 MCP server
```

要求 Python 3.9+。CLI 本身零运行时依赖。

<br/>

## 🎯 问题所在

> **离线可用。在损坏的 venv 上可用。在别人的电脑上可用。在 CI 里可用。**

你打开一个 Django 项目。它有 20 个 app。你需要回答一个简单的问题:

> _"哪个 app 拥有 `Order` model,它又是怎么和 `User` 关联的?"_

放在今天,这意味着:`Ctrl+P`,输入 "models",在 30 个搜索结果里滚动,打开五个文件,`Ctrl+F` 搜 `class Order`,读完 400 行 `ForeignKey('otherapp.Something')` 字符串,努力回想两个文件之前刚看到的内容。

**半天就这么没了。每次都是。每个项目都是。**

<br/>

## ✨ 使用 Django ORM Lens 之后

<table>
<tr>
<td width="50%" valign="top">

### 📚 一切尽在树形结构中

每个 app → 每个 model → 每个字段 → 每个 `Meta` 选项。按应用分组、字母排序、可展开。

图标让你一眼区分 `CharField`、`ForeignKey` 与 `ManyToManyField`。

</td>
<td width="50%" valign="top">

### 🕸️ 实时 ER 图

一条命令即可打开整张 schema 的 Mermaid 实体关系图。编辑时实时重绘。可导出为 SVG。

`ForeignKey`、`OneToOneField` 与 `ManyToManyField` 会变成带基数的箭头。

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔎 悬浮查看关系

在任意 Python 文件中悬浮于 `ForeignKey('app.Model')` 之上 → 弹出一张卡片,显示目标 model 的字段、关系,以及一个"跳转至"链接。无需 `Ctrl+F`,无需文件对话框。

</td>
<td width="50%" valign="top">

### 🧭 跳转到定义

点击树中的任意字段 → 光标落在精确的那一行。可按 app 或 model 名过滤树。拆分后的 `models/` 包也完全支持。

</td>
</tr>
<tr>
<td width="50%" valign="top">

### ⚡ 零配置

无需 `DJANGO_SETTINGS_MODULE`。无需 `runserver`。静态解析 `models.py`。在损坏的 venv、缺失的依赖,或别人的电脑上都能工作。

</td>
<td width="50%" valign="top">

### 🎨 原生 VS Code UI

深色主题。浅色主题。你的主题。跟随你的图标主题、字体、键位绑定。不花哨,不贴牌。

</td>
</tr>
</table>

<br/>

## 📸 它长什么样

<div align="center">
<img src="media/hero.png" alt="Django ORM Lens sidebar showing an app's models with fields, relations, and Meta options" width="90%"/>
</div>

**扩展中还包含:**

- 🕸️ **实时 ER 图** — Mermaid 基数箭头、边标签(`CASCADE`、`through Model`、`as related_name`)、感知主题、一键导出 SVG
- 🔎 **悬浮卡片** — 悬浮于任意 `ForeignKey('app.Model')` 或 `ManyToManyField(...)` 之上,带一键跳转链接
- 🧭 **CodeLens** — 在每一行 `class Model` 上方:字段数、关系数,以及一个 **打开 ER 图** 操作
- 🎨 **具名主题** — 图表 webview 支持 `auto` / `default` / `dark` / `forest` / `neutral`

<br/>

## 🤖 面向终端与 AI coding agent

驱动 VS Code 扩展的同一个解析器,也作为独立的 Python 包发布——附带一个可选的 **MCP(Model Context Protocol)server**,让任何兼容 MCP 的 AI agent 都能浏览你的 Django schema,而无需导入 Django 或启动你的应用。

### CLI

```bash
django-orm-lens scan -f json          # 每个 app、每个 model、每个字段
django-orm-lens describe blog.Post    # 以 Markdown 输出单个 model
django-orm-lens hover blog.Post       # 紧凑的悬浮卡片
django-orm-lens list | fzf            # 扁平的 app.Model 列表 —— 可管道到任意位置
django-orm-lens er > schema.mmd       # Mermaid ER 图
```

每条命令都接受 `--path <dir>` 与 `--exclude <glob>`。

### MCP server

只需向你的 agent 注册一次,它便会暴露五个只读工具:

| Tool | 用途 |
| --- | --- |
| `list_apps` | 工作区中每个 Django app 及其 model 数量 |
| `list_models` | 扁平的 `app.Model` 列表,可附加 app 过滤 |
| `describe_model` | 单个 model 完整的字段 / 关系 / Meta 详情 |
| `find_relations` | 单个 model 的入站 + 出站关系 |
| `er_diagram` | 整个工作区的 Mermaid `erDiagram` |

```bash
# 直接启动
django-orm-lens-mcp

# 或通过 CLI 子命令
django-orm-lens mcp
```

设置 `DJANGO_ORM_LENS_ROOT=/abs/path/to/project` 即可指向任意位置。

<br/>

## 🔌 集成

| Client | 如何启用 | 状态 |
|---|---|:-:|
| **VS Code** | `code --install-extension frowningdev.django-orm-lens` | ✅ |
| **Cursor** | 同样的 VSIX + 在 `~/.cursor/mcp.json` 中可选的 MCP 条目 | ✅ |
| **Windsurf / VSCodium / 任意 Code 衍生版** | 从 [Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) 或 [GitHub Releases](https://github.com/FROWNINGdev/django-orm-lens/releases) 安装 VSIX | ✅ |
| **Aider** | 将 `django-orm-lens-mcp` 加入你的 `mcp.json` | ✅ (via MCP) |
| **Continue.dev** | 在 `~/.continue/config.json` 中注册 MCP server | ✅ (via MCP) |
| **Zed** | 在 Zed 设置中注册 MCP server | ✅ (via MCP) |
| **任意兼容 MCP 的客户端** | 将 `command` 指向 `django-orm-lens-mcp`,设置 `DJANGO_ORM_LENS_ROOT` | ✅ |
| **可通过 [MCP Registry](https://registry.modelcontextprotocol.io/) 发现** | 官方的 Model Context Protocol server 目录 | ✅ |
| **纯终端 / CI** | `pip install django-orm-lens && django-orm-lens scan` | ✅ |

### 示例:Cursor / 任意 MCP 客户端

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

## 🚀 开始使用(30 秒)

**在 VS Code 中:**

1. `code --install-extension frowningdev.django-orm-lens`
2. 打开一个包含 `manage.py` 或 `models.py` 的文件夹
3. 点击活动栏中的 **Django ORM Lens** 图标
4. 展开 app → model → field
5. 点击面板顶部的 **type-hierarchy** 图标 → ER 图在代码旁打开

**在终端中:**

```bash
pip install django-orm-lens
cd my-django-project
django-orm-lens scan -f table
```

**作为 AI agent 工具:**

```bash
pip install "django-orm-lens[mcp]"
```

…然后在你的 agent 的 MCP 配置中注册 `django-orm-lens-mcp`(参见上方[集成](#-集成)表)。

没有设置界面。无需登录。无遥测。

<br/>

## 🎯 它适合谁

- **Django 开发者**——接手一个有 10+ 个 app、在 `models.py` 里迷失的代码库。
- **外包 / 自由职业工程师**——需要在第一小时而非第一周,摸清一个陌生的 Django 项目。
- **为新员工做入职培训的团队**——想要一览无余的 schema 视图,而不必搭建文档基础设施。
- **AI-agent 重度用户**(Cursor / Aider / Zed / Continue / 任意兼容 MCP 的客户端)——需要 agent 准确回答 schema 问题,而无需给它数据库凭据或启动 Django。
- **CI 流水线**——在不导入项目的前提下,校验 schema 形态(例如"我们是不是不小心改坏了某个 `related_name`?")。
- **独立开发者**——在损坏的 venv 或别人的电脑上,没有 `runserver`、没有 `manage.py migrate`,依然可用。

<br/>

## 🗺️ 市场定位

Django ORM Lens 处在 **编辑器工具** 与 **AI-agent 工具** 的交叉点——这个位置目前没有任何现成包覆盖:

| 细分领域 | 现有方案 | 你的代价 |
|---|---|---|
| 启动后画图 | `django-extensions graph_models` | 需要 Graphviz + Django 配置 + 可用的数据库 URL |
| 基于 Web 的查看器 | `django-schema-graph` | 需要运行中的 Django 服务器;多托管一样会坏的东西 |
| 管理后台 | Django Admin | 需要 runserver + 鉴权 + 数据库——适合数据,不适合架构 |
| 编辑器插件 | PyCharm 的 Django Structure | 锁定在 PyCharm;无 CLI,无 AI-agent 故事 |
| MCP server | (此前没有) | AI agent 凭源码猜测你的 schema,并不完美 |

**Django ORM Lens 是唯一一个由同一个解析器提供三种形态的工具有:** 一个 VS Code 扩展(任意 Code 衍生版)、一个零依赖 CLI(终端 + CI),以及一个 MCP server(AI agent)。全部静态。全部免费。全部 MIT。

<br/>

## 🤔 它有何不同?

| | **Django ORM Lens** | `django-extensions graph_models` | `django-schema-graph` | Django Admin | PyCharm Django Structure |
|---|:-:|:-:|:-:|:-:|:-:|
| 无需可启动的 Django 项目即可工作 | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| 零安装(无 graphviz,无服务器) | ✅ | ❌ | ❌ | ❌ | ❌ (需 PyCharm) |
| 在 VS Code / Cursor / 任意 Code 衍生版中可用 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 编辑器内的侧边栏树 | ✅ | ❌ | ❌ | ❌ | ✅ |
| 实时 ER 图 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 悬浮于 `ForeignKey` 的卡片 | ✅ | ❌ | ❌ | ❌ | ⚠️ |
| model 类上的 CodeLens | ✅ | ❌ | ❌ | ❌ | ❌ |
| 拆分 `models/` 包支持 | ✅ | ⚠️ | ⚠️ | ✅ | ✅ |
| 面向终端 / CI 的 CLI | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| 面向 AI agent 的 MCP server | ✅ | ❌ | ❌ | ❌ | ❌ |
| 可在 [MCP Registry](https://registry.modelcontextprotocol.io/) 中发现 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 免费且开源(MIT) | ✅ | ✅ | ✅ | ✅ | ❌ (付费 IDE) |
| Django 版本支持 | **4.0 – 5.2** | latest | 3.2 – 4.1 (自 2023 起停滞) | latest | latest |

> *`django-schema-graph` 自 2023-05 起未再更新,且不测试 Django 5.x。*

<br/>

## ⚙️ 配置

默认值已经得当且合理。如果你需要调整:

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

| 设置 | 类型 | 默认值 | 作用 |
|---|---|---|---|
| `djangoOrmLens.excludeGlobs` | `string[]` | 见上方 | 扫描时跳过的 glob 模式 |
| `djangoOrmLens.autoRefresh` | `boolean` | `true` | 在 `models.py` 变更时重新扫描 |

<br/>

## 🧭 命令

打开命令面板(`Ctrl+Shift+P` / `Cmd+Shift+P`),输入 "Django ORM Lens":

| 命令 | 作用 |
|---|---|
| `Django ORM Lens: Refresh` | 强制重新扫描工作区 |
| `Django ORM Lens: Show ER Diagram` | 并排打开 Mermaid ER 图 |
| `Django ORM Lens: Filter Models` | 按 app / model / field 名过滤树 |
| `Django ORM Lens: Clear Filter` | 恢复完整树 |
| `Django ORM Lens: Jump to Model` | 程序化 —— 由树点击与悬浮卡片触发 |

<br/>

## 🗺️ 路线图

**已发布**

- [x] 按 app 分组的侧边栏树
- [x] 实时 Mermaid ER 图
- [x] 悬浮于 `ForeignKey('app.Model')` 之上的卡片
- [x] 按名称过滤树
- [x] 拆分 `models/` 包支持
- [x] 将 ER 图导出为 SVG
- [x] 面向终端与 AI agent 的 Python CLI + MCP server
- [x] 空工作区的欢迎视图
- [x] 路径安全的跳转至定义,以及净化的悬浮 markdown
- [x] **v0.3.0** —— 每个 model 类上方的 CodeLens(`N 个字段 · N 个关系 · 打开 ER 图`)
- [x] **v0.3.0** —— 图上的边标签(`CASCADE`、`SET_NULL`、`PROTECT`、`related_name`)
- [x] **v0.3.0** — 具名配色主题(`auto` / `default` / `dark` / `forest` / `neutral`)
- [x] **v0.3.1** — M2M 边上的 `through_model`(由 [@kingrubic](https://github.com/kingrubic) 贡献)
- [x] **v0.3.1** — 列入[官方 MCP Registry](https://registry.modelcontextprotocol.io/) + [Glama.ai](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)

**下一步**

- [ ] webview 内的缩放 + 小地图 + 自动布局([#4](https://github.com/FROWNINGdev/django-orm-lens/issues/4))
- [ ] 在 `.filter()` / `.exclude()` / `.annotate()` 内的 ORM 查询自动补全([#3](https://github.com/FROWNINGdev/django-orm-lens/issues/3))
- [ ] app / model 开关复选框,以清理庞大的 schema

**更之后**

- [ ] 迁移依赖图
- [ ] 第三方字段支持(`django-mptt`、`django-taggit`、`django-model-utils`)
- [ ] JetBrains / PyCharm 插件(如果有需求)

通过为你对应的 [issue](https://github.com/FROWNINGdev/django-orm-lens/issues) 点 👍 来投票。

<br/>

## ❓ 常见问题

<details>
<summary><b>你们会把我的代码发到服务器吗?</b></summary>
<br/>
不会。每一个字节都留在你的机器上。解析器是纯 TypeScript(扩展)或纯 Python(CLI)。没有 LLM 调用,没有遥测,没有分析,没有错误上报。Mermaid 渲染器运行在 VS Code 的 webview 沙箱内。
</details>

<details>
<summary><b>它能配合 Poetry / uv / conda / 完全没有 venv 使用吗?</b></summary>
<br/>
可以。扩展直接读取 Python 源码——它不导入 Django,也不关心你用哪个包管理器。CLI 要求 Python 3.9+,仅此而已。
</details>

<details>
<summary><b>我的 model 拆分在 <code>models/</code> 包内的多个文件里。能工作吗?</b></summary>
<br/>
可以,自 v0.2.0 起。扩展与 CLI 都会遍历 <code>models/*.py</code>,与传统 <code>models.py</code> 并列。
</details>

<details>
<summary><b>我能把它用于 DRF serializers、Wagtail、Oscar,或第三方基类 model 吗?</b></summary>
<br/>
任何看起来像 Django model 的类都会被识别:继承自 <code>models.Model</code> 的子类、以 <code>Abstract</code> 开头的抽象基类、以 <code>Mixin</code> 结尾的常见 mixin,以及已知的基类名如 <code>TimeStampedModel</code> 或 <code>PolymorphicModel</code>。非 model 类(<code>ModelAdmin</code>、<code>ModelSerializer</code>、<code>Form</code>、<code>View</code>、<code>Manager</code>,……)会被过滤掉。
</details>

<details>
<summary><b>哪些 AI agent 能用这个 MCP server?</b></summary>
<br/>
任何兼容 MCP 的客户端——Cursor、Aider、Continue.dev、Zed,以及任何其他讲该协议的工具。只需将 <code>command</code> 指向已安装的 <code>django-orm-lens-mcp</code> 二进制。参见 <a href="#-集成">集成</a> 章节。
</details>

<details>
<summary><b>有 JetBrains / PyCharm 版本吗?</b></summary>
<br/>
还没有。PyCharm 的 Django Structure 工具窗口已经不错,所以价值差较小。如果足够多人提出需求,就值得去做。
</details>

<br/>

## 🆘 支持

- 🐛 **Bug 报告** — [GitHub Issues](https://github.com/FROWNINGdev/django-orm-lens/issues)(请附上最小化的 `models.py` 片段)
- 💡 **功能请求 / 想法** — [GitHub Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions)
- 📝 **Marketplace 评价** — [为扩展评分](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens&ssr=false#review-details)(让项目继续前进的最快信号)
- 🐍 **PyPI 页面** — [pypi.org/project/django-orm-lens](https://pypi.org/project/django-orm-lens/)
- 💚 **Sponsor** — [github.com/sponsors/FROWNINGdev](https://github.com/sponsors/FROWNINGdev)

<br/>

## ✨ 贡献者

感谢这些了不起的人([emoji 含义](https://allcontributors.org/docs/en/emoji-key))——所有类型的贡献都算数,不只是代码。翻译、文档、截图、bug 报告、答疑,都是一等公民。

刚到这里?参见 [CONTRIBUTING.md → "如何成为贡献者"](.github/CONTRIBUTING.md#how-to-become-a-contributor-all-skill-levels-welcome),并浏览 [`good first issue`](https://github.com/FROWNINGdev/django-orm-lens/labels/good%20first%20issue)。

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

本项目遵循 [all-contributors](https://allcontributors.org) 规范。要加入,只需在任意 issue 或 PR 下评论 `@all-contributors please add @your-username for docs`(或 `code`、`translation`、`design`、`ideas`、`question`、`bug`、`test`、`tutorial`、`example`,……)。

<br/>

## 📜 许可证

MIT © [FROWNINGdev](https://github.com/FROWNINGdev)

<br/>

<div align="center">

**为在乎自己代码库的开发者而做。**

[Marketplace](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens) · [PyPI](https://pypi.org/project/django-orm-lens/) · [GitHub](https://github.com/FROWNINGdev/django-orm-lens) · [Issues](https://github.com/FROWNINGdev/django-orm-lens/issues) · [Discussions](https://github.com/FROWNINGdev/django-orm-lens/discussions) · [Sponsor](https://github.com/sponsors/FROWNINGdev)

</div>
