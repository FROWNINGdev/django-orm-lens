"""Tests for the optional production-statistics input (django_orm_lens/stats.py).

The contract this file guards is mostly about honesty: a missing table means
"unknown", never "empty"; every rendered number says it is an estimate; and
the shipped query only ever reads.

Run: python -m unittest discover cli/tests -v
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from django_orm_lens.blast_radius import (
    analyze_blast_radius,
    format_markdown,
    format_text,
)
from django_orm_lens.parser import scan_workspace
from django_orm_lens.stats import (
    STATS_QUERY,
    ProductionStats,
    StatsError,
    TableStats,
    default_table_name,
)

FIXTURE = Path(__file__).parent / "fixtures" / "blast_radius"

PAYLOAD = {
    "database": "postgres",
    "version": 15,
    "generated_at": "2026-07-28T22:00:00Z",
    "tables": {
        "blog_post": {"rows": 41_000_000, "bytes": 12_884_901_888, "indexes": 4},
        "blog_tag": {"rows": 0, "bytes": 8192, "indexes": 1},
        "custom_posts": {"rows": 7, "bytes": 16384, "indexes": 2},
    },
}


class TempFileMixin(unittest.TestCase):
    """Gives each test a scratch directory that cleans itself up."""

    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self._dir = Path(td.name)
        self._seq = 0

    def _write_text(self, text: str) -> str:
        self._seq += 1
        path = self._dir / f"stats_{self._seq}.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _write(self, payload: object) -> str:
        return self._write_text(json.dumps(payload))


class StatsQueryTest(unittest.TestCase):
    def test_query_is_read_only(self) -> None:
        # The whole premise is that an operator can run this against
        # production without thinking twice.
        lowered = STATS_QUERY.lower()
        for forbidden in (
            "insert",
            "update ",
            "delete",
            "drop",
            "alter",
            "create",
            "truncate",
            "grant",
        ):
            self.assertNotIn(
                forbidden, lowered, f"query must not contain {forbidden!r}"
            )

    def test_query_reads_only_the_catalog(self) -> None:
        self.assertIn("pg_stat_user_tables", STATS_QUERY)
        self.assertIn("pg_total_relation_size", STATS_QUERY)

    def test_query_survives_a_database_with_no_user_tables(self) -> None:
        # json_object_agg over zero rows is NULL; the coalesce keeps the
        # output a valid object instead of a bare null.
        self.assertIn("coalesce", STATS_QUERY.lower())


class LoadingTest(TempFileMixin):
    def test_loads_a_well_formed_file(self) -> None:
        stats = ProductionStats.from_file(self._write(PAYLOAD))
        self.assertEqual(len(stats), 3)
        self.assertEqual(stats.version, 15)
        self.assertIn("PostgreSQL 15", stats.describe())

    def test_missing_file_raises_a_usable_message(self) -> None:
        with self.assertRaises(StatsError) as ctx:
            ProductionStats.from_file("no/such/stats.json")
        self.assertIn("cannot read stats file", str(ctx.exception))

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(StatsError) as ctx:
            ProductionStats.from_file(self._write_text("{not json"))
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_top_level_array_raises(self) -> None:
        with self.assertRaises(StatsError):
            ProductionStats.from_file(self._write([1, 2, 3]))

    def test_tables_must_be_an_object(self) -> None:
        with self.assertRaises(StatsError):
            ProductionStats.from_file(self._write({"tables": ["blog_post"]}))

    def test_table_entry_must_be_an_object(self) -> None:
        with self.assertRaises(StatsError):
            ProductionStats.from_file(self._write({"tables": {"blog_post": 41}}))

    def test_empty_tables_object_is_valid(self) -> None:
        stats = ProductionStats.from_file(self._write({"tables": {}}))
        self.assertEqual(len(stats), 0)


class ResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stats = ProductionStats(PAYLOAD)

    def test_default_table_name_follows_django(self) -> None:
        self.assertEqual(default_table_name("blog", "Post"), "blog_post")
        self.assertEqual(default_table_name("Blog", "POST"), "blog_post")

    def test_resolves_by_django_default(self) -> None:
        found = self.stats.for_model("blog", "Post")
        self.assertIsNotNone(found)
        self.assertEqual(found.rows, 41_000_000)

    def test_meta_db_table_wins_and_is_unquoted(self) -> None:
        # The parser hands Meta values over as raw source text.
        found = self.stats.for_model("blog", "Post", {"db_table": '"custom_posts"'})
        self.assertIsNotNone(found)
        self.assertEqual(found.rows, 7)
        single = self.stats.for_model("blog", "Post", {"db_table": "'custom_posts'"})
        self.assertEqual(single.rows, 7)

    def test_unrelated_meta_keys_are_ignored(self) -> None:
        found = self.stats.for_model("blog", "Post", {"ordering": '["title"]'})
        self.assertEqual(found.rows, 41_000_000)

    def test_unknown_table_is_none_not_zero(self) -> None:
        # The distinction that matters: a table production has never seen is
        # unknown, and must never be rendered as "0 rows".
        self.assertIsNone(self.stats.for_model("shop", "Order"))


class TableStatsTest(unittest.TestCase):
    def test_large_and_empty_flags(self) -> None:
        self.assertTrue(TableStats("t", rows=1_000_000).is_large)
        self.assertFalse(TableStats("t", rows=999_999).is_large)
        self.assertTrue(TableStats("t", rows=0).is_empty)
        self.assertFalse(TableStats("t", rows=None).is_empty)
        self.assertFalse(TableStats("t", rows=None).is_large)

    def test_human_size_scales(self) -> None:
        self.assertEqual(TableStats("t", bytes=512).human_size(), "512 B")
        self.assertEqual(TableStats("t", bytes=1536).human_size(), "1.5 KB")
        self.assertEqual(TableStats("t", bytes=12_884_901_888).human_size(), "12.0 GB")
        self.assertIsNone(TableStats("t").human_size())

    def test_summary_always_marks_the_numbers_as_estimates(self) -> None:
        s = TableStats("blog_post", rows=41_000_000, bytes=1024, indexes=4).summary()
        self.assertIn("estimated", s)
        self.assertIn("~41 000 000 rows", s)

    def test_summary_without_any_numbers(self) -> None:
        self.assertIn("no statistics", TableStats("blog_post").summary())


class IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.index = scan_workspace(str(FIXTURE))
        self.stats = ProductionStats(PAYLOAD)

    def test_target_carries_table_stats(self) -> None:
        report = analyze_blast_radius(FIXTURE, index=self.index, stats=self.stats)
        target = report.targets[0]
        self.assertIsNotNone(target.table_stats)
        self.assertEqual(target.table_stats.rows, 41_000_000)
        self.assertTrue(target.to_dict()["tableStats"]["isLarge"])

    def test_no_stats_leaves_the_field_absent(self) -> None:
        report = analyze_blast_radius(FIXTURE, index=self.index)
        self.assertIsNone(report.targets[0].table_stats)
        self.assertIsNone(report.targets[0].to_dict()["tableStats"])

    def test_unknown_table_leaves_it_absent_rather_than_zero(self) -> None:
        empty = ProductionStats({"tables": {}})
        report = analyze_blast_radius(FIXTURE, index=self.index, stats=empty)
        self.assertIsNone(report.targets[0].table_stats)

    def test_cascade_flag_is_independent_of_the_index(self) -> None:
        # --stats needs the index to read Meta.db_table; that must not
        # silently switch cascade previews back on.
        report = analyze_blast_radius(
            FIXTURE, index=self.index, stats=self.stats, cascade=False
        )
        self.assertIsNone(report.targets[0].cascade)
        self.assertIsNotNone(report.targets[0].table_stats)

    def test_renderers_show_the_row_count(self) -> None:
        report = analyze_blast_radius(FIXTURE, index=self.index, stats=self.stats)
        text = format_text(report, FIXTURE)
        self.assertIn("~41 000 000 rows", text)
        self.assertIn("estimated", text)
        md = format_markdown(report, FIXTURE)
        self.assertIn("~41 000 000 rows", md)
        self.assertIn("locks a large table", md)


if __name__ == "__main__":
    unittest.main()
