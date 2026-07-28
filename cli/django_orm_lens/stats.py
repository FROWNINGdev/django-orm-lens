"""Optional production table statistics — supplied as a file, never fetched.

The rest of this package answers "is this migration dangerous?" from source
alone, and one honest weakness follows from that: it cannot tell a table with
forty million rows from a table with none. The migration-risk analyzer papers
over the gap with a heuristic — *anything after ``0001_`` is assumed
populated* — which is right often enough to be useful and wrong often enough
to be annoying.

This module closes the gap **without the tool ever touching a database**.
The operator runs :data:`STATS_QUERY` themselves on a read-only connection and
hands the resulting JSON to ``--stats``. django-orm-lens never sees a DSN, a
password, or a row of data — only table names and counts.

That is a deliberate design choice, not a limitation:

* No credential ever enters CI config, so there is nothing to leak.
* The query is a single read from ``pg_stat_user_tables``; it takes no locks
  and reads no user data.
* A stats file can be committed, reviewed, and diffed like any other input.

Everything here is an **estimate** and is labelled as one. ``n_live_tup`` is
maintained by the stats collector and refreshed by ``VACUUM`` / ``ANALYZE``;
autovacuum triggers ``ANALYZE`` once roughly 20% of a table's rows have
changed, so a busy table can drift between runs. Right after ``ANALYZE`` it is
typically within a couple of percent. That is plenty to tell forty million
rows from four hundred — which is the decision this feature exists to inform.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATS_QUERY = """\
-- django-orm-lens: production table statistics (read-only, no user data)
-- Run against a replica or with a read-only role, then save the output:
--   psql -At -d "$DATABASE_URL" -f stats.sql > stats.json
SELECT json_build_object(
  'database', 'postgres',
  'version', (current_setting('server_version_num')::int / 10000),
  'generated_at', now(),
  'tables', coalesce(json_object_agg(
      t.relname,
      json_build_object(
        'rows',    t.n_live_tup,
        'bytes',   pg_total_relation_size(t.relid),
        'indexes', (SELECT count(*) FROM pg_index i WHERE i.indrelid = t.relid)
      )
  ), '{}'::json)
) FROM pg_stat_user_tables t;
"""

# Row count above which a schema change stops being a formality. Not a law of
# nature — a threshold at which "this locks the table" is worth saying out loud
# in a review.
LARGE_TABLE_ROWS = 1_000_000


@dataclass(frozen=True)
class TableStats:
    """Estimated size of one table. Every numeric field may be missing."""

    table: str
    rows: int | None = None
    bytes: int | None = None
    indexes: int | None = None

    @property
    def is_large(self) -> bool:
        return self.rows is not None and self.rows >= LARGE_TABLE_ROWS

    @property
    def is_empty(self) -> bool:
        return self.rows == 0

    def human_size(self) -> str | None:
        if self.bytes is None:
            return None
        size = float(self.bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return None

    def summary(self) -> str:
        """One line for a report. Always says these are estimates."""
        parts = []
        if self.rows is not None:
            # Thin-space grouping: 41 000 000 stays readable in a PR comment
            # where a comma could be mistaken for part of the value.
            parts.append(f"~{self.rows:,} rows".replace(",", " "))
        size = self.human_size()
        if size:
            parts.append(size)
        if self.indexes is not None:
            parts.append(f"{self.indexes} index(es)")
        if not parts:
            return f"{self.table}: no statistics"
        return f"{self.table}: " + ", ".join(parts) + " (estimated)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rows": self.rows,
            "bytes": self.bytes,
            "indexes": self.indexes,
            "isLarge": self.is_large,
            "isEmpty": self.is_empty,
        }


class StatsError(Exception):
    """Raised when a stats file cannot be used. Message is user-facing."""


def default_table_name(app: str, model: str) -> str:
    """Django's default: ``<app_label>_<modelname lowercased>``."""
    return f"{app}_{model.lower()}".lower()


def _unquote(raw: str) -> str:
    """``Meta`` values arrive as raw source text — ``'"custom"'`` → ``custom``."""
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


class ProductionStats:
    """Table statistics loaded from a file the operator produced."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.database: str = payload.get("database", "postgres")
        self.version: int | None = payload.get("version")
        self.generated_at: str | None = payload.get("generated_at")
        raw_tables = payload.get("tables") or {}
        if not isinstance(raw_tables, dict):
            raise StatsError("stats file: 'tables' must be an object")
        self._tables: dict[str, TableStats] = {}
        for name, body in raw_tables.items():
            if not isinstance(body, dict):
                raise StatsError(f"stats file: entry for {name!r} must be an object")
            self._tables[name.lower()] = TableStats(
                table=name,
                rows=body.get("rows"),
                bytes=body.get("bytes"),
                indexes=body.get("indexes"),
            )

    @classmethod
    def from_file(cls, path: str | Path) -> ProductionStats:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as e:
            raise StatsError(f"cannot read stats file {path}: {e}") from e
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise StatsError(f"stats file {path} is not valid JSON: {e}") from e
        if not isinstance(payload, dict):
            raise StatsError(f"stats file {path}: expected a JSON object at the top")
        return cls(payload)

    def __len__(self) -> int:
        return len(self._tables)

    def for_table(self, table: str) -> TableStats | None:
        return self._tables.get(table.lower())

    def for_model(
        self, app: str, model: str, meta: dict[str, str] | None = None
    ) -> TableStats | None:
        """Resolve a model to its table, honouring ``Meta.db_table``.

        Returns ``None`` when the table is absent from the stats file — which
        legitimately happens for a model production has never seen. Absence is
        not an error and must never be reported as zero rows.
        """
        if meta:
            explicit = meta.get("db_table")
            if explicit:
                return self.for_table(_unquote(explicit))
        return self.for_table(default_table_name(app, model))

    def describe(self) -> str:
        bits = [f"{len(self._tables)} table(s)"]
        if self.version:
            bits.append(f"PostgreSQL {self.version}")
        if self.generated_at:
            bits.append(f"collected {self.generated_at}")
        return ", ".join(bits)
