# Migration playbook

Read this when a migration review (Playbook B) found something and you need
to write the safe version. Contents:

1. The 16 risk rules
2. Safe rewrites, with code
3. Deploy order for destructive changes

## 1. The 16 risk rules

Severity and confidence are what `migration-risk` / `blast_radius` report.

| Rule | Operation | Severity | What goes wrong |
|---|---|---|---|
| `add_field_not_null_no_default` | AddField | critical | NOT NULL column without a default: existing rows raise IntegrityError, the migration fails mid-deploy |
| `add_field_unique_no_row_default` | AddField | critical | unique column filled with one shared default: the unique index fails on the second row |
| `remove_field_still_referenced` | RemoveField | critical | the field is still declared in models.py — code reads a column that is about to vanish |
| `delete_model_still_referenced` | DeleteModel | critical | the model still exists in models.py |
| `conflicting_migration_leaves` | graph | critical | two leaf migrations in one app: `migrate` refuses to run |
| `rename_field_rolling_deploy` | RenameField | warning | old app instances keep querying the old column during a rolling deploy |
| `rename_model_rolling_deploy` | RenameModel | warning | same, for the table name |
| `add_index_locks_table` | AddIndex | warning | plain `CREATE INDEX` holds a Postgres SHARE lock for the whole build — reads continue, every write to the table blocks |
| `alter_field_char_length` | AlterField | warning | shrinking `max_length` truncates or fails on existing data; can rewrite the table |
| `alter_field_int_type` | AlterField | warning | integer type change rewrites the table under lock; narrowing can overflow |
| `runsql_no_reverse` | RunSQL | warning | no `reverse_sql`: the migration cannot be rolled back |
| `runpython_no_reverse` | RunPython | warning | no `reverse_code`: cannot roll back |
| `alter_unique_together_lock` | AlterUniqueTogether | warning | builds a unique index under lock, fails on existing duplicates |
| `remove_field` | RemoveField | info | field already gone from models.py — `blast-radius --severity info` lists code still reading it |
| `remove_field_unverified` | RemoveField | info | schema could not be cross-checked — confirm nothing still reads the field |
| `delete_model_unverified` | DeleteModel | info | same, for a model |
| `alter_index_together_deprecated` | AlterIndexTogether | info | `index_together` is deprecated; use `Meta.indexes` |

`AddIndexConcurrently` and `RemoveIndex` are recognized as safe and never
flagged.

## 2. Safe rewrites

### NOT NULL column on a table with rows — three steps

```python
# 0002: add as nullable
migrations.AddField("product", "weight_grams", models.PositiveIntegerField(null=True))


# 0003: backfill in batches
def backfill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    qs = Product.objects.filter(weight_grams__isnull=True)
    while ids := list(qs.values_list("pk", flat=True)[:1000]):
        Product.objects.filter(pk__in=ids).update(weight_grams=0)


# noop reverse: the migration can be unapplied, the backfilled values stay
migrations.RunPython(backfill, migrations.RunPython.noop)

# 0004 (next release): enforce
migrations.AlterField("product", "weight_grams", models.PositiveIntegerField())
```

If a constant default is genuinely correct, one step is fine:
`field=models.PositiveIntegerField(default=0)`. On Postgres 11+ adding a
column with a constant default does not rewrite the table.

### Index on a live Postgres table

```python
from django.contrib.postgres.operations import AddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # CONCURRENTLY cannot run inside a transaction
    dependencies = [...]
    operations = [
        AddIndexConcurrently(
            "product",
            models.Index(
                fields=["is_active", "price"], name="product_active_price_idx"
            ),
        ),
    ]
```

Keep a concurrent index in its own migration — `atomic = False` applies to
every operation in the file.

### Rename without breaking a rolling deploy — expand / contract

1. Release N: add the new field (nullable), write to both, backfill old → new.
2. Release N+1: read from the new field only.
3. Release N+2: remove the old field.

When the rename only matters in Python and the column name can stay, skip
the data move:

```python
name = models.CharField(max_length=200, db_column="title")
```

or record the rename for Django's state only:

```python
migrations.SeparateDatabaseAndState(
    state_operations=[migrations.RenameField("product", "title", "name")],
    database_operations=[],
)
```

### Unique constraint on existing data

1. Find and fix duplicates first (a `RunPython` with a reverse).
2. On Postgres, build the index concurrently, then attach the constraint:

```python
migrations.SeparateDatabaseAndState(
    database_operations=[
        migrations.RunSQL(
            "CREATE UNIQUE INDEX CONCURRENTLY order_ref_uniq ON orders_order (ref);",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS order_ref_uniq;",
        ),
        # Promote the index to a real constraint (instant, reuses the index),
        # so the database matches the AddConstraint Django records below.
        migrations.RunSQL(
            "ALTER TABLE orders_order ADD CONSTRAINT order_ref_uniq "
            "UNIQUE USING INDEX order_ref_uniq;",
            reverse_sql="ALTER TABLE orders_order DROP CONSTRAINT order_ref_uniq;",
        ),
    ],
    state_operations=[
        migrations.AddConstraint(
            "order",
            models.UniqueConstraint(fields=["ref"], name="order_ref_uniq"),
        )
    ],
)
```

(`atomic = False` on that migration.) Without the second statement Django's
state would record a constraint the database does not have, and a later
`RemoveConstraint` would fail. Prefer `UniqueConstraint` over
`unique_together`.

### Narrowing a column (char length, int type)

Check the data before the schema: `Max(Length("code"))` or
`Max("counter")`. Narrow only when nothing exceeds the new limit; otherwise
clean up in a `RunPython` step first. For big tables, add a new column, copy,
and swap (expand/contract) instead of altering in place.

### Irreversible RunSQL / RunPython

Always pass the reverse, even when it is a no-op:

```python
migrations.RunPython(forwards, migrations.RunPython.noop)
migrations.RunSQL("UPDATE ...", reverse_sql=migrations.RunSQL.noop)
```

A no-op reverse is an explicit statement; a missing one blocks rollback. Be
clear about what it means: `noop` lets the migration graph roll back, but
the data stays as the forward step left it. When a rollback must restore
data (a destructive transform, a merge of rows), write a real reverse
function instead.

### Conflicting leaves

`python manage.py makemigrations --merge` when both branches are already
applied somewhere. If neither is deployed yet, prefer editing the newer
migration's `dependencies` to point at the other leaf — the history stays
linear.

## 3. Deploy order for destructive changes

Removing a field or model is two releases, never one:

1. **Release N — stop using it.** Remove every reference that `impact`
   reports (models code, serializers, forms, admin, views, templates, tests).
   Keep the field in `models.py` for this release.
2. **Release N+1 — drop it.** Remove the field from `models.py`, run
   `makemigrations`, and run `impact` once more on the name: only the
   migration files should still mention it. Then run `blast_radius` on the
   new migration.

A rollback of release N+1 then needs no data restore, because nothing still
needed the column.

Before deleting a model, run `cascade_preview` on it and on everything in its
`cascade_kills`, recursively: `on_delete=CASCADE` decides what each row
deletion takes with it, several levels deep.
