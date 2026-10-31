---
title: "My Django migration linter raised 407 alarms on six big codebases. 405 were wrong"
description: >-
  Running orm-lens over NetBox, PostHog, authentik, Plane, paperless-ngx
  and Healthchecks produced 407 critical migration findings. Two were real. What
  the other 405 taught me about how Django really migrates a populated table.
---

# My Django migration linter raised 407 alarms on six big codebases. 405 were wrong

*FROWNINGdev · 31 October 2026*

I maintain [orm-lens](https://github.com/FROWNINGdev/orm-lens) (until
recently django-orm-lens), a static analyzer for Django models and
migrations. One of its checks,
`migration-risk`, reads every migration file and flags operations that break
on a table that already has rows: a `NOT NULL` column with no default, a
`UNIQUE` column that existing duplicates will violate, an index build that
locks the table.

Its test suite was green, so I pointed it at real projects:

| Project | GitHub stars | Critical findings |
|---|---|---|
| NetBox | 21.8k | 212 |
| PostHog | 40.5k | 79 |
| authentik | 26.2k | 58 |
| Healthchecks | 10.5k | 27 |
| Plane | 61.7k | 25 |
| paperless-ngx | 47.4k | 6 |

That is **407 critical findings**. I read every one, and two were real.

The other 405 were not edge cases. Each came from something Django does
when it migrates a populated table, which I had modelled wrongly. Here they
are, ordered by how many false alarms each caused.

## 1. Squashed migrations never touch a populated table (208)

```python
class Migration(migrations.Migration):
    replaces = [("dcim", "0002_auto_..."), ..., ("dcim", "0059_...")]
```

A squashed migration only runs on a fresh database. On a database where the
replaced migrations are already applied, Django marks the squash as applied
without running it. On a database where only some of them are applied, it
keeps running the originals. Either way, every `AddField` inside a squash
lands on an empty table. Squashes alone made up more than half of all the
alarms.

## 2. `blank=True` text fields get `""` (83)

```python
migrations.AddField("virtualmachine", "serial",
                    models.CharField(blank=True, max_length=50))
```

No `default=` and no `null=True`, so the column is `NOT NULL`, yet this is
safe. `BaseDatabaseSchemaEditor._effective_default()` fills existing rows with
`""` for any `blank=True` field whose class allows empty strings. Projects
also subclass `CharField`: NetBox's `ColorField(blank=True, max_length=6)` gets
the same treatment. The linter now treats a `max_length` argument as a sign of
a text field.

## 3. Many-to-many fields add no column (37)

`ManyToManyField`, django-taggit's `TaggableManager` and `GenericRelation`
create a join table, or nothing at all. They are never a `NOT NULL` risk on
the model's own table.

## 4. `makemigrations` splits foreign keys out of `CreateModel` (25)

```python
migrations.CreateModel(name="ContactGroupMembership", fields=[...]),
...
migrations.AddField("contactgroupmembership", "group",
                    models.ForeignKey(..., on_delete=models.CASCADE)),
```

To break dependency cycles, the autodetector creates the table first and
adds some foreign keys afterwards, in the same migration. That table was
created a few lines earlier, so it is empty.

## 5. A squash and the migrations it replaces are not two leaves (17)

Django refuses to migrate an app whose migration graph has two leaf nodes.
The check flagged authentik's apps as conflicting because the squash and the
last migration it replaces both looked like leaves. The loader drops the
replaced nodes and points their dependents at the squash, so the linter now
does the same before it counts leaves.

## 6. `auto_now`, `db_default` and `GeneratedField` fill themselves (16)

`auto_now_add=True` gets the current time on `ADD COLUMN`, and `db_default`
is a database-side default. A `GeneratedField` is computed by the database.
None of them needs `default=`.

## 7. NULLs don't collide (12)

```python
models.CharField(blank=True, max_length=128, null=True, unique=True)
```

Existing rows get `NULL`. On PostgreSQL, MySQL and SQLite a unique constraint
never treats two NULLs as equal, so this is safe. The same holds for
`default=None`, which authentik uses on four fields across three migrations.

## 8. Names that come back (5)

A `RemoveField` followed by an `AddField` of the same name, or a
`RenameField` onto it, leaves the field in place. So does a `DeleteModel`
followed by a `CreateModel`. The linter compared each historical removal
with today's `models.py`, saw the field still there, and called it drift.

## 9. Data migrations that run first (2)

authentik adds a `NOT NULL` column right after a `RunPython` that, its comment
says, deletes every row. A static tool cannot prove what a `RunPython` does,
so this is now a warning that says why, rather than a certain critical.

## The two that were real

PostHog's `0308_add_indirect_person_override_constraints` removes two
foreign-key columns and adds them back as `NOT NULL` with no default:

```python
migrations.RemoveField(model_name="personoverride", name="old_person_id"),
migrations.AddField(model_name="personoverride", name="old_person_id",
                    field=models.ForeignKey(on_delete=..., to=...)),
```

On a populated `personoverride` table this fails. The table may well have
been empty when it shipped. The linter cannot know that, and it does not
pretend to.

## The same exercise for N+1

`nplusone` had its own share of noise: writes through a relation
(`interface.vdcs.set(...)`) reported as reads, one field suggested in both
`select_related` and `prefetch_related`, and loops in test files. After those
fixes I drew a random sample of the remaining high-confidence findings
across the six projects, and all six were real N+1s. One example is
`installation.organization` read inside a loop over installations, which is
fixed with `select_related("organization")`.

## What I took from it

A static analyzer is only as good as its precision on code it has never seen.
Synthetic test fixtures confirmed that the rules did what I wrote. They could
not tell me whether what I wrote was true of Django. Big open-source codebases
can, and running against them is now part of how the rules are tested.

All of the above shipped in py-1.14.0. Try it on your own history:

```bash
uvx orm-lens migration-risk      # migration findings, critical by default
uvx orm-lens nplusone            # N+1 loops, with the select_related to add
```

It reads source only: no database, no settings module, no `django.setup()`.
It is free and MIT. If it is wrong about your project, [open an
issue](https://github.com/FROWNINGdev/orm-lens/issues). That is how
this whole list came about.
