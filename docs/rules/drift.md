# Schema drift

`django-orm-lens drift --path .` answers one question: **do the migrations still describe the models?**

Django already answers it with `makemigrations --check`. That needs a working settings module, an importable app registry, and every third-party dependency installed. On a cold clone, a broken venv, or a CI job that deliberately does not boot the project, the answer is unavailable exactly when acting on it would be cheapest.

This does it from source. Each app's migrations are replayed in numeric order — `CreateModel`, `AddField`, `RemoveField`, `RenameField`, `DeleteModel`, `RenameModel` — into the set of fields the migrations believe each model has. That is then compared against what `models.py` declares.

`AlterField` is not replayed: it changes a column's type or options, never whether the field exists, so it cannot produce drift in this sense.

## Two directions, and only one of them blocks

| Drift | Meaning | Exit code |
|---|---|---|
| Declared in `models.py`, never migrated | Somebody edited a model and forgot `makemigrations`. The column will not exist; the first query touching it fails. | **1** |
| Model declared with no `CreateModel` anywhere | Same failure, whole table. | **1** |
| Migrated, no longer declared | A column nothing reads. Usually harmless; occasionally a half-finished removal still holding `NOT NULL`. | 0 |
| Created by migrations, model not found | Stale table, or the model lives outside the parsed tree. | 0 |

The narrow blocking rule is deliberate. Static analysis cannot see fields Django computes at import time — abstract bases resolved through metaclasses, fields injected by third-party mixins, swappable models. Those surface as "extra in migrations", and failing a build on them would teach people to pass `--exit-zero` permanently, which costs more than the check is worth.

`id` is ignored in both directions: Django adds it unless told otherwise, so a migration that omits it is not drift.

## Usage

```bash
django-orm-lens drift --path .            # text, exit 1 on blocking drift
django-orm-lens drift --format json       # machine-readable
django-orm-lens drift --exit-zero         # report without failing the build
```

```
!! blog.post:
     declared but never migrated: author
       the column will be missing at runtime

summary: 1 model(s) drifted, 1 blocking, 2 migration(s) replayed
```

Blocking entries sort first, so the thing that breaks production is the first line of output.

## In CI

```yaml
- uses: FROWNINGdev/django-orm-lens@action-v1
  with:
    command: drift
```

No database, no settings module, no installed dependencies — the same reason the rest of this tool runs on a cold clone.

## JSON shape

```jsonc
{
  "drifted": [
    {
      "app": "blog",
      "model": "post",
      "missingInMigrations": ["author"],
      "missingInModels": [],
      "onlyInModels": false,
      "onlyInMigrations": false,
      "blocking": true
    }
  ],
  "summary": { "apps": 1, "migrations": 2, "drifted": 1, "blocking": 1 }
}
```

## Limits worth knowing

- **Per model, per app.** Cross-app `ForeignKey` targets are not resolved; drift is measured against each model's own field set.
- **A migration that will not parse is skipped, not fatal.** One malformed file must not blank out an app's whole state — but its operations are then missing from the replay, which can surface as drift that is not real.
- **Fields added outside `models.py`** — `add_to_class`, mixins applied at runtime — read as "migrated but not declared". That is precisely why that direction does not block.

## Related

- [`migration-risk`](migrations.md) — is an individual migration dangerous to run?
- [`blast-radius`](blast-radius.md) — what does a schema change hit?
