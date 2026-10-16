---
name: django-orm-lens
description: >-
  Static analysis for Django codebases: real answers about models, relations,
  N+1 queries, migration safety, schema drift and "what breaks if I remove
  this field", computed from the AST — no database, no settings module, no
  django.setup(). Use this skill whenever the user works in a Django project
  and asks about models or the schema, reviews a PR that touches models.py or
  migrations, wants to rename/remove/alter a field or model, asks whether a
  migration is safe to deploy, complains about slow views or too many
  queries, wants an ER diagram, debugs signals or migration conflicts, or
  asks what deleting a row will cascade to — even if they never say
  "static analysis" or name this tool.
license: MIT
compatibility: >-
  Python 3.9+. Works through the django-orm-lens MCP server when it is
  connected, otherwise through the django-orm-lens CLI (uvx, pipx or pip).
  Read-only: never imports the project, never touches a database.
metadata:
  author: FROWNINGdev
  version: 1.0.0
  homepage: https://github.com/FROWNINGdev/django-orm-lens
---

# Django ORM Lens

Guessing about a Django schema is how agents ship broken migrations. Reading
`models.py` by eye misses abstract bases in other files, reverse accessors,
`related_name`s, cross-app foreign keys and the migration history; grepping
for a field name drowns in false matches. `django-orm-lens` parses the whole
project with Python's AST and answers from facts: which models exist, what
points at what, which loops issue N+1 queries, which migration operations
lock tables or drop data, and which lines of code still read a column you are
about to remove.

It never runs project code, needs no `DJANGO_SETTINGS_MODULE`, no installed
dependencies and no database, so it is safe on any checkout — including a
fresh clone, a PR branch, or a repo whose settings need secrets.

## Step 0 — get the engine

Check whether MCP tools named `list_apps`, `describe_model`, `blast_radius`,
`nplusone_scan` (etc.) are available to you. If they are, use them and pass
`workspace_root` = the absolute path of the directory that holds `manage.py`.

If they are not, use the CLI. Pick the first that works:

```bash
uvx django-orm-lens@latest --version   # zero-install, preferred
pipx run django-orm-lens --version
pip install django-orm-lens && django-orm-lens --version
```

Every CLI command takes `--path <project root>` and most take `--format json`.
Text output is for reading; JSON is for counting. In `impact` JSON the
`line` field is already 1-based — cite `file:line` directly (it used to be
0-based, which made JSON and text disagree). `uvx` may reuse a cached older
release; use `uvx django-orm-lens@latest` when a flag seems to be missing.
When the user wants the MCP server permanently, give them the line for their
agent (details in `references/tools.md` → "Installing the MCP server"):

```bash
claude mcp add django-orm-lens -- uvx --from "django-orm-lens[mcp]" django-orm-lens-mcp
```

## Pick the playbook

Match each part of the user's request to a playbook — one request often
needs two ("is this PR safe, and why is the page slow?" is B then D). Run
deploy-safety playbooks (B, C, E) before performance (D): a blocker changes
what is worth optimizing. Run the tools before forming an opinion — the
value of this skill is that your answer rests on the scan, not on a skim of
a few files.

| The user wants to… | Playbook |
|---|---|
| understand the schema / a model / "how is X related to Y" | A. Map the schema |
| review a PR or decide if a migration is safe to deploy | B. Migration review |
| rename, remove or retype a field or model | C. Safe schema change |
| fix slow pages, "too many queries", N+1 | D. Query performance |
| delete data, or know what a delete takes with it | E. Cascade check |
| untangle signals or migration conflicts | F. Wiring and history |

### A. Map the schema

1. `list_apps` (CLI: `list --format json`) for the app and model inventory.
2. `describe_model` for each model in question — fields, Meta, bases, file.
3. `find_relations` for inbound and outbound links, including `on_delete`.
4. If a picture helps, `er_diagram` (CLI: `er`). Mermaid renders on GitHub
   and in most chat UIs; offer `dbml` for dbdiagram.io, or `d2`, `plantuml`,
   `dot`. For a large project, draw only the models the user asked about plus
   their direct neighbours — a 120-box diagram helps nobody.

