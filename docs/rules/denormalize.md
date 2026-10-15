# Denormalization review

`orm-synapse denormalize` reports three smells. It does not prove 2NF or 3NF, and the default exit code is 0, so a pull request is not blocked.

On a pull request the check looks only at a **new table** (the `class` line is added) or a **new column** (the field line is added). A column that was already there is not annotated. A local run without `--only-added` still reports the whole schema.

| Code | Smell |
|---|---|
| [DOL018](DOL018.md) | Text or JSON column ending in `_ids` |
| [DOL019](DOL019.md) | `stem_1`, `stem_2`, `stem_3` |
| [DOL020](DOL020.md) | `company_name` beside a `company` foreign key |

`company_id = IntegerField()` is not reported. A scalar id without a foreign key is a convention, not a copied column.

```bash
orm-synapse denormalize --path . --format github
orm-synapse denormalize --path . --only-added pr.diff
orm-synapse denormalize --path . --strict   # exit 1 when a smell is found
```

`--format github` prints `::warning` annotations, never `::error`. Inside GitHub Actions the command also appends a markdown table to the job summary.

Silence one column:

```python
# orm-synapse-disable-next-line DOL020
company_name = models.CharField(max_length=100)  # snapshot taken at checkout
```

## Pull request workflow

```yaml
name: Denormalization review
on:
  pull_request:
permissions:
  contents: read
  pull-requests: read
jobs:
  denormalize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: frowningdev/orm-synapse@v1
        with:
          command: denormalize
          path: .
          format: github
          github-token: ${{ github.token }}
```

Until a release contains this command, install the checkout and set `install: false`, as `.github/workflows/denormalize.yml` does.
