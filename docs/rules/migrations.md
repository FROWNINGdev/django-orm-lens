# Migration risk rules

`django-orm-lens migration-risk --path .` statically analyzes every `<app>/migrations/*.py` in the workspace via `ast.parse` — no Django boot, no database connection, no execution of the migration. It implements **16 rules** over the `operations = [...]` list of each `Migration` class. Every finding carries a severity (`critical` | `warning` | `info`) and a confidence (`high` | `medium` | `low`), plus the description and mitigation shown below.

Usage and CI semantics:

- **Exit code:** `1` only when `critical` findings remain after filtering; `0` otherwise. `--exit-zero` always exits `0` — useful while burning down existing debt.
- **`--severity critical|warning|info|all`** (default `critical`) — report findings at or above the given severity. The default surfaces only migration-breaking issues; use `--severity all` for the full review list.
- **`--format text|json|sarif|github`** — `sarif` emits SARIF 2.1.0 for upload to GitHub Code Scanning; `github` emits `::error`/`::warning` workflow commands for zero-setup PR annotations. `json` is the machine-readable finding list; `text` is the human default.

Populated-table heuristic: any migration after the app's first (`0001_*`) is assumed to run against a table that already contains rows. Rules marked *populated tables only* stay silent in an app's initial migration. Rules that cross-reference the current `models.py` degrade to a low-confidence `*_unverified` variant when the workspace schema cannot be parsed.

## add_field_not_null_no_default

**Operation:** `AddField` · **Severity:** critical · **Confidence:** high · *populated tables only*

Adds a NOT NULL column (no `null=True`) without a `default` to a model whose table likely has rows; existing rows will raise `IntegrityError` when the migration applies. Auto-created PK fields (`AutoField` / `BigAutoField` / `SmallAutoField`) are exempt.

**Mitigation:** Add `null=True` first, backfill via `RunPython`, then a third migration to set `null=False`. Or provide `default=`.

## add_field_unique_no_row_default

**Operation:** `AddField` · **Severity:** critical (high confidence) — downgraded to warning (medium confidence) when the default is a callable · *populated tables only*

Adds a UNIQUE column to a populated table. Without a per-row default, every existing row gets the same value and the constraint fails on the first duplicate. A callable default (e.g. `default=uuid.uuid4`) *can* produce unique per-row values, so that case is flagged for verification rather than as a blocker.

**Mitigation:** Add the column nullable first, populate unique values via data migration, then apply the unique constraint.

## remove_field_still_referenced

**Operation:** `RemoveField` · **Severity:** critical · **Confidence:** high

Removes a field while a field with the same name still exists in the current `models.py` — running code will keep reading/writing a column the migration drops.

**Mitigation:** Confirm no code path still reads/writes the field. Deploy the code change first, then run this migration.

## remove_field_unverified

**Operation:** `RemoveField` · **Severity:** info · **Confidence:** low

Removes a field, but the analyzer could not cross-reference the current `models.py` (schema parse unavailable). Flagged so reviewers see dropped columns at a glance.

**Mitigation:** Manually confirm no code paths still access the removed field.

## delete_model_still_referenced

**Operation:** `DeleteModel` · **Severity:** critical · **Confidence:** high

Deletes a model whose class is still defined in `models.py` — the running application will keep querying a table the migration drops.

**Mitigation:** Remove the model class from `models.py` in a prior deploy, or drop this operation.

## delete_model_unverified

**Operation:** `DeleteModel` · **Severity:** info · **Confidence:** low

Deletes a model, but the analyzer could not cross-reference the current `models.py`.

**Mitigation:** Manually confirm no code paths still import or query the model.

## rename_field_rolling_deploy

**Operation:** `RenameField` · **Severity:** warning · **Confidence:** medium

Renames a column. During a rolling deploy, app instances still running the old code query the old column name and fail until every instance has restarted.

**Mitigation:** Use a 3-step migration: add the new column, dual-write and backfill, then drop the old column after all instances have restarted.

## rename_model_rolling_deploy

**Operation:** `RenameModel` · **Severity:** warning · **Confidence:** medium

Renames a model (and therefore its table). Old app instances during a rolling deploy query the old table and fail.

**Mitigation:** Use `db_table` on the new model to keep the same table name, or stage the rename via new model + data copy + old model drop.

## add_index_locks_table

**Operation:** `AddIndex` · **Severity:** warning · **Confidence:** medium · *populated tables only*

