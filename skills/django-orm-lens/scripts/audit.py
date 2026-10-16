#!/usr/bin/env python3
"""One-shot Django audit with django-orm-lens.

Runs the four CLI analyzers (nplusone, migration-risk, drift, blast-radius)
and prints one JSON document:

    {"tool": {...}, "summary": {...}, "nplusone": [...],
     "migration_risk": {...}, "drift": {...}, "blast_radius": {...}}

Usage:
    python audit.py --path /abs/project/root
    python audit.py --path . --changed-since origin/main   # PR scope

Read-only: the analyzers parse source with the AST, never import the project
and never touch a database. Exit code is 0 unless the CLI cannot be found.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_cli() -> list[str] | None:
    """First working way to run django-orm-lens, as an argv prefix."""
    candidates: list[list[str]] = []
    if shutil.which("django-orm-lens"):
        candidates.append(["django-orm-lens"])
    if shutil.which("uvx"):
        # @latest: a bare `uvx django-orm-lens` can keep reusing an old cached release.
        candidates.append(["uvx", "django-orm-lens@latest"])
    if shutil.which("pipx"):
        candidates.append(["pipx", "run", "django-orm-lens"])
    candidates.append([sys.executable, "-m", "django_orm_lens"])
    for argv in candidates:
        try:
            out = subprocess.run(
                argv + ["--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and "django-orm-lens" in out.stdout:
            return argv
    return None


def run_json(cli: list[str], args: list[str]) -> object:
    out = subprocess.run(
        cli + args,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    text = out.stdout.strip()
    if not text:
        return {"error": "NO_OUTPUT", "stderr": out.stderr.strip()[-2000:]}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # "nothing to review" style messages are plain text, not an error.
        return {"message": text[-2000:]}


def changed_migrations(root: Path, base: str) -> list[str]:
    """Absolute paths of migration files changed since ``base`` (git)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )
    if out.returncode != 0:
        sys.exit(f"git diff failed: {out.stderr.strip()}")
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    ).stdout.strip()
    files = []
    for rel in out.stdout.splitlines():
        p = Path(rel)
        if "migrations" in p.parts and p.suffix == ".py" and p.name != "__init__.py":
            files.append(str((Path(top) / p).resolve()))
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--path", default=".", help="Django project root (holds manage.py)")
    ap.add_argument(
        "--changed-since",
        metavar="REF",
        help="limit migration checks to files changed since this git ref",
    )
    ap.add_argument(
        "--confidence",
        default="all",
        choices=["high", "medium", "all"],
        help="minimum N+1 confidence to include (default: all)",
    )
    opts = ap.parse_args()

    root = Path(opts.path).resolve()
    cli = find_cli()
    if cli is None:
        print(
            json.dumps(
                {
                    "error": "CLI_NOT_FOUND",
                    "hint": "pip install django-orm-lens  (or install uv / pipx)",
                }
            )
        )
        return 2

    base = ["--path", str(root), "--format", "json"]
    only: list[str] = []
    scope = "workspace"
    if opts.changed_since:
        files = changed_migrations(root, opts.changed_since)
        scope = f"changed since {opts.changed_since}: {len(files)} migration file(s)"
        for f in files:
            only += ["--only", f]

    nplusone = run_json(
        cli, ["nplusone", *base, "--confidence", opts.confidence, "--exit-zero"]
    )
    risk = run_json(cli, ["migration-risk", *base, "--severity", "all", "--exit-zero"])
    drift = run_json(cli, ["drift", *base, "--exit-zero"])
    if opts.changed_since and not only:
        blast: object = {"message": "no migration files changed — nothing to review"}
    else:
        blast = run_json(
            cli, ["blast-radius", *base, "--severity", "all", *only, "--exit-zero"]
        )

    risks = risk.get("findings", []) if isinstance(risk, dict) else []
    if opts.changed_since:
        wanted = {Path(f) for f in only[1::2]}
        risks = [
            r
            for r in risks
            if (root / r.get("filePath", "")).resolve() in wanted
            or Path(r.get("filePath", "")).resolve() in wanted
        ]
        if isinstance(risk, dict):
            risk = {**risk, "findings": risks}

    def count(sev: str) -> int:
        return sum(1 for r in risks if r.get("severity") == sev)

    def summary_of(doc: object) -> dict:
        s = doc.get("summary") if isinstance(doc, dict) else None
        return s if isinstance(s, dict) else {}

    drift_summary = summary_of(drift)
    blast_summary = summary_of(blast)
    n1: list[dict] = (
        [f for f in nplusone if isinstance(f, dict)]
        if isinstance(nplusone, list)
        else []
    )
    blocking = count("critical") + int(drift_summary.get("blocking", 0) or 0)

    summary = {
        "verdict": "BLOCK"
        if blocking
        else ("FIX BEFORE DEPLOY" if count("warning") else "SHIP"),
        "scope": scope,
        "nplusone": {
            "total": len(n1),
            "high": sum(1 for f in n1 if f.get("confidence") == "high"),
        },
        "migration_risk": {
            "critical": count("critical"),
            "warning": count("warning"),
            "info": count("info"),
        },
        "drift": {
            "drifted_models": drift_summary.get("drifted", 0),
            "blocking": drift_summary.get("blocking", 0),
            "migrations_replayed": drift_summary.get("migrations", 0),
        },
        "blast_radius": {
            "targets": blast_summary.get("targets", 0),
            "certain_references": blast_summary.get("certainReferences", 0),
        },
        "note": "N+1 findings do not affect the verdict; the verdict is about deploy safety.",
    }
    version = subprocess.run(
        cli + ["--version"], capture_output=True, check=False, text=True
    ).stdout.strip()
    print(
        json.dumps(
            {
                "tool": {"cli": " ".join(cli), "version": version, "root": str(root)},
                "summary": summary,
                "nplusone": nplusone,
                "migration_risk": risk,
                "drift": drift,
                "blast_radius": blast,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
