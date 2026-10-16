"""Pin JSON/text line numbering without a database or network."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django_orm_lens.cli import main
from django_orm_lens.impact import scan_file_text


class ImpactLineContractTest(unittest.TestCase):
    def test_serialized_lines_are_one_based_columns_remain_zero_based(self):
        for separator in ("\n", "\r\n"):
            with self.subTest(separator=separator):
                text = separator * 20 + "value = post.title" + separator
                found = scan_file_text("blog/views.py", text, "title")
                self.assertEqual(found[0].to_dict()["line"], 21)
                self.assertEqual(found[0].to_dict()["column"], 13)
        first = scan_file_text("blog/views.py", "title = 1\n", "title")
        self.assertEqual(first[0].to_dict()["line"], 1)
        self.assertEqual(first[0].to_dict()["column"], 0)

    def test_cli_json_and_text_agree_on_line_21(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "blog" / "views.py"
            path.parent.mkdir()
            path.write_text("\n" * 20 + "value = post.title\n", encoding="utf-8")
            outputs = {}
            for fmt in ("json", "text"):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(["impact", "title", "--path", tmp, "--format", fmt])
                self.assertEqual(code, 0)
                outputs[fmt] = out.getvalue()
            self.assertEqual(json.loads(outputs["json"])["findings"][0]["line"], 21)
            self.assertIn("blog/views.py:21 ", outputs["text"])
            self.assertNotIn("blog/views.py:22 ", outputs["text"])