A plain `AddIndex` takes an ACCESS EXCLUSIVE lock on Postgres for the duration of the index build, blocking writes to the table. (`AddIndexConcurrently` and `RemoveIndex` are recognized as the safe variants and never flagged.)

**Mitigation:** Use `AddIndexConcurrently` (Django 3.0+) inside a non-atomic migration, or wrap `CREATE INDEX CONCURRENTLY` in `RunSQL` with `SET LOCAL lock_timeout` to bail early.

## alter_field_char_length

**Operation:** `AlterField` · **Severity:** warning · **Confidence:** medium

Alters a column to `CharField(max_length=N)`. If this narrows the column, rows longer than N characters make the migration fail; either way Postgres may rewrite the table under an ACCESS EXCLUSIVE lock.

**Mitigation:** Verify no existing row exceeds the new length. Use `ALTER TABLE ... ALTER COLUMN ... TYPE` with `USING` and run out of hours if the table is large.

## alter_field_int_type

**Operation:** `AlterField` · **Severity:** warning · **Confidence:** medium

Alters a column across integer field types (`SmallIntegerField` / `IntegerField` / `BigIntegerField` and their `Positive*` variants). On Postgres < 12 a column type change rewrites the whole table under an ACCESS EXCLUSIVE lock.

**Mitigation:** On PG12+ widening is metadata-only; narrowing still rewrites. Stage via new column + backfill + swap for large tables.

## runsql_no_reverse

**Operation:** `RunSQL` · **Severity:** warning · **Confidence:** medium

`RunSQL` without `reverse_sql` cannot be rolled back; migrating backwards past it fails — usually mid-incident, exactly when rollback matters.

**Mitigation:** Pass `reverse_sql=...` (or `migrations.RunSQL.noop` if the operation is genuinely irreversible) so the migration is reversible in CI/rollback.

## runpython_no_reverse

**Operation:** `RunPython` · **Severity:** warning · **Confidence:** medium

`RunPython` without `reverse_code` cannot be rolled back; migrating backwards past this data migration will fail.

**Mitigation:** Pass `reverse_code=migrations.RunPython.noop` when the forward step is safe to leave in place, or a real inverse function when it is not.

## alter_unique_together_lock

**Operation:** `AlterUniqueTogether` · **Severity:** warning · **Confidence:** medium · *populated tables only*

Adds/changes `unique_together` on a populated table: Postgres builds and validates a unique index under an ACCESS EXCLUSIVE lock, and any existing duplicate rows make the migration fail mid-deploy. Removing the constraint (`unique_together=set()` or `[]`) is safe and not flagged.

**Mitigation:** Deduplicate rows first, then prefer `AddConstraint(UniqueConstraint)` — on Postgres create the unique index CONCURRENTLY (`RunSQL` + `SeparateDatabaseAndState`) for large tables. `unique_together` is soft-deprecated in favour of `UniqueConstraint`.

## alter_index_together_deprecated

**Operation:** `AlterIndexTogether` · **Severity:** info · **Confidence:** high

Uses `index_together`, deprecated since Django 4.2 and removed in 5.1 — this migration will not run on modern Django at all.

**Mitigation:** Squash or rewrite the operation as `Meta.indexes` with `AddIndex` / `RenameIndex` (see the Django 4.2 release notes migration path).

## conflicting_migration_leaves

**Operation:** `(migration graph)` · **Severity:** critical · **Confidence:** high

The app's migration graph has more than one leaf — two or more migrations that nothing else in the app depends on. This is what happens when two branches each add a migration on the same parent and both get merged. Django refuses to run the app at all: *"Conflicting migrations detected; multiple leaf nodes in the migration graph."*

Unlike every other rule here, this one is a property of the whole graph rather than of a single operation, so it is reported once per conflicting leaf — each finding names the migrations it collides with, and every offending file gets annotated in a pull request.

The check reads the `dependencies` tuples only, so it fires on a fresh clone and in CI, before anything has a settings module or a database. `makemigrations --merge` cannot tell you this until you already have both.

**Mitigation:** Run `python manage.py makemigrations --merge` to generate a merge migration depending on every leaf. If the branches touched the same table, review the merged result by hand before applying it.

**Note on app labels:** `dependencies` carries the Django app *label*, which `AppConfig.label` may set to something other than the package directory name. The rule recovers the real label from the dependencies themselves and stays silent when that is ambiguous — a false "your migrations conflict" would be worse than a missed one.
