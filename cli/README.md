# orm-synapse

<!-- mcp-name: io.github.nam-tong/orm-synapse -->

[![PyPI](https://img.shields.io/pypi/v/orm-synapse?color=3775a9&label=PyPI&logo=pypi&logoColor=white)](https://pypi.org/project/orm-synapse/)
[![Python](https://img.shields.io/pypi/pyversions/orm-synapse?color=3775a9&logo=python&logoColor=white)](https://pypi.org/project/orm-synapse/)
[![Downloads](https://img.shields.io/pepy/dt/orm-synapse?color=3775a9&label=downloads&logo=pypi&logoColor=white)](https://pepy.tech/project/orm-synapse)
[![License](https://img.shields.io/github/license/nam-tong/orm-synapse?color=16a34a)](https://github.com/nam-tong/orm-synapse/blob/main/LICENSE)

**Static analysis + MCP server for Django models.** Terminal- and AI-agent-friendly.

Listed in the official [MCP Registry](https://registry.modelcontextprotocol.io/) as `io.github.nam-tong/orm-synapse`.

Ships with a zero-dependency parser, a JSON/Markdown/table CLI, and an optional
MCP (Model Context Protocol) server so any AI coding agent — Cursor, Aider,
Continue, and any other MCP client — can navigate your Django schema without
importing Django or spinning up your app.

Companion to the [ORM Synapse VS Code
extension](https://marketplace.visualstudio.com/items?itemName=frowningdev.orm-synapse).

## Paid-tier capabilities, free and MIT

Schema review is a paid category nearly everywhere. A bot that reviews every
pull request, analysis that follows a queryset past the function it was built in, a check that
catches schema drift, index advice grounded in real table statistics — those
normally sit behind a per-seat or per-database subscription.

All of it is here, MIT-licensed, with no tier gate, no seat count, no account
and no telemetry:

| Capability usually sold as a paid tier | Here |
|---|---|
| PR review bot for schema changes — posts once, then updates in place | `blast-radius` + the GitHub Action |
| Analysis that follows a queryset across functions | `nplusone` |
| Schema drift detection | `drift` |
| Index proposals from observed QuerySet usage | `suggest-indexes` |
| Migration risk weighed against real table sizes | `blast-radius --stats` |
| Blast radius of a destructive migration | `blast-radius` |
| Cross-layer impact of removing a field | `impact` |

**There is no Pro tier, and none is planned.**

---

## Install

```bash
# Core CLI (zero third-party deps)
pip install orm-synapse

# With the MCP server (adds the `mcp` package)
pip install "orm-synapse[mcp]"
```

Requires Python **3.9+**. Works on Linux, macOS, and Windows.

---

## CLI usage

```bash
# Scan a Django project for models (JSON, Markdown, or table)
orm-synapse scan -f json
orm-synapse scan -f markdown
orm-synapse scan -f table

# Describe one model
orm-synapse describe blog.Post
orm-synapse describe Post -f json

# Compact hover card (great for pipeing into your editor)
orm-synapse hover blog.Post

# Flat list — pipes into fzf, grep, etc.
orm-synapse list | fzf

# ER diagram — Mermaid (default), DBML, D2, or PlantUML
orm-synapse er > schema.mmd
orm-synapse er -f dbml > schema.dbml     # paste into dbdiagram.io
orm-synapse er -f d2 > schema.d2         # render: d2 schema.d2 schema.svg
orm-synapse er -f plantuml > schema.puml

# Diff two schema dumps (exit 1 on changes — CI-friendly)
orm-synapse diff before.json after.json

# Static analyzers — text, json, sarif, or github annotation output
orm-synapse nplusone --format github     # N+1 findings as PR annotations
orm-synapse migration-risk -f sarif      # SARIF for GitHub Code Scanning
orm-synapse suggest-indexes blog.Post    # Meta.indexes proposals from usage
orm-synapse signals                      # sender→signal→handler graph
orm-synapse migration-deps blog -f mermaid   # per-app migration DAG
orm-synapse cascade blog.Author          # delete blast radius by on_delete
```

Every command accepts `--path <dir>` and repeatable `--exclude <glob>`. Defaults
skip `migrations/`, `venv/`, `.venv/`, `env/`, and `node_modules/`.

---

## MCP server — for AI coding agents

The MCP server exposes ten read-only tools that any MCP-compatible agent can
call while it edits your Django project:

| Tool | Purpose |
| --- | --- |
| `list_apps` | Every Django app in the workspace with model counts |
| `list_models` | Flat `app.Model` list, optional app filter |
| `describe_model` | Full field / relation / Meta detail for one model |
| `find_relations` | Inbound + outbound relations for one model |
| `cascade_preview` | Blast radius of one `delete()`, grouped by `on_delete` |
| `er_diagram` | ER diagram — `mermaid` / `dbml` / `d2` / `plantuml` |
| `describe_migration_dependency` | Per-app migration DAG: roots, leaves, cross-app deps |
| `suggest_indexes` | `Meta.indexes` proposals from observed QuerySet usage |
| `signal_graph` | Sender→signal→handler graph from `@receiver` decorators |
| `nplusone_scan` | Static N+1 findings for the whole workspace |

### Start the server manually

```bash
orm-synapse-mcp     # dedicated entry point
# or
orm-synapse mcp     # subcommand
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
    "orm-synapse": {
      "command": "orm-synapse-mcp",
      "env": { "DJANGO_ORM_LENS_ROOT": "/abs/path/to/your/project" }
    }
  }
}
```

**Any MCP client** — same shape, generic tool. Point `command` at the
installed `orm-synapse-mcp` binary. Two ways to tell it which Django
project to scan:

1. **Set `DJANGO_ORM_LENS_ROOT` in `env`** — the whole session uses one
   project. Simplest for single-repo workflows.
2. **Pass `workspace_root` on each tool call** — the agent switches
   projects per call. Useful for mono-repos and multi-workspace setups.

The tool signatures include `workspace_root: str = ""` as an optional
parameter, so any agent inspecting `tools/list` sees it and can supply it.

---

## CI gates

`diff` and `nplusone` exit `1` on findings; `migration-risk` exits `1` on
critical findings (`--exit-zero` for report-only). Two annotation-ready
formats: `--format github` prints `::warning`/`::error` workflow commands
(PR annotations with no extra permissions), `--format sarif` emits
SARIF 2.1.0 for `github/codeql-action/upload-sarif`.

pre-commit users get two ready-made hooks:

```yaml
repos:
  - repo: https://github.com/nam-tong/orm-synapse
    rev: py-v1.13.3
    hooks:
      - id: orm-synapse-nplusone
      - id: orm-synapse-migration-risk
```

GitHub Actions users get a composite action:
`uses: nam-tong/orm-synapse@action-v1` with `command:` / `format:` inputs.

---

## Why?

Django's ORM is Python, and Python is dynamic. AI agents that only see
`models.py` as raw text miss:

* which fields belong to which model;
* the direction and cardinality of every relation;
* what `Meta.ordering`, `unique_together`, and `constraints` actually contain;
* which app owns which model when the project uses split `models/` packages.

`orm-synapse` gives them a **static, deterministic, JSON view** of the
schema — no Django boot, no database, no side effects. And you get a nice CLI
for humans too.

---

## Programmatic API

```python
from orm_synapse import scan_workspace

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

* Repo: <https://github.com/nam-tong/orm-synapse>
* Issues: <https://github.com/nam-tong/orm-synapse/issues>
* Changelog: <https://github.com/nam-tong/orm-synapse/blob/main/CHANGELOG.md>
* VS Code extension: <https://marketplace.visualstudio.com/items?itemName=frowningdev.orm-synapse>

MIT licensed.
