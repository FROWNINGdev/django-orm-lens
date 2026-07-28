# Blast radius

`django-orm-lens blast-radius --path .` answers the question a schema change actually raises in review: **what does this hit?**

Three analyzers in this package each answer a third of it, and running them separately leaves the reviewer to join the results by hand — which in practice nobody does:

| Analyzer | Answers |
|---|---|
| [`migration-risk`](migrations.md) | Is this migration dangerous on its own? |
| `impact` | What code still reads the thing it touches? |
| `cascade` | What does deleting a row take down? |

`blast-radius` runs all three and joins them. Static AST + text analysis — no database, no Django boot, no `git` required, so it works on a cold clone and on a shallow CI checkout.

## What becomes a target

Every **destructive** migration operation becomes a *target* — one thing the migration changes, carrying everything known about it:

`RemoveField` · `DeleteModel` · `RenameField` · `RenameModel` · `AlterField`

`AddField` is deliberately excluded. Adding a column cannot orphan a reader, so it is reported in the "other migration risks" bucket without a reference scan. Its own risks (NOT NULL without a default, UNIQUE on a populated table) still come from `migration-risk` unchanged.

Field-level operations key on the field, so two `RemoveField`s on one model stay separate targets. Model-level operations (`DeleteModel`, `RenameModel`) key on the model and additionally get a cascade preview.

Targets are ordered by worst severity, then by how many `certain` references remain, then by name — so the thing most likely to break production is the first thing in the output.

## Confidence, and why `possibly` exists

Reference findings carry `certain` / `likely` / `possibly`, from the same classifier the VS Code extension uses:

- **certain** — an unambiguous ORM reference: `filter(author__id=1)`, `order_by("-author")`, `fields = ["author"]`, `list_display`, `search_fields`.
- **likely** — attribute access inside a recognised Django layer, or a template variable `{{ post.author }}`.
- **possibly** — a bare identifier match, or attribute access in a file whose layer could not be determined.

There is no type inference here. That is Pyright's job, and Pyright already loses on Django's string-typed `ForeignKey` / `related_name` / template surface. A visible `possibly` tier is the honest alternative to silently dropping those lines.

The definition site itself is not counted — a field does not report its own declaration as impact.

## Usage

```bash
django-orm-lens blast-radius --path .                     # critical risks only
django-orm-lens blast-radius --severity all               # everything
django-orm-lens blast-radius --format markdown            # PR-comment body
django-orm-lens blast-radius --format github              # PR annotations
django-orm-lens blast-radius --format json                # machine-readable
django-orm-lens blast-radius --no-cascade                 # skip the extra parse
django-orm-lens blast-radius --only blog/migrations/0002_drop_author.py
```

- **`--severity critical|warning|info|all`** (default `critical`) — minimum risk severity, matching `migration-risk`.
- **`--only MIGRATION`** — restrict to these migration files; repeat the flag per file. Pass a PR's changed paths to scope the report to the diff. Default scans every migration in the workspace.
- **`--no-cascade`** — skip the cascade preview and the workspace parse it needs. Cascade only ever applies to model-level operations.
- **Exit code** — `1` when critical risks remain, `0` otherwise. `--exit-zero` always exits `0`, useful while burning down existing debt.

## In CI

As a GitHub Action, findings become PR annotations with no extra permissions:

```yaml
- uses: FROWNINGdev/django-orm-lens@action-v1
  with:
    command: blast-radius
    format: github
```

Annotations point at the **migration line** — the line a reviewer can act on — and name the reference count in the title, so the consequence is visible without opening a second tab:

```
::error file=blog/migrations/0002_drop_author.py,line=7,title=django-orm-lens: remove_field_still_referenced (2 certain reference(s))::…
```

### As a PR comment

`comment: true` posts the markdown report and **updates that same comment** on every later push, so a twenty-push PR carries one report rather than twenty. `only-changed: true` narrows the report to the migrations this PR actually touches, and exits early when it touches none.

```yaml
name: Schema review
on: pull_request

permissions:
  contents: read
  pull-requests: write        # only needed for `comment: true`

jobs:
  blast-radius:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: FROWNINGdev/django-orm-lens@action-v1
        with:
          command: blast-radius
          only-changed: true
          comment: true
          github-token: ${{ github.token }}
```

