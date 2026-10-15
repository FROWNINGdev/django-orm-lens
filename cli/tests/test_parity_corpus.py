"""Corpus parity — the TypeScript and Python parsers must agree on real code.

``test_parity.py`` pins one hand-written fixture. This runs both parsers over
every ``models.py`` in the repo's fixtures — including the golden Django
projects (saleor, wagtail, zulip, ...) — and compares the structural shape:
model names, base classes, and each field's type and relation attributes.

The TypeScript side is the compiled ``out/`` build (``npm run build``); the
test skips when Node or that build is absent so the Python suite stays
runnable on its own.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from orm_synapse.parser import parse_models_file

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "cli" / "tests" / "fixtures"
OUT_PARSER = REPO_ROOT / "out" / "modelParse.js"

NODE_DUMP = r"""
const Module = require('node:module');
const orig = Module._load;
Module._load = function (r, ...a) { return r === 'vscode' ? {} : orig.call(this, r, ...a); };
const fs = require('node:fs');
const { parseModelsFile } = require(process.argv[1]);
const out = {};
for (const f of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  out[f] = parseModelsFile(f, fs.readFileSync(f, 'utf8')).map((m) => [
    m.name,
    m.baseClasses,
    m.fields.map((x) => [x.name, x.type, x.relatedModel ?? null, x.relationKind ?? null,
      x.onDelete ?? null, x.relatedName ?? null, x.throughModel ?? null]),
  ]);
}
process.stdout.write(JSON.stringify(out));
"""


def _corpus() -> list[Path]:
    files = sorted(FIXTURES.rglob("models.py"))
    files.append(REPO_ROOT / "test" / "fixtures" / "parity_input.py")
    return files


def _python_shape(path: Path) -> list:
    models = parse_models_file(str(path), path.read_text(encoding="utf-8"))
    return [
        [
            m.name,
            list(m.base_classes),
            [
                [f.name, f.type, f.related_model, f.relation_kind,
                 f.on_delete, f.related_name, f.through_model]
                for f in m.fields
            ],
        ]
        for m in models
    ]


@unittest.skipUnless(shutil.which("node") and OUT_PARSER.exists(),
                     "needs node and a built out/ (npm run build)")
class CorpusParityTest(unittest.TestCase):
    def test_parsers_agree_on_every_fixture(self) -> None:
        files = _corpus()
        proc = subprocess.run(
            ["node", "-e", NODE_DUMP, str(OUT_PARSER)],
            input=json.dumps([str(f) for f in files]),
            capture_output=True, text=True, check=True,
        )
        ts_shapes = json.loads(proc.stdout)
        for path in files:
            with self.subTest(file=str(path.relative_to(REPO_ROOT))):
                self.assertEqual(ts_shapes[str(path)], _python_shape(path))


if __name__ == "__main__":
    unittest.main()
