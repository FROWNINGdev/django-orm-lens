# Tools and commands

Every MCP tool takes an optional `workspace_root` (absolute path of the
directory with `manage.py`); without it the server uses `DJANGO_ORM_LENS_ROOT`
or its working directory. Every CLI command takes `--path` (default: current
directory) and `--exclude` (glob, repeatable). Tools return JSON; on a wrong
root they return an envelope such as
`{"error": "WORKSPACE_NOT_DJANGO", "hint": "..."}` — fix the path and retry
rather than reporting "no models".

Contents: 1. MCP tools · 2. CLI commands · 3. Installing the MCP server ·
4. CI usage

## 1. MCP tools

| Tool | Arguments | Returns |
|---|---|---|
| `list_apps` | — | apps with model counts |
| `list_models` | `app` (optional) | flat `app.Model` list |
| `describe_model` | `model` (`app.Model` or `Model`) | fields, relations, Meta, bases, file path and line |
| `find_relations` | `model` | outbound and inbound relations; inbound carry `on_delete` |
| `cascade_preview` | `app_label`, `model_name` | `cascade_kills`, `set_null`, `protected` — one level |
| `er_diagram` | `diagram_format`: `mermaid` (default), `dbml`, `d2`, `plantuml`, `dot` | diagram source |
| `describe_migration_dependency` | `app_label` | migration DAG: dependencies, roots, leaves, cross-app deps |
| `suggest_indexes` | `app_label`, `model_name` | field-usage frequency from filter/exclude/get/order_by, proposed `Meta.indexes` |
| `signal_graph` | — | sender → signal → handler graph, send-sites, orphan handlers |
| `nplusone_scan` | — | N+1 findings: `file`, `line`, `loop_var`, `queryset_var`, `accessed`, `suggested_fix`, `confidence` |
| `blast_radius` | `severity`: `critical` (default), `warning`, `info`, `all` | per destructive operation: risks, references by layer with certainty, cascade |
| `drift` | — | per model: fields declared but never migrated, fields migrated but no longer declared, `blocking` flag |
| `impact` | `name` (field or model name) | references grouped by layer, each `certain` / `likely` / `possibly` |

Pass `severity: "all"` to `blast_radius` during reviews — the default shows
only critical risks.

## 2. CLI commands

Run as `django-orm-lens <command>` (or `uvx django-orm-lens <command>`).

| Command | Key options | Exit code |
|---|---|---|
| `list` | `--format text\|json` | 0 |
| `scan` | `--format json\|markdown\|table` | 0 |
| `describe <app.Model>` | | 0 |
| `er` | `--format mermaid\|dbml\|d2\|plantuml\|dot`, `--output FILE` | 0 |
| `nplusone` | `--format text\|json\|sarif\|github`, `--confidence high\|medium\|all`, `--exit-zero` | 1 on findings |
| `migration-risk` | `--format text\|json\|sarif\|github`, `--severity critical\|warning\|info\|all`, `--exit-zero` | 1 on critical |
| `blast-radius` | `--format text\|json\|markdown\|github`, `--severity …`, `--only FILE` (repeat), `--no-cascade`, `--stats FILE`, `--exit-zero` | 1 on critical |
| `drift` | `--format text\|json`, `--exit-zero` | 1 on blocking drift |
| `impact <name>` | `--confidence certain\|likely\|possibly\|all`, `--format text\|json` | 0 |
| `cascade <app.Model>` | `--format text\|json` | 0 |
| `suggest-indexes <app.Model>` | `--format text\|json` | 0 |
| `signals` | | 0 |
| `migration-deps` | `--format text\|json\|mermaid` | 0 |
| `diff OLD.json NEW.json` | compares two `list/scan --format json` dumps | 1 on changes |
| `stats-sql` | prints read-only SQL that produces a `--stats` file | 0 |
| `mcp` | runs the MCP stdio server | — |

`--only` takes absolute paths or paths relative to the current directory.
`--stats` takes production table sizes (from `stats-sql`) so blast-radius can
say "this table has 40M rows" instead of "probably large".

## 3. Installing the MCP server

The server ships as an extra: `django-orm-lens[mcp]`. With `uv` installed no
global install is needed.

**Claude Code**

```bash
claude mcp add django-orm-lens -- uvx --from "django-orm-lens[mcp]" django-orm-lens-mcp
```

**Cursor** (`~/.cursor/mcp.json`), **Claude Desktop**
(`claude_desktop_config.json`), **Windsurf**, **Gemini CLI**
(`~/.gemini/settings.json`) — same shape:

```json
{
  "mcpServers": {
    "django-orm-lens": {
      "command": "uvx",
      "args": ["--from", "django-orm-lens[mcp]", "django-orm-lens-mcp"],
      "env": { "DJANGO_ORM_LENS_ROOT": "/abs/path/to/project" }
    }
  }
}
```

**VS Code / GitHub Copilot** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "django-orm-lens": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "django-orm-lens[mcp]", "django-orm-lens-mcp"]
    }
  }
}
```

**Codex CLI** (`~/.codex/config.toml`):

```toml
[mcp_servers.django-orm-lens]
command = "uvx"
args = ["--from", "django-orm-lens[mcp]", "django-orm-lens-mcp"]
```

Without `uv`: `pip install "django-orm-lens[mcp]"` and use
`"command": "django-orm-lens-mcp"` with no args. `DJANGO_ORM_LENS_ROOT` is
optional when the agent passes `workspace_root` on each call (useful for
monorepos). `DJANGO_ORM_LENS_ALLOWED_ROOTS` restricts which paths the server
may read.

## 4. CI usage

```yaml
# .github/workflows/django-lens.yml
- run: pip install django-orm-lens
- run: django-orm-lens migration-risk --format github     # PR annotations
- run: django-orm-lens drift
- run: django-orm-lens nplusone --format sarif > nplusone.sarif
```

There is also a composite GitHub Action and pre-commit hooks — see the
project README: https://github.com/FROWNINGdev/django-orm-lens
