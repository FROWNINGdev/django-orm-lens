"""Schema diff — compare two ``django-orm-lens`` JSON dumps.

Pure stdlib. Takes two dicts in the shape produced by
``WorkspaceIndex.to_dict()`` (i.e. what ``scan --format=json`` or
``list --format=json`` write) and reports what changed at the model,
field, and relation level.

Intended as a code-review aid: run ``list --format=json`` on the main
branch, again on the PR branch, then ``diff before.json after.json`` to
see the model delta at a glance.

The output data model is intentionally flat and JSON-friendly. Nothing
here reaches back into the parser — the diff only sees the serialised
schema, so it can be run in CI without the source tree.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Tuple

# Field attributes that are treated as "constraints" for change detection.
# ``lineNumber`` is deliberately excluded — moving a field up or down in a
# ``models.py`` is not a schema change.
_CONSTRAINT_KEYS: Tuple[str, ...] = (
    "type",
    "args",
    "onDelete",
    "relatedName",
    "throughModel",
)

# Attributes that identify a relation target — used to detect "the same
# relation now points somewhere else".
_RELATION_TARGET_KEYS: Tuple[str, ...] = (
    "relatedModel",
    "relationKind",
    "onDelete",
    "throughModel",
    "relatedName",
)


@dataclass
class FieldChange:
    """One field whose constraints/type changed between old and new."""

    model: str
    name: str
    changes: Dict[str, Dict[str, Any]]

    def to_dict(self) -> dict:
        return {"model": self.model, "name": self.name, "changes": self.changes}


@dataclass
class RelationChange:
    """One relation whose target/kind/on_delete changed."""

    model: str
    name: str
    changes: Dict[str, Dict[str, Any]]

    def to_dict(self) -> dict:
        return {"model": self.model, "name": self.name, "changes": self.changes}


@dataclass
class ModelFieldRef:
    """A scalar field belonging to a model — used for add/remove lists."""

    model: str
    name: str
    type: str

    def to_dict(self) -> dict:
        return {"model": self.model, "name": self.name, "type": self.type}


@dataclass
class ModelRelationRef:
    """A relation field belonging to a model — used for add/remove lists."""

    model: str
    name: str
    kind: str
    target: str

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "name": self.name,
            "kind": self.kind,
            "target": self.target,
        }


@dataclass
class DiffResult:
    """The full delta between two schema dumps."""

    added_models: List[str] = field(default_factory=list)
    removed_models: List[str] = field(default_factory=list)
    added_fields: List[ModelFieldRef] = field(default_factory=list)
    removed_fields: List[ModelFieldRef] = field(default_factory=list)
    changed_fields: List[FieldChange] = field(default_factory=list)
    added_relations: List[ModelRelationRef] = field(default_factory=list)
    removed_relations: List[ModelRelationRef] = field(default_factory=list)
    changed_relations: List[RelationChange] = field(default_factory=list)

    def is_empty(self) -> bool:
        """True when the two schemas are functionally identical."""
        return not any(
            (
                self.added_models,
                self.removed_models,
                self.added_fields,
                self.removed_fields,
                self.changed_fields,
                self.added_relations,
                self.removed_relations,
                self.changed_relations,
            )
        )

    def to_dict(self) -> dict:
        return {
            "addedModels": list(self.added_models),
            "removedModels": list(self.removed_models),
            "addedFields": [f.to_dict() for f in self.added_fields],
            "removedFields": [f.to_dict() for f in self.removed_fields],
            "changedFields": [f.to_dict() for f in self.changed_fields],
            "addedRelations": [r.to_dict() for r in self.added_relations],
            "removedRelations": [r.to_dict() for r in self.removed_relations],
            "changedRelations": [r.to_dict() for r in self.changed_relations],
        }


def _index_models(schema: dict) -> Dict[str, dict]:
    """Flatten ``{apps: [{name, models: [...]}, ...]}`` to ``{app.Model: model_dict}``.

    ``schema`` accepts either the full workspace dump or a bare
    ``{"apps": [...]}`` payload. Unknown shapes yield an empty index rather
    than raising — the diff is deliberately forgiving so ``diff`` on an
    unrelated JSON file surfaces as "everything removed" instead of a
    traceback.
    """
    out: Dict[str, dict] = {}
    apps = schema.get("apps") if isinstance(schema, dict) else None
    if not isinstance(apps, list):
        return out
    for app in apps:
        if not isinstance(app, dict):
            continue
        app_name = app.get("name") or ""
        for m in app.get("models", []) or []:
            if not isinstance(m, dict):
                continue
            model_name = m.get("name") or ""
            key = f"{app_name}.{model_name}" if app_name else model_name
            out[key] = m
    return out


def _split_fields(model: dict) -> Tuple[Dict[str, dict], Dict[str, dict]]:
    """Return ``(scalars_by_name, relations_by_name)`` for a model dict."""
    scalars: Dict[str, dict] = {}
    relations: Dict[str, dict] = {}
    for f in model.get("fields", []) or []:
        if not isinstance(f, dict):
            continue
        name = f.get("name") or ""
        if f.get("isRelation"):
            relations[name] = f
        else:
            scalars[name] = f
    return scalars, relations


def _delta(old: dict, new: dict, keys: Tuple[str, ...]) -> Dict[str, Dict[str, Any]]:
    """Return ``{key: {"old": ..., "new": ...}}`` for each key that differs."""
    out: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        ov = old.get(k)
        nv = new.get(k)
        if ov != nv:
            out[k] = {"old": ov, "new": nv}
    return out


def diff_schemas(old: dict, new: dict) -> DiffResult:
    """Compute the delta between two ``WorkspaceIndex.to_dict()`` payloads.

    Both inputs are treated as read-only. Models are matched by
    ``app.Model`` key; fields and relations are matched by name inside
    the containing model. Fields present in one side and absent from the
    other are reported as added/removed — this tool does not attempt to
    detect renames (that requires heuristics the caller may not want).
    """
    result = DiffResult()

    old_models = _index_models(old)
    new_models = _index_models(new)

    added_keys = sorted(set(new_models) - set(old_models))
    removed_keys = sorted(set(old_models) - set(new_models))
    common_keys = sorted(set(old_models) & set(new_models))

    result.added_models = added_keys
    result.removed_models = removed_keys

    for key in common_keys:
        old_scalars, old_relations = _split_fields(old_models[key])
        new_scalars, new_relations = _split_fields(new_models[key])

        for name in sorted(set(new_scalars) - set(old_scalars)):
            f = new_scalars[name]
            result.added_fields.append(
                ModelFieldRef(model=key, name=name, type=str(f.get("type", "")))
            )
        for name in sorted(set(old_scalars) - set(new_scalars)):
            f = old_scalars[name]
            result.removed_fields.append(
                ModelFieldRef(model=key, name=name, type=str(f.get("type", "")))
            )
        for name in sorted(set(old_scalars) & set(new_scalars)):
            delta = _delta(old_scalars[name], new_scalars[name], _CONSTRAINT_KEYS)
            if delta:
                result.changed_fields.append(
                    FieldChange(model=key, name=name, changes=delta)
                )

        for name in sorted(set(new_relations) - set(old_relations)):
            f = new_relations[name]
            result.added_relations.append(
                ModelRelationRef(
                    model=key,
                    name=name,
                    kind=str(f.get("relationKind", "")),
                    target=str(f.get("relatedModel", "")),
                )
            )
        for name in sorted(set(old_relations) - set(new_relations)):
            f = old_relations[name]
            result.removed_relations.append(
                ModelRelationRef(
                    model=key,
                    name=name,
                    kind=str(f.get("relationKind", "")),
                    target=str(f.get("relatedModel", "")),
                )
            )
        for name in sorted(set(old_relations) & set(new_relations)):
            delta = _delta(
                old_relations[name], new_relations[name], _RELATION_TARGET_KEYS
            )
            if delta:
                result.changed_relations.append(
                    RelationChange(model=key, name=name, changes=delta)
                )

    return result


def format_diff(result: DiffResult, fmt: str = "text") -> str:
    """Render a :class:`DiffResult` as either human-readable text or JSON."""
    fmt = fmt.lower()
    if fmt == "json":
        return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    if fmt == "text":
        return _diff_text(result)
    raise ValueError(f"Unknown format: {fmt!r}. Use text | json.")


def _diff_text(result: DiffResult) -> str:
    if result.is_empty():
        return "No schema changes."

    lines: List[str] = []

    def section(title: str) -> None:
        if lines:
            lines.append("")
        lines.append(title)

    if result.added_models:
        section("Added models:")
        for name in result.added_models:
            lines.append(f"  + {name}")
    if result.removed_models:
        section("Removed models:")
        for name in result.removed_models:
            lines.append(f"  - {name}")

    if result.added_fields:
        section("Added fields:")
        for f in result.added_fields:
            lines.append(f"  + {f.model}.{f.name}: {f.type}")
    if result.removed_fields:
        section("Removed fields:")
        for f in result.removed_fields:
            lines.append(f"  - {f.model}.{f.name}: {f.type}")
    if result.changed_fields:
        section("Changed fields:")
        for c in result.changed_fields:
            lines.append(f"  ~ {c.model}.{c.name}")
            for key, delta in c.changes.items():
                lines.append(f"      {key}: {delta['old']!r} -> {delta['new']!r}")

    if result.added_relations:
        section("Added relations:")
        for r in result.added_relations:
            lines.append(f"  + {r.model}.{r.name} -> {r.target} ({r.kind})")
    if result.removed_relations:
        section("Removed relations:")
        for r in result.removed_relations:
            lines.append(f"  - {r.model}.{r.name} -> {r.target} ({r.kind})")
    if result.changed_relations:
        section("Changed relations:")
        for c in result.changed_relations:
            lines.append(f"  ~ {c.model}.{c.name}")
            for key, delta in c.changes.items():
                lines.append(f"      {key}: {delta['old']!r} -> {delta['new']!r}")

    return "\n".join(lines)


# ``asdict`` is re-exported so tests can round-trip a DiffResult without
# depending on our to_dict shape if they'd rather compare raw dataclass state.
__all__ = [
    "DiffResult",
    "FieldChange",
    "RelationChange",
    "ModelFieldRef",
    "ModelRelationRef",
    "diff_schemas",
    "format_diff",
    "asdict",
]
