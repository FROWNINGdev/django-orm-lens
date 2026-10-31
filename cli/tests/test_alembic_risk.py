"""Alembic revision risks: each rule, and each precision lesson from the census.

The census ran over Superset, Airflow, Prefect, Polar, Dispatch, Mealie and the
FastAPI full-stack template (~1170 revisions). Cases below mirror what it hit.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from django_orm_lens.alembic_risk import analyze_alembic_risks
from django_orm_lens.cli import main

HEADER = (
    "import sqlalchemy as sa\n"
    "from alembic import op\n\n"
    'revision = "{rev}"\n'
    "down_revision = {down}\n"
    "branch_labels = {labels}\n\n\n"
    "def upgrade():\n"
)


def _rev(versions: Path, rev: str, down: str | None, body: str, labels: str = "None") -> None:
    versions.mkdir(parents=True, exist_ok=True)
    down_src = "None" if down is None else (down if down.startswith("(") else f'"{down}"')
    (versions / f"{rev}_change.py").write_text(
        HEADER.format(rev=rev, down=down_src, labels=labels) + body + "\n\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )


def _rules(tmp_path: Path, body: str, base: bool = False) -> dict[str, list]:
    versions = tmp_path / "alembic" / "versions"
    if base:
        _rev(versions, "aaa", None, body)
    else:
        _rev(versions, "aaa", None, "    op.create_table('orders', sa.Column('id', sa.Integer()))")
        _rev(versions, "bbb", "aaa", body)
    out: dict[str, list] = {}
    for f in analyze_alembic_risks(str(tmp_path)):
        out.setdefault(f.rule, []).append(f)
    return out


NN = "alembic_add_column_not_null_no_server_default"


def test_not_null_without_server_default_is_critical(tmp_path: Path) -> None:
    rules = _rules(tmp_path, "    op.add_column('orders', sa.Column('status', sa.String(), nullable=False))")
    (f,) = rules[NN]
    assert (f.severity, f.model, f.field) == ("critical", "orders", "status")


def test_python_default_does_not_fill_existing_rows(tmp_path: Path) -> None:
    # Superset af30ca79208f: default=0, nullable=False, no server_default.
    rules = _rules(tmp_path, "    op.add_column('orders', sa.Column('n', sa.Integer(), default=0, nullable=False))")
    assert "INSERT only" in rules[NN][0].description


def test_safe_add_column_forms(tmp_path: Path) -> None:
    for i, column in enumerate((
        "sa.Column('n', sa.Integer(), nullable=False, server_default='0')",
        "sa.Column('n', sa.Integer(), nullable=True)",
        "sa.Column('n', sa.Integer())",  # SQLAlchemy columns are nullable by default
        "sa.Column('n', sa.Integer(), sa.Computed('id * 2'), nullable=False)",
    )):
        assert NN not in _rules(tmp_path / str(i), f"    op.add_column('orders', {column})"), column


def test_table_created_in_the_same_revision_or_base_revision_is_empty(tmp_path: Path) -> None:
    same = (
        "    op.create_table('lines', sa.Column('id', sa.Integer()))\n"
        "    op.add_column('lines', sa.Column('qty', sa.Integer(), nullable=False))\n"
        "    op.create_index('ix_lines_qty', 'lines', ['qty'])"
    )
    rules = _rules(tmp_path / "same", same)
    assert NN not in rules and "alembic_create_index_locks_table" not in rules
    base = "    op.add_column('orders', sa.Column('qty', sa.Integer(), nullable=False))"
    assert NN not in _rules(tmp_path / "base", base, base=True)


def test_data_operation_first_downgrades_to_warning(tmp_path: Path) -> None:
    body = (
        "    op.execute('DELETE FROM orders')\n"
        "    op.add_column('orders', sa.Column('status', sa.String(), nullable=False))"
    )
    f = _rules(tmp_path / "delete", body)[NN][0]
    assert (f.severity, f.confidence) == ("warning", "medium")
    lock_timeout_first = (
        "    op.execute(\"SET LOCAL lock_timeout = '5s'\")\n"
        "    op.add_column('orders', sa.Column('status', sa.String(), nullable=False))"
    )
    assert _rules(tmp_path / "set", lock_timeout_first)[NN][0].severity == "critical"


def test_batch_operations_take_the_table_from_the_with_block(tmp_path: Path) -> None:
    body = (
        "    with op.batch_alter_table('orders', schema=None) as batch_op:\n"
        "        batch_op.add_column(sa.Column('kind', sa.String(), nullable=False))\n"
        "        batch_op.alter_column('status', nullable=False)\n"
        "        batch_op.drop_column('legacy')"
    )
    rules = _rules(tmp_path, body)
    assert rules[NN][0].model == "orders"
    assert rules["alembic_set_not_null_scans_table"][0].field == "status"
    assert rules["alembic_drop_column_breaks_running_code"][0].field == "legacy"


def test_index_concurrently_is_safe(tmp_path: Path) -> None:
    rules = _rules(tmp_path / "plain", "    op.create_index('ix_o', 'orders', ['status'])")
    assert rules["alembic_create_index_locks_table"][0].severity == "warning"
    safe = (
        "    with op.get_context().autocommit_block():\n"
        "        op.create_index('ix_o', 'orders', ['status'], postgresql_concurrently=True)"
    )
    assert "alembic_create_index_locks_table" not in _rules(tmp_path / "conc", safe)


def test_alter_column_rules(tmp_path: Path) -> None:
    body = (
        "    op.alter_column('orders', 'total', type_=sa.BigInteger())\n"
        "    op.alter_column('orders', 'note', new_column_name='memo')"
    )
    rules = _rules(tmp_path, body)
    assert rules["alembic_alter_column_type_rewrites"][0].field == "total"
    rename = rules["alembic_rename_column_breaks_running_code"][0]
    assert (rename.field, rename.old_name) == ("memo", "note")


def test_constraint_rules(tmp_path: Path) -> None:
    body = (
        "    op.create_unique_constraint('uq_o', 'orders', ['code'])\n"
        "    op.create_foreign_key('fk_o', 'orders', 'users', ['user_id'], ['id'])\n"
        "    op.create_check_constraint('ck_o', 'orders', 'total >= 0')"
    )
    rules = _rules(tmp_path, body)
    for rule in (
        "alembic_add_unique_constraint_locks_and_may_fail",
        "alembic_add_foreign_key_validates_rows",
        "alembic_add_check_constraint_validates_rows",
    ):
        assert rules[rule][0].model == "orders", rule


def _heads(tmp_path: Path) -> list:
    return [f for f in analyze_alembic_risks(str(tmp_path)) if f.rule == "alembic_multiple_heads"]


def test_two_heads_break_upgrade_head(tmp_path: Path) -> None:
    v = tmp_path / "migrations" / "versions"  # Flask-Migrate layout
    _rev(v, "aaa", None, "    pass")
    _rev(v, "bbb", "aaa", "    pass")
    _rev(v, "ccc", "aaa", "    pass")
    heads = _heads(tmp_path)
    assert len(heads) == 2 and heads[0].severity == "critical"
    _rev(v, "ddd", '("bbb", "ccc")', "    pass")  # alembic merge heads
    assert _heads(tmp_path) == []


def test_branch_labels_soften_multiple_heads(tmp_path: Path) -> None:
    v = tmp_path / "alembic" / "versions"
    _rev(v, "aaa", None, "    pass")
    _rev(v, "bbb", None, "    pass", labels='("billing",)')
    assert {f.severity for f in _heads(tmp_path)} == {"warning"}


def test_separate_directories_are_separate_histories(tmp_path: Path) -> None:
    # Prefect: versions/postgresql/ and versions/sqlite/ each have one head.
    for dialect in ("postgresql", "sqlite"):
        v = tmp_path / "migrations" / "versions" / dialect
        _rev(v, f"{dialect}1", None, "    pass")
        _rev(v, f"{dialect}2", f"{dialect}1", "    pass")
    assert _heads(tmp_path) == []


def test_revision_in_newer_python_syntax_still_counts_in_the_graph(tmp_path: Path) -> None:
    # Mealie: `except A, B:` (PEP 758, Python 3.14) made the file unparsable on
    # older Pythons, so its parent looked like a second head.
    v = tmp_path / "alembic" / "versions"
    _rev(v, "aaa", None, "    pass")
    _rev(v, "bbb", "aaa", "    pass")
    (v / "ccc_newer.py").write_text(
        'revision = "ccc"\n'
        'down_revision: str | None = "bbb"\n\n'
        "def upgrade() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except OSError ValueError:\n"  # unparsable on every Python
        "        pass\n",
        encoding="utf-8",
    )
    assert _heads(tmp_path) == []


def test_cli_reports_alembic_findings(tmp_path: Path) -> None:
    _rules(tmp_path, "    op.add_column('orders', sa.Column('status', sa.String(), nullable=False))")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["migration-risk", "--path", str(tmp_path), "--format", "json"])
    payload = json.loads(out.getvalue())
    assert code == 1
    assert [f["rule"] for f in payload["findings"]] == [NN]
