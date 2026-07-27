# Static N+1 detector

`django-orm-lens nplusone --path .` (alias: `n-plus-one`) walks every `.py` file in the workspace — skipping `migrations/`, virtualenvs, `node_modules/`, hidden directories, `site-packages`, `dist`, `build`, `eggs` — parses each with `ast.parse`, and flags the classic Django N+1 shape: a `for` loop over a queryset whose body accesses a related object per iteration, with no matching `select_related` / `prefetch_related` on the source queryset. No Django boot, no database, no code execution.

## What it detects

The scanner resolves the loop source two ways: inline chains (`for p in Post.objects.filter(...):`) and variables bound earlier to a queryset chain (`qs = Post.objects.all()` … `for p in qs:` — the most recent binding per name, tracked per function scope). Inside the loop body it collects accesses rooted at the loop variable:

- `p.author.name` — attribute chain, suggests `ForeignKey` / `OneToOneField` traversal → needs `select_related`
- `p.tags.all()` / `p.tags.filter(...)` / `.exclude` / `.count` / `.exists` — related-manager idiom → needs `prefetch_related`
- `p.comment_set...` — the `_set` reverse-manager naming → needs `prefetch_related`

Accesses already covered by a `select_related(...)` / `prefetch_related(...)` clause in the chain are not flagged — string arguments are matched by their first lookup segment, a bare `.select_related()` counts as covering every FK, and `Prefetch("lookup", ...)` objects are understood. Each finding includes a rendered `suggested_fix`, e.g. `.select_related("author").prefetch_related("tags")`.

## Confidence levels

- **high** — the loop source resolved to a model known to the parsed workspace schema, and the accessed attribute is a declared `ForeignKey` / `OneToOneField` / `ManyToManyField` or a computed reverse relation (`related_name` or default `<model>_set`). The unambiguous `<attr>_set` reverse-manager idiom also counts as high even without schema resolution.
- **medium** — structural heuristics only: the source model could not be resolved, and the access pattern (attribute chain, `.all()` on an attribute) merely *suggests* a relation.

When the source model is known but the attribute is not a declared relation, the scanner assumes a scalar and stays silent — it prefers missing a finding over inventing one.

## CLI usage

```bash
django-orm-lens nplusone --path .                    # all findings, text output
django-orm-lens nplusone --confidence high           # schema-confirmed findings only
django-orm-lens nplusone --format sarif > npo.sarif  # SARIF 2.1.0 for GitHub Code Scanning
django-orm-lens nplusone --format github             # ::warning workflow commands for PR annotations
```

- **`--confidence high|medium|all`** (default `all`) — minimum confidence to report; `medium` includes `high`. Use `high` in CI to keep the gate noise-free.
- **`--format text|json|sarif|github`** — same output surface as `migration-risk`.
- **Exit code:** `1` when any finding remains after the confidence filter, `0` otherwise; `--exit-zero` always exits `0`.

## Limitations

This is a static heuristic, not runtime query capture — it never sees the SQL your app actually runs. Known blind spots:

- Only the most recent assignment of a queryset variable is tracked; re-bindings, querysets passed across function boundaries, and querysets returned from helpers are not followed.
- Properties and methods that query the database internally are invisible; conversely, a `@cached_property` or an attribute cached earlier may be flagged although it costs nothing.
- Loops over unresolvable iterables (dicts, lists, ranges, unrecognized calls) are skipped entirely rather than guessed at.
- Attribute chains are evidence, not proof — a medium-confidence finding can be a plain object attribute. That is what the confidence filter is for.

Treat findings as review pointers with a suggested fix attached, and pair the detector with a runtime tool (e.g. query logging in tests) when you need proof.
