Fixture snippets used by tests/test_migration_risk.py.

Each subdirectory holds a self-contained Django-shaped app with a
`migrations/` folder containing one or more `NNNN_*.py` migration files
illustrating a specific risk (or its safe counterpart).

These files are NOT valid packages on their own — they're loaded by the
test harness which copies them into a tmp workspace root before invoking
`analyze_migration_risks`.
