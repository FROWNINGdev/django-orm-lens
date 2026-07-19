"""Tests for the ``--verbose``/``-v`` scan-timing summary (issue #14).

``-v`` is opt-in per scan-backed subcommand via ``_add_scan_flags``. It must:

* print a one-line ``scanned N files in Tms, found A apps / M models``
  summary to stderr after the scan;
* never touch stdout — piping stays byte-for-byte identical whether or not
  ``-v`` is passed;
* print nothing at all when the flag is absent.

The exact millisecond value is timing-dependent and not asserted — only the
shape/presence of the message, per the counts the scan actually produced.
"""

from __future__ import annotations

import io
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.cli import main

MODELS_SOURCE = """from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
"""

VERBOSE_RE = re.compile(r"^scanned \d+ files in \d+ms, found \d+ apps / \d+ models$")


def _write_hello_app(app_dir: Path) -> None:
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(MODELS_SOURCE, encoding="utf-8")


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


class VerboseScanFlagTest(unittest.TestCase):
    def test_verbose_prints_summary_to_stderr(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            rc, out, err = _run(["scan", "-v", "--path", str(app)])
            self.assertEqual(rc, 0)
            stderr_lines = [ln for ln in err.splitlines() if ln.strip()]
            self.assertEqual(len(stderr_lines), 1)
            self.assertRegex(stderr_lines[0], VERBOSE_RE)
            self.assertIn("scanned 1 files in", stderr_lines[0])
            self.assertIn("found 1 apps / 2 models", stderr_lines[0])

    def test_verbose_long_flag_form_also_works(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            rc, out, err = _run(["scan", "--verbose", "--path", str(app)])
            self.assertEqual(rc, 0)
            self.assertRegex(err.strip(), VERBOSE_RE)

    def test_verbose_does_not_alter_stdout(self) -> None:
        """`list` output has no embedded timestamp, so it's safe to compare
        byte-for-byte between a verbose and a non-verbose run — this is the
        piping guarantee the issue asks for.
        """
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            _, out_plain, err_plain = _run(["list", "--path", str(app)])
            _, out_verbose, err_verbose = _run(["list", "-v", "--path", str(app)])
            self.assertEqual(out_plain, out_verbose)
            self.assertEqual(err_plain, "")
            self.assertRegex(err_verbose.strip(), VERBOSE_RE)

    def test_no_verbose_flag_prints_nothing_to_stderr(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            _write_hello_app(app)
            rc, out, err = _run(["scan", "--path", str(app)])
            self.assertEqual(rc, 0)
            self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
