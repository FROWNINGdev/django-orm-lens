# Rule reference

🌐 [Tiếng Việt](../i18n/rules/vi/README.md)


Django ORM Lens ships two rule surfaces:

1. **Editor rules (`DOL###`)** — 16 line-oriented static checks that run inside the VS Code extension on every `.py` file. Findings appear in the Problems panel under the source `Django ORM Lens`, link to these pages from the diagnostic code, and — where a fix is safe to express as a text edit — carry a QuickFix lightbulb. Detection is regex-based with bounded windows; no Python process is involved.
2. **CLI / CI analyzers** — AST-based checks in the Python package (`pip install django-orm-lens`) for terminals and pipelines: [`migration-risk`](migrations.md) and [`nplusone`](nplusone.md).

## Severity and applicability

Severity mirrors VS Code's four diagnostic levels: `error`, `warning`, `info`, `hint`. Every rule has a default (listed below); override per rule in `.vscode/settings.json` via `djangoOrmLens.rules` — e.g. `{"djangoOrmLens.rules": {"DOL013": "error", "DOL007": "off"}}`.

Applicability follows Clippy's semantics. It is a property of each individual finding and gates whether an editor may apply the fix unattended:

| Applicability | Meaning |
|---|---|
| `safe` | Semantically equivalent, always correct to apply. Eligible for auto-apply and "Fix All". |
| `suggestion` | Usually right but may need review — offered as a QuickFix, never included in "Fix All". |
| `unsafe` | Likely-correct but breaks in edge cases — surfaced as a diagnostic only, never auto-applied. |

## Editor rules

| Code | Rule | Category | Default severity | Applicability |
|---|---|---|---|---|
| [DOL001](DOL001.md) | Prefer `.exists()` over `.count() > 0` | queryset | info | safe |
| [DOL002](DOL002.md) | Prefer `not .exists()` over `.count() == 0` | queryset | info | safe |
| [DOL003](DOL003.md) | Prefer `not .exists()` over `.first() is None` | queryset | info | safe |
| [DOL004](DOL004.md) | Prefer `.exists()` over `.first() is not None` | queryset | info | safe |
| [DOL005](DOL005.md) | Consider `Q(...)` over `.filter().exclude()` chain | queryset | hint | suggestion |
| [DOL006](DOL006.md) | Drop `list()` around a QuerySet in for-loop | queryset | info | safe |
| [DOL007](DOL007.md) | Possible N+1: attribute access inside for-loop | queryset | warning | unsafe |
| [DOL011](DOL011.md) | `null=True` on CharField/TextField | model | warning | suggestion |
| [DOL012](DOL012.md) | Model without `__str__` method | model | info | suggestion |
| [DOL013](DOL013.md) | ForeignKey without `on_delete` | model | error | suggestion |
| [DOL014](DOL014.md) | CharField without `max_length` | model | error | suggestion |
| [DOL015](DOL015.md) | TextField with `max_length` has no DB effect | model | hint | suggestion |
| [DOL021](DOL021.md) | `datetime.now()` should be `timezone.now()` | datetime | warning | suggestion |
| [DOL022](DOL022.md) | `datetime.utcnow()` is deprecated | datetime | warning | suggestion |
| [DOL031](DOL031.md) | `render()` with `locals()` as context | forms | warning | suggestion |
| [DOL032](DOL032.md) | `fields = '__all__'` in Meta | forms | warning | unsafe |

### Suppressing findings inline

```python
# django-orm-lens-disable-next-line DOL007        (next line; comma-separate for several codes)
qs.count() > 0  # django-orm-lens-disable-line DOL001
# django-orm-lens-disable DOL011                  (own line — disables for the rest of the file)
```

Ruff-style bulk selection is also available: `djangoOrmLens.rulesSelect` (e.g. `["DOL0"]`) and `djangoOrmLens.rulesIgnore` (e.g. `["DOL03"]`).

## CLI / CI analyzers

These run from the Python CLI, not the editor. Both exit non-zero on findings (see each page for exact semantics) and emit `--format sarif` (SARIF 2.1.0 for GitHub Code Scanning) or `--format github` (workflow commands for zero-setup PR annotations).

- **[Migration risk rules](migrations.md)** — 15 rules over `<app>/migrations/*.py` flagging operations that are dangerous on production databases. Run with `django-orm-lens migration-risk`.
- **[Static N+1 detector](nplusone.md)** — flags FK / O2O / M2M / reverse-manager access inside for-loops when the source queryset has no matching `select_related` / `prefetch_related`. Run with `django-orm-lens nplusone`.
