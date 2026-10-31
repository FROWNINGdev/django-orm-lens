# Alembic migration risk rules (preview)

`django-orm-lens migration-risk --path .` also reads every Alembic revision in the workspace: any `.py` under a `versions/` directory that declares `revision = "..."` and an `upgrade()` function. That covers `alembic/versions/`, Flask-Migrate's `migrations/versions/` and nested layouts such as `versions/postgresql/`. Like the Django rules, it is static: revisions are parsed with `ast`, never imported or run, and no database is touched. Projects that use SQLAlchemy without Django (FastAPI, Flask, Litestar) get the same checks and the same output formats.

Usage and CI semantics are those of the [Django migration rules](migrations.md): exit code `1` on `critical` findings, `--severity critical|warning|info|all` (default `critical`), `--format text|json|sarif|github`. Findings carry `app = "alembic"`, the table in `model` and the column in `field`.

Where engines differ, the rules describe PostgreSQL.

Populated-table heuristic, tuned against ~1170 real revisions (Superset, Airflow, Prefect, Polar, Dispatch, Mealie, the FastAPI full-stack template):

- A table created by `op.create_table` earlier in the same revision is empty.
- The base revision (`down_revision = None`) runs on an empty database.
- Operations inside `with op.batch_alter_table("t") as batch_op:` apply to `t`. On PostgreSQL, batch mode issues ordinary `ALTER TABLE` statements.
- A data operation earlier in the revision can empty or backfill the table: `op.execute` with `DELETE`, `UPDATE`, `INSERT` or `TRUNCATE`, `op.bulk_insert`, or SQL run on a connection from `op.get_bind()`. A NOT NULL column added after one is reported as a warning, not a certain critical.

## alembic_add_column_not_null_no_server_default

**Operation:** `add_column` · **Severity:** critical · **Confidence:** high · *populated tables only*

Adds a `nullable=False` column without `server_default`. Existing rows get NULL, so the `ALTER TABLE` fails. A SQLAlchemy `default=` does not help: it is applied by the ORM on INSERT only, and Alembic does not render it into the DDL. Generated (`Computed`) and `Identity` columns are filled by the database and are exempt.

```python
op.add_column("alerts", sa.Column("database_id", sa.Integer(), default=0, nullable=False))  # fails on a populated table
```

**Mitigation:** Add the column nullable, backfill it, then `alter_column(..., nullable=False)` in a later revision. Or give it a `server_default`.

## alembic_create_index_locks_table

**Operation:** `create_index` · **Severity:** warning · **Confidence:** medium · *populated tables only*

`CREATE INDEX` without `CONCURRENTLY` blocks writes to the table for the whole build.

**Mitigation:**

```python
with op.get_context().autocommit_block():
    op.create_index("ix_orders_status", "orders", ["status"], postgresql_concurrently=True)
```

## alembic_set_not_null_scans_table

**Operation:** `alter_column(nullable=False)` · **Severity:** warning · **Confidence:** medium · *populated tables only*

PostgreSQL scans the whole table under an exclusive lock to verify there are no NULLs, and the `ALTER` fails if any row still has one.

**Mitigation:** Backfill first. On large tables add `CHECK (col IS NOT NULL) NOT VALID`, `VALIDATE` it, then set NOT NULL.

## alembic_alter_column_type_rewrites

**Operation:** `alter_column(type_=...)` · **Severity:** warning · **Confidence:** medium · *populated tables only*

Most type changes rewrite the table under an exclusive lock.

**Mitigation:** Add a column of the new type, backfill it, switch reads, then drop the old column.

## alembic_rename_column_breaks_running_code

**Operation:** `alter_column(new_column_name=...)` · **Severity:** warning · **Confidence:** medium

Code still running from the previous release keeps using the old name until every instance is replaced. The finding carries `old_name`.

**Mitigation:** Add the new column, write to both, backfill, switch reads, then drop the old one.

## alembic_rename_table_breaks_running_code

**Operation:** `rename_table` · **Severity:** warning · **Confidence:** medium

The previous release keeps querying the old table name.

**Mitigation:** Create the new table, or a view under the new name, migrate readers, then drop the old one.

## alembic_drop_column_breaks_running_code

**Operation:** `drop_column` · **Severity:** warning · **Confidence:** medium · *populated tables only*

The previous release's models still select the column until every instance is replaced.

**Mitigation:** Remove the column from the models and deploy first; drop it in a later release.

## alembic_drop_table_breaks_running_code

**Operation:** `drop_table` · **Severity:** warning · **Confidence:** medium · *populated tables only*

The previous release's models still query the table, so every remaining instance fails until it is replaced.

**Mitigation:** Remove the table from the models and deploy first; drop it in a later release.

## alembic_add_unique_constraint_locks_and_may_fail

**Operation:** `create_unique_constraint` · **Severity:** warning · **Confidence:** medium · *populated tables only*

The backing index is built while writes are blocked, and existing duplicates make it fail.

**Mitigation:** `CREATE UNIQUE INDEX CONCURRENTLY`, then `ADD CONSTRAINT ... USING INDEX`.

## alembic_add_foreign_key_validates_rows

**Operation:** `create_foreign_key` · **Severity:** warning · **Confidence:** medium · *populated tables only*

Every existing row is checked while both tables are locked against writes.

**Mitigation:** Add the constraint `NOT VALID` with `op.execute`, then `VALIDATE CONSTRAINT` in a separate step.

## alembic_add_check_constraint_validates_rows

**Operation:** `create_check_constraint` · **Severity:** warning · **Confidence:** medium · *populated tables only*

Every existing row is checked under an exclusive lock.

**Mitigation:** Add it `NOT VALID` with `op.execute`, then `VALIDATE CONSTRAINT`.

## alembic_multiple_heads

**Operation:** (revision graph) · **Severity:** critical · **Confidence:** high, or warning / medium when `branch_labels` are in use

More than one head in a directory's revision history makes `alembic upgrade head` fail with *Multiple head revisions are present*. Each directory is its own history, so `versions/postgresql/` and `versions/sqlite/` are checked separately. A revision written in syntax newer than the Python running the scan still counts in the graph: its header is read even when the file cannot be parsed.

**Mitigation:** `alembic merge heads -m merge` adds a revision that depends on every head.
