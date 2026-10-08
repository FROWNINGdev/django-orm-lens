Shared fixture for issue #135, read by both `cli/tests/test_base_outside_models.py`
and `test/base-outside-models.test.js`.

Every base class here lives outside the files the scanner reads
(`models.py`, `abstract_models.py`, `models/*.py`), so the only way to find
it is to follow the subclass's `import`:

- `core/base.py` — abstract `MyCustomModel`, the shape from the issue.
- `core/db/` — abstract `SoftDeletable(MyCustomModel)`, re-exported through
  `core/db/__init__.py`, so reaching it takes two hops.
- `places/base.py` — a concrete `Located`, pulled in by a relative import.
  Django creates a table for it, so it is a model in its own right.