Notes on behaviour, so nothing surprises you in a live run:

- The comment is posted **before** the job fails, so a blocked PR still carries the explanation of why. The exit code is preserved — critical risks still fail the check.
- The changed-file list comes from the API, not `git diff`: `actions/checkout` defaults to `fetch-depth: 1`, so the base commit is not in the local history and a diff would be wrong or empty.
- On a `push` event both flags are skipped with a notice rather than failing — the same workflow can run on pushes without special-casing.
- Updating works by matching the marker `<!-- django-orm-lens: blast-radius -->`, which the markdown renderer always emits as its first line.
- `github-token: ${{ github.token }}` is enough; no PAT, no app.

## Production statistics (optional)

Everything above is static, which leaves one honest gap: source code cannot tell a table with forty million rows from an empty one. `migration-risk` papers over it with a heuristic — *anything after `0001_` is assumed populated* — right often enough to be useful, wrong often enough to be annoying.

`--stats` closes the gap, and **django-orm-lens still never connects to a database**. You run one read-only query yourself and hand over the result:

```bash
django-orm-lens stats-sql > stats.sql
psql -At -d "$DATABASE_URL" -f stats.sql > stats.json     # a replica is fine
django-orm-lens blast-radius --path . --stats stats.json
```

The report then carries the real size:

```
!! blog.post.author  [RemoveField]
     critical: remove_field_still_referenced (high)  blog/migrations/0002_drop_author.py:7
     blog_post: ~41 000 000 rows, 12.0 GB, 4 index(es) (estimated)
```

Why a file rather than a connection string:

- No credential ever enters CI config, so there is nothing to leak.
- The query is a single read of `pg_stat_user_tables` plus `pg_total_relation_size`. It takes no locks and reads no user data — only table names and counts.
- `stats.json` can be committed, reviewed and diffed like any other input.

**These are estimates, and the tool always says so.** `n_live_tup` is maintained by the stats collector and refreshed by `VACUUM` / `ANALYZE`; autovacuum triggers `ANALYZE` once roughly 20% of a table's rows have changed, so a busy table drifts between runs. Right after `ANALYZE` it is typically within a couple of percent. That is ample for the decision this informs: telling forty million rows from four hundred.

A table missing from `stats.json` is reported as **unknown**, never as zero — a model production has never seen must not read as "safe to drop". `Meta.db_table` is honoured when resolving a model to its table; otherwise Django's `<app>_<model>` default applies.

## Example

```
!! blog.post.author  [RemoveField]
     critical: remove_field_still_referenced (high)  blog/migrations/0002_drop_author.py:7
       Removes field 'author' from 'post' but a field with the same name still exists in the current models.py.
       fix: Confirm no code path still reads/writes the field. Deploy the code change first, then run this migration.
     still referenced in 5 place(s): 2 certain, 1 likely, 2 possibly
       serializers/certain  blog/serializers.py:3  fields = ["title", "author"]
       views/certain  blog/views.py:5  return Post.objects.filter(author__id=request.user.id)
       templates/likely  blog/templates/blog/post.html:1  <p>{{ post.author }}</p>

summary: 1 target(s), 1 critical risk(s), 2 certain reference(s)
```

## JSON shape

```jsonc
{
  "targets": [
    {
      "target": "blog.post.author",
      "app": "blog", "model": "post", "field": "author",
      "operations": ["RemoveField"],
      "worstSeverity": "critical",
      "risks": [ /* MigrationRisk objects, as in `migration-risk --format json` */ ],
      "impact": {
        "counts": { "certain": 2, "likely": 1, "possibly": 2 },
        "byLayer": { "views": [ /* findings */ ] }
      },
      "cascade": null
    }
  ],
  "unscannedRisks": [ /* risks on non-destructive operations */ ],
  "summary": { "targets": 1, "criticalRisks": 1, "certainReferences": 2 }
}
```

Impact findings use **zero-based** `line` and `column`, matching the VS Code extension and the LSP. The text and markdown renderers add one before printing, because humans and editors are one-based.

## Related

- [`migration-risk`](migrations.md) — the 16 rules behind the risk half
- [`nplusone`](nplusone.md) — the other CI analyzer
- `impact <name>` — the reference scan on its own, for when you are not looking at a migration
