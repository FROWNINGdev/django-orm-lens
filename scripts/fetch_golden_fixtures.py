"""Fetch models.py files from real-world Django projects for golden test suite.

Uses `gh api` (which handles auth + rate limits) to download raw content, writes
files into cli/tests/fixtures/golden/<project>/<original-path>. Idempotent.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "cli" / "tests" / "fixtures" / "golden"

# Selection tuned so combined vendored size stays <500 KB.
PROJECTS = {
    "zulip": {
        "repo": "zulip/zulip",
        "ref": "main",
        "paths": [
            "zerver/models/__init__.py",
            "zerver/models/realms.py",
            "zerver/models/users.py",
            "zerver/models/messages.py",
            "zerver/models/streams.py",
            "zerver/models/realm_audit_logs.py",
        ],
    },
    "saleor": {
        "repo": "saleor/saleor",
        "ref": "main",
        "paths": [
            "saleor/product/models.py",
            "saleor/order/models.py",
            "saleor/discount/models.py",
            "saleor/warehouse/models.py",
        ],
    },
    "wagtail": {
        "repo": "wagtail/wagtail",
        "ref": "main",
        "paths": [
            "wagtail/models/__init__.py",
            "wagtail/models/pages.py",
            "wagtail/models/sites.py",
        ],
    },
    "django-cms": {
        "repo": "django-cms/django-cms",
        "ref": "main",
        "paths": [
            "cms/models/__init__.py",
            "cms/models/pagemodel.py",
            "cms/models/placeholdermodel.py",
            "cms/models/pluginmodel.py",
        ],
    },
}


def fetch(repo: str, ref: str, path: str) -> bytes:
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    return base64.b64decode(payload["content"])


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    for project, cfg in PROJECTS.items():
        for path in cfg["paths"]:
            dest = FIXTURES / project / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = fetch(cfg["repo"], cfg["ref"], path)
            dest.write_bytes(data)
            total_bytes += len(data)
            print(f"[{project}] {path} -> {len(data):,} B")
    print(f"\nTotal: {total_bytes:,} B ({total_bytes / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
