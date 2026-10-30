---
title: "Django 6.1's DB_CASCADE skips your post_delete handlers"
description: >-
  on_delete=models.DB_CASCADE in Django 6.1 lets the database delete child rows,
  so pre_delete and post_delete never fire for them. How to find the handlers
  that silently stop running, before you switch.
---

# Django 6.1's `DB_CASCADE` skips your `post_delete` handlers

*FROWNINGdev · 31 October 2026*

Django 6.1 added three `on_delete` policies that run in the database instead of
in Python:

```python
from django.db import models

class Attachment(models.Model):
    order = models.ForeignKey("shop.Order", on_delete=models.DB_CASCADE)
    file = models.FileField()
```

`DB_CASCADE`, `DB_SET_NULL` and `DB_SET_DEFAULT` put `ON DELETE CASCADE` /
`SET NULL` / `SET DEFAULT` on the foreign-key constraint and let the database
do the work. Deleting an `Order` becomes one `DELETE` statement. Django no
longer loads every child row into memory first to find out what else it has
to delete.

That speed has a cost, and the 6.1 release notes say so: **`DB_CASCADE` does
not send `pre_delete` or `post_delete` for the rows the database removes.**
Django never sees those rows, so it has nothing to send signals about.

## What stops working

Most projects have at least one delete handler they no longer think about:

```python
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Attachment

@receiver(post_delete, sender=Attachment)
def delete_file_from_storage(sender, instance, **kwargs):
    instance.file.delete(save=False)
```

With the ORM's `CASCADE`, deleting an order deletes its attachments *and*
calls this handler once per attachment, so the files leave S3 too. Switch the
foreign key to `DB_CASCADE` and the rows still disappear, but the handler
never runs. You get no error and no log line, and the files stay in the
bucket.

The same goes for audit trails written on delete, search-index removal, cache
invalidation, and counters kept in sync by signals. A receiver registered
with no `sender` ("log every delete") is also skipped for those rows.

Third-party apps count too. django-cleanup and django-simple-history both
listen to `post_delete`. If they cover a model you move to `DB_CASCADE`,
assume they stop covering the rows the database deletes.

## Finding them before you switch

Grepping for `post_delete` gets you the handlers, but not which ones a given
`DB_CASCADE` foreign key will silence. You also have to match each receiver's
`sender` against the models on the receiving end of the cascade, and remember
that a sender-less receiver matches all of them.

[django-orm-lens](https://github.com/FROWNINGdev/django-orm-lens) does that
matching statically: it reads your source, so it needs no database and no
`django.setup()`. Since py-1.13.8, `cascade` lists the delete handlers each
`DB_CASCADE` relation skips:

```text
$ uvx django-orm-lens cascade shop.Order
deleting one shop.Order row:
  CASCADE-deletes rows in (1):
    - shop.Attachment  via order (db)
  (db) = on_delete=DB_*: the database applies it, so Django sends no delete signals for those rows.
  ! 1 delete receiver(s) will NOT run for (db) rows:
    - post_delete shop.signals.delete_file_from_storage  for shop.Attachment  (shop/signals.py:6)
```

`--format json` puts the same list under `skipped_receivers`, so a CI step can
fail on it. The MCP server's `cascade_preview` tool returns it too, so an AI
agent that proposes switching to `DB_CASCADE` gets told which handlers go
quiet.

What the scan does not cover, so you know where to look by hand:

- It reads `@receiver(...)` decorators and
  `post_delete.connect(handler, sender=Model)` calls in your project.
- Receivers that third-party packages register inside site-packages are not
  scanned.
- It reports one level of cascade. Run it again for each model it lists, the
  same way the database will follow the constraints.

## What to do with a handler that would be skipped

- **Keep the ORM's `CASCADE` on that relation.** `DB_CASCADE` is opt-in per
  foreign key. Use it where deletes are hot and side-effect free, and keep
  `CASCADE` where a handler has to run.
- **Do the side effect explicitly.** Collect the file names before you delete
  the parent, then remove them after the transaction commits
  (`transaction.on_commit`).
- **Clean up asynchronously.** A periodic job that deletes storage objects
  with no matching row is slower to converge, but it survives any delete path,
  raw SQL included.

What you should not do is switch the policy and trust that the handlers still
fire. The rows disappear either way, so nothing tells you the handler stopped
running.

---

django-orm-lens is free and MIT: a VS Code extension, a CLI (`pip install
django-orm-lens`) and an MCP server for AI agents, all working from your
source. It also handles the older ways of writing a cascade. A positional
`ForeignKey(Order, models.CASCADE)`, the way `django.contrib` writes it, and
`DO_NOTHING`, which leaves rows for the constraint to reject, are both
reported since py-1.13.7.
