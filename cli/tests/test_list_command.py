"""Tests for the ``list`` subcommand."""

from __future__ import annotations

import json
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django_orm_lens.cli import main

MODELS_SOURCE = """from django.db import models


class Author(models.Model):
    name = models.CharField(max_length=100)


class Book(models.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)


class Tag(models.Model):
    label = models.CharField(max_length=50)
"""


def _write_hello_app(app_dir: Path) -> None:
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(MODELS_SOURCE, encoding="utf-8")
    for name in ("__init__.py", "admin.py", "apps.py", "views.py", "urls.py", "tests.py"):
        (app_dir / name).write_text("", encoding="utf-8")
    (app_dir / "migrations").mkdir(exist_ok=True)
    (app_dir / "migrations" / "__init__.py").write_text("", encoding="utf-8")


class ListCommandTest(unittest.TestCase):
    def test_default_text_output_is_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            _write_hello_app(Path(tmp) / "hello")
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["list", "--path", tmp])
            self.assertEqual(code, 0)
            lines = stdout.getvalue().splitlines()
            self.assertEqual(lines, ["hello.Author", "hello.Book", "hello.Tag"])

    def test_json_output_has_app_model_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            _write_hello_app(Path(tmp) / "hello")
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["list", "--format", "json", "--path", tmp])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload,
                [
                    {"app": "hello", "model": "Author"},
                    {"app": "hello", "model": "Book"},
                    {"app": "hello", "model": "Tag"},
                ],
            )

    def test_json_short_flag_works(self) -> None:
        with TemporaryDirectory() as tmp:
            _write_hello_app(Path(tmp) / "hello")
            with patch("sys.stdout", new=StringIO()) as stdout:
                code = main(["list", "-f", "json", "--path", tmp])
            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload), 3)
            self.assertEqual(payload[0], {"app": "hello", "model": "Author"})


if __name__ == "__main__":
    unittest.main()
