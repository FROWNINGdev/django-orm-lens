# Golden fixtures — real-world Django `models.py`

Vendored `models.py` files from established open-source Django projects. Used
by `cli/tests/test_golden_fixtures.py` to prove `django-orm-lens` survives
real-world code at scale.

**Fetch date:** 2026-07-16

**Only `models.py` files are vendored** — no views, settings, URL routes, or
other application code. Each file is stored at its original relative path so
`scan_workspace` sees the same app-directory boundaries the upstream project
does.

The `scripts/fetch_golden_fixtures.py` script at the repo root reproduces
this tree from GitHub via `gh api`.

## Attribution

All projects below use permissive licences (Apache-2.0, BSD-2-Clause, or
BSD-3-Clause) and allow verbatim redistribution of source files with copyright
notice retained. The original licence and copyright notices remain in each file
(top-of-file headers) where present and are preserved unchanged. Each vendored
subtree is a partial copy, unmodified.

| Project      | Repo                                      | Licence      | Files fetched                                                                 |
|--------------|-------------------------------------------|--------------|-------------------------------------------------------------------------------|
| Zulip        | https://github.com/zulip/zulip            | Apache-2.0   | `zerver/models/{__init__,realms,users,messages,streams,realm_audit_logs}.py`  |
| Saleor       | https://github.com/saleor/saleor          | BSD-3-Clause | `saleor/{product,order,discount,warehouse}/models.py`                         |
| Wagtail      | https://github.com/wagtail/wagtail        | BSD-3-Clause | `wagtail/models/{__init__,pages,sites}.py`                                    |
| django-CMS   | https://github.com/django-cms/django-cms  | BSD-3-Clause | `cms/models/{__init__,pagemodel,placeholdermodel,pluginmodel}.py`             |
| Mezzanine    | https://github.com/stephenmcd/mezzanine   | BSD-2-Clause | `mezzanine/blog/models.py`                                                    |

Full licence texts are available in each upstream repository's `LICENSE`
file at the linked URL above.