Answer with file paths (`app/models.py:42`) so the user can jump to source.

### B. Migration review (PR or pre-deploy)

Run all three; each sees something the others do not.

1. `blast_radius` with `severity: "all"` (CLI: `blast-radius --severity all`;
   for a PR, repeat `--only <file>` per changed migration, using absolute
   paths or paths relative to the current directory). For every destructive
   operation it lists the risk rule, the mitigation, and the code that still
   references the thing being changed, grouped by Django layer.
2. `drift` — replays migrations and diffs them against `models.py`. A field
   "declared but never migrated" means the column will not exist at runtime:
   that is a blocker even when every migration looks safe.
3. CLI `migration-risk --severity all` if you also want rules that have no
   reference scan (e.g. `add_index_locks_table`, `runpython_no_reverse`).
   `blast_radius` already includes them under "other migration risks".
4. For every `RenameField` / `RenameModel`, run `impact` on the **old** name
   too. `blast_radius` looks up references to the new name, so it shows
   lookalikes (`name` on another model) and misses the code that still says
   `title` — the code that actually breaks.
5. Check indexes by hand: `drift` compares fields, not `Meta.indexes`. An
   `AddIndex` whose index is missing from the model's `Meta.indexes` will be
   undone by the next `makemigrations` as a `RemoveIndex`.
6. For a PR, separate what the PR introduces from what was already broken:
   run `drift` on the base branch too (`git worktree add` or `git archive`)
   and label pre-existing findings as such.

Then give a verdict, worst first:

- **BLOCK** — any `critical` risk (e.g. `add_field_not_null_no_default`,
  `remove_field_still_referenced`, `delete_model_still_referenced`) or any
  blocking drift.
- **FIX BEFORE DEPLOY** — `warning` risks on large or hot tables (table
  locks, rolling-deploy renames, int/char narrowing).
- **SHIP** — only `info` findings, each acknowledged.

For each finding, give the safe rewrite, not just the problem. The standard
patterns (expand/contract, `AddIndexConcurrently`, three-step NOT NULL,
rename via add-copy-drop) are in `references/migration-playbook.md` — read it
when you need to write the fixed migration.

### C. Safe schema change (rename / remove / retype)

Do this before editing anything, so the plan is grounded:

1. `impact` with `name` = the field or model name. It returns every
   reference grouped by layer (models, serializers, forms, admin, views,
   urls, templates, tests, migrations), each tagged `certain` / `likely` /
   `possibly`.
2. For a model removal, also `cascade_preview` on it (Playbook E).
3. Write the change as a deploy sequence, not one migration: update code
   paths first, then the destructive migration in a later release. Name the
   files and lines from step 1 that must change in each step.
4. After `makemigrations`, run Playbook B on the new migration.

Treat `certain` hits as must-fix. Open every `likely` and `possibly` hit
before acting on it: the reference scan matches by name, so `name` on a
different model, or a template variable with the same spelling, shows up
too. Say which ones you dismissed and why.

### D. Query performance (N+1)

1. `nplusone_scan` (CLI: `nplusone --format json`). Each finding has
   `file`, `line`, the loop variable, the relations accessed, a
   `suggested_fix` and a `confidence`.
2. Open each finding and apply the fix at the queryset that feeds the loop:
   `select_related` for FK/O2O, `prefetch_related` for reverse FK and M2M.
   Fix the whole chain at once. When the page only renders child rows,
   query the child model flat — `OrderItem.objects.filter(order__customer=u)
   .select_related("product__category")` is one query instead of
   1 + N + 2N. Otherwise prefetch the chain:
   `.prefetch_related("items__product__category")`.
3. Re-run the scan and report before/after counts. A finding is resolved
   when it is gone, or when you can point to the prefetch that covers it:
   after an outer `prefetch_related("items__...")` the scan may still flag
   the inner `for item in order.items.all()` loop, because it does not link
   the inner queryset to the outer prefetch. Say so explicitly rather than
   leaving it unexplained or "fixing" it twice.
