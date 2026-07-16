"""Regression test for #12: friendlier error when no models.py is found.

`scan --path <empty dir>` used to print an empty apps list with no signal
that the tool actually ran. It now emits a "hint: no models.py found under
<path>" line to stderr (stdout stays clean for piping, exit code stays 0),
suppressible with ``--quiet``. The hint must NOT fire when a models.py *was*
walked but simply defined zero Django model classes — that's a different
situation (models.py seen, just nothing in it) from "no models.py at all".
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.cli import main


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exit_code = main(argv)
    return exit_code, out.getvalue(), err.getvalue()


class NoModelsHintTest(unittest.TestCase):
    def test_hint_printed_to_stderr_on_empty_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            exit_code, out, err = _run(["scan", "--path", tmp])

            self.assertEqual(exit_code, 0)
            self.assertIn('"apps": []', out)
            self.assertIn(f"hint: no models.py found under {tmp}", err)
            self.assertIn("--exclude to whitelist non-standard layouts", err)

    def test_quiet_suppresses_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            exit_code, out, err = _run(["scan", "--path", tmp, "--quiet"])

            self.assertEqual(exit_code, 0)
            self.assertIn('"apps": []', out)
            self.assertEqual(err, "")

    def test_hint_not_printed_when_models_py_seen_but_empty_of_models(self) -> None:
        with TemporaryDirectory() as tmp:
            app = Path(tmp) / "hello"
            app.mkdir()
            # A real models.py that was walked but defines no Django model
            # classes — this is NOT the "no models.py found" situation.
            (app / "models.py").write_text(
                "class NotAModel:\n    pass\n", encoding="utf-8"
            )

            exit_code, out, err = _run(["scan", "--path", tmp])

            self.assertEqual(exit_code, 0)
            self.assertIn('"apps": []', out)
            self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
