# django-orm-lens

<!-- mcp-name: io.github.FROWNINGdev/django-orm-lens -->

**Static analysis + MCP server for Django models.** Terminal- and AI-agent-friendly.

Listed in the official [MCP Registry](https://registry.modelcontextprotocol.io/) as `io.github.FROWNINGdev/django-orm-lens`.

Ships with a zero-dependency parser, a JSON/Markdown/table CLI, and an optional
MCP (Model Context Protocol) server so any AI coding agent — Cursor, Aider,
Continue, and any other MCP client — can navigate your Django schema without
importing Django or spinning up your app.

Companion to the [Django ORM Lens VS Code
extension](https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens).

---

## Install

```bash
# Core CLI (zero third-party deps)
pip install django-orm-lens

# With the MCP server (adds the `mcp` package)
pip install "django-orm-lens[mcp]"
```

Requires Python **3.9+**. Works on Linux, macOS, and Windows.

---

## CLI usage

```bash
# Scan a Django project for models (JSON, Markdown, or table)
django-orm-lens scan -f json
django-orm-lens scan -f markdown
django-orm-lens scan -f table

# Describe one model
django-orm-lens describe blog.Post
django-orm-lens describe Post -f json

# Compact hover card (great for pipeing into your editor)
django-orm-lens hover blog.Post

# Flat list — pipes into fzf, grep, etc.
django-orm-lens list | fzf

# Emit a Mermaid ER diagram
django-orm-lens er > schema.mmd
django-orm-lens er -o schema.mmd
```

Every command accepts `--path <dir>` and repeatable `--exclude <glob>`. Defaults
skip `migrations/`, `venv/`, `.venv/`, `env/`, and `node_modules/`.

---

## MCP server — for AI coding agents

The MCP server exposes five read-only tools that any MCP-compatible agent can
call while it edits your Django project:

| Tool | Purpose |
| --- | --- |
| `list_apps` | Every Django app in the workspace with model counts |
| `list_models` | Flat `app.Model` list, optional app filter |
| `describe_model` | Full field / relation / Meta detail for one model |
| `find_relations` | Inbound + outbound relations for one model |
| `er_diagram` | Mermaid `erDiagram` string for the whole workspace |

### Start the server manually

```bash
django-orm-lens-mcp     # dedicated entry point
# or
django-orm-lens mcp     # subcommand
```

**Workspace resolution (py-1.3.0+).** Priority: explicit `workspace_root`
argument on the tool call → `DJANGO_ORM_LENS_ROOT` env var → current working
directory. If none resolves to a Django project (`manage.py`, `django` in
`pyproject.toml`, or any `models.py`) you get a structured error envelope
back — `{"error": "WORKSPACE_NOT_DJANGO", "hint": "…"}` — instead of an
empty list, so the agent knows what to do next.

Optional sandbox: set `DJANGO_ORM_LENS_ALLOWED_ROOTS` (`;`-separated on
Windows, `:`-separated elsewhere) to a whitelist of prefixes; any path
outside them is rejected with `WORKSPACE_NOT_ALLOWED`.

### Register it with an agent

**Cursor** — add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "django-orm-lens": {
      "command": "django-orm-lens-mcp",
      "env": { "DJANGO_ORM_LENS_ROOT": "/abs/path/to/your/project" }
    }
  }
}
```

**Any MCP client** — same shape, generic tool. Point `command` at the
installed `django-orm-lens-mcp` binary. Two ways to tell it which Django
project to scan:

1. **Set `DJANGO_ORM_LENS_ROOT` in `env`** — the whole session uses one
   project. Simplest for single-repo workflows.
2. **Pass `workspace_root` on each tool call** — the agent switches
   projects per call. Useful for mono-repos and multi-workspace setups.

The tool signatures include `workspace_root: str = ""` as an optional
parameter, so any agent inspecting `tools/list` sees it and can supply it.

---

## Why?

Django's ORM is Python, and Python is dynamic. AI agents that only see
`models.py` as raw text miss:

* which fields belong to which model;
* the direction and cardinality of every relation;
* what `Meta.ordering`, `unique_together`, and `constraints` actually contain;
* which app owns which model when the project uses split `models/` packages.

`django-orm-lens` gives them a **static, deterministic, JSON view** of the
schema — no Django boot, no database, no side effects. And you get a nice CLI
for humans too.

---

## Programmatic API

```python
from django_orm_lens import scan_workspace

index = scan_workspace(".")
for app in index.apps:
    for model in app.models:
        print(f"{app.name}.{model.name} — {len(model.fields)} fields")

# The full parsed tree serialises to the same JSON schema the VS Code
# extension emits, so tools can share it interchangeably.
import json
json.dumps(index.to_dict(), indent=2)
```

---

## Links

* Repo: <https://github.com/FROWNINGdev/django-orm-lens>
* Issues: <https://github.com/FROWNINGdev/django-orm-lens/issues>
* Changelog: <https://github.com/FROWNINGdev/django-orm-lens/blob/main/CHANGELOG.md>
* VS Code extension: <https://marketplace.visualstudio.com/items?itemName=frowningdev.django-orm-lens>

MIT licensed.