4. Then read the loop bodies the scan flagged for one level deeper than it
   reported, and other loops over sliced querysets (`qs[:50]`) or querysets
   built in another function: static detection cannot see every case, so a
   short manual pass catches what it misses. Report those as "found by
   review", separately from tool findings.
5. For hot filters, `suggest_indexes` on the model (CLI:
   `suggest-indexes app.Model`) proposes `Meta.indexes` from the
   `filter/exclude/get/order_by` calls it finds. It needs several usage
   sites before it proposes anything, so for a single hot view reason about
   the index yourself (filter columns first, then the `ORDER BY` column) and
   label it "found by review". An index proposal always comes with the
   migration-safety note from Playbook B (`AddIndexConcurrently` on Postgres).

### E. Cascade check

`cascade_preview` on the model lists what one deleted row takes with it:
`cascade_kills`, `set_null`, `protected`. It reports one level. Repeat it for
every model in `cascade_kills` until nothing new appears, and present the
whole tree — deleting a `Category` that cascades to `Product` that cascades
to `OrderItem` erases order history, and that is the sentence the user needs
to see. Also check `find_relations` for self-referential foreign keys
(`parent = ForeignKey("self", on_delete=CASCADE)`): they delete whole
subtrees and are easy to miss.

### F. Wiring and history

- `signal_graph` — sender → signal → handler graph, custom signal send-sites,
  orphan handlers. Use it when a save "does something mysterious".
- `describe_migration_dependency` — per-app migration DAG with roots, leaves
  and cross-app dependencies. Two leaves in one app is a conflict
  (`conflicting_migration_leaves`); propose `makemigrations --merge` or a
  rebase of the newer migration's `dependencies`.

## Full audit in one command

For "audit this project", or as the first step of a PR review, run the
bundled script. It calls the CLI, merges `nplusone`, `migration-risk`,
`drift` and `blast-radius` into one JSON document with a verdict, and needs
only Python. Treat it as the overview: it tells you where to look, and the
playbooks above are how you then dig into each finding (the old-name
`impact` for renames, the index check, the base-branch comparison and the
manual N+1 pass are not in the script).

```bash
python scripts/audit.py --path /abs/project/root            # whole project
python scripts/audit.py --path . --changed-since origin/main  # PR scope
```

Lead your report with the `summary` block, then go finding by finding.

## How to report

Keep the report scannable and anchored in source:

```markdown
## Verdict: BLOCK | FIX BEFORE DEPLOY | SHIP
One sentence on why.

| Severity | Where | What | Fix |
|---|---|---|---|
| critical | catalog/migrations/0002_x.py:7 | NOT NULL column without default | add null=True → backfill → set NOT NULL |

## Still referenced
Layer-grouped list from impact / blast_radius, with dismissed matches noted.

## Next steps
Numbered, in deploy order.
```

## Being honest about static analysis

The scan is deterministic and fast, which makes it a great floor and a poor
ceiling. Say what you checked ("3 migrations replayed, 2 apps, 41 files")
instead of "no issues", and name what you could not check — templates that
are not in the repo, a production schema that may differ from the
migrations. Code that builds lookups dynamically (`getattr`,
`**{field: value}`), raw SQL strings and querysets assembled across many
functions can hide references and N+1 loops; when the stakes are high
(dropping a column in production), recommend one confirming step the scan
cannot do: `python manage.py makemigrations --check --dry-run`, a test run,
or `assertNumQueries` around the view.

## Reference files

- `references/tools.md` — every MCP tool and CLI command, arguments, output
  fields, MCP install lines for Claude Code, Cursor, VS Code and others.
- `references/migration-playbook.md` — all 16 migration risk rules with the
  safe rewrite for each, plus deploy-order patterns.
- `scripts/audit.py` — one-shot audit that merges the four analyzers.
