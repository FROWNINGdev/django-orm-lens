"""Data classes for parsed Django models.

Mirrors the TypeScript ``types.ts`` shape so the CLI and the VS Code
extension emit the same camelCase JSON schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RelationKind = Literal["ForeignKey", "ManyToManyField", "OneToOneField"]


@dataclass
class ParsedField:
    name: str
    type: str
    args: str
    is_relation: bool
    line_number: int
    related_model: str | None = None
    relation_kind: RelationKind | None = None
    on_delete: str | None = None
    related_name: str | None = None
    through_model: str | None = None

    def to_dict(self) -> dict:
        out = {
            "name": self.name,
            "type": self.type,
            "args": self.args,
            "isRelation": self.is_relation,
            "lineNumber": self.line_number,
        }
        if self.related_model is not None:
            out["relatedModel"] = self.related_model
        if self.relation_kind is not None:
            out["relationKind"] = self.relation_kind
        if self.on_delete is not None:
            out["onDelete"] = self.on_delete
        if self.related_name is not None:
            out["relatedName"] = self.related_name
        if self.through_model is not None:
            out["throughModel"] = self.through_model
        return out


@dataclass
class ParsedModel:
    name: str
    app_name: str
    file_path: str
    line_number: int
    base_classes: list[str]
    fields: list[ParsedField] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "appName": self.app_name,
            "filePath": self.file_path,
            "lineNumber": self.line_number,
            "baseClasses": list(self.base_classes),
            "fields": [f.to_dict() for f in self.fields],
            "meta": dict(self.meta),
        }


@dataclass
class ParsedApp:
    name: str
    path: str
    models: list[ParsedModel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "models": [m.to_dict() for m in self.models],
        }


@dataclass
class WorkspaceIndex:
    apps: list[ParsedApp] = field(default_factory=list)
    scanned_at: int = 0
    # Number of models.py-style files inspected in the scan that produced
    # this index — surfaced so ``--verbose`` can print a summary without a
    # second directory walk. Optional (default 0) for backward compat with
    # callers that build the index by hand in tests.
    scanned_files: int = 0

    def to_dict(self) -> dict:
        return {
            "apps": [a.to_dict() for a in self.apps],
            "scannedAt": self.scanned_at,
            "scannedFiles": self.scanned_files,
        }

    def total_models(self) -> int:
        return sum(len(a.models) for a in self.apps)


_USER_BASE_MARKERS = ("AbstractUser", "AbstractBaseUser")


def find_user_model(index: WorkspaceIndex) -> ParsedModel | None:
    """Return the workspace's Django User model, or ``None``.

    Heuristic: 1) first model whose bases include ``AbstractUser`` /
    ``AbstractBaseUser`` (dotted or bare); 2) fall back to any model named
    ``User``; 3) ``None`` if nothing matches. Used to resolve
    ``settings.AUTH_USER_MODEL`` references across parser/signals/query layers.
    """
    for app in index.apps:
        for m in app.models:
            for b in m.base_classes:
                if b.split(".")[-1] in _USER_BASE_MARKERS:
                    return m
    for app in index.apps:
        for m in app.models:
            if m.name == "User":
                return m
    return None


def find_user_model_from_dict(payload: dict) -> dict | None:
    """Same as :func:`find_user_model` but for a ``WorkspaceIndex.to_dict()``
    payload — returns the raw model dict, or ``None``."""
    apps = payload.get("apps") or []
    for app in apps:
        for m in app.get("models", []):
            for b in m.get("baseClasses", []) or []:
                if b.split(".")[-1] in _USER_BASE_MARKERS:
                    return m
    for app in apps:
        for m in app.get("models", []):
            if m.get("name") == "User":
                return m
    return None


def find_model(
    index: WorkspaceIndex, ref: str
) -> ParsedModel | None:
    """Look up a model in ``index`` by ``"app.Model"`` or bare ``"Model"``.

    Prefers a dotted match (unambiguous across apps); otherwise falls back
    to the first model with that class name. Returns ``None`` when nothing
    matches. Shared between the CLI and MCP server so lookup semantics stay
    consistent — a divergence used to silently return wrong results when the
    two lookup paths drifted.
    """
    if "." in ref:
        app_name, model_name = ref.split(".", 1)
        for app in index.apps:
            if app.name == app_name:
                for m in app.models:
                    if m.name == model_name:
                        return m
    for app in index.apps:
        for m in app.models:
            if m.name == ref:
                return m
    return None


def resolve_related_tail(
    related_model: str | None, user_model_name: str | None
) -> str | None:
    """Turn ``related_model`` into the target model name used by schema lookups.

    Substitutes ``settings.AUTH_USER_MODEL`` / bare ``AUTH_USER_MODEL`` with
    the workspace's actual User model name. Otherwise returns the last
    dotted segment (``"orders.Order"`` → ``"Order"``).
    """
    if not related_model:
        return related_model
    tail = related_model.rsplit(".", 1)[-1]
    if tail == "AUTH_USER_MODEL" and user_model_name:
        return user_model_name
    return tail


def cascade_preview(index: WorkspaceIndex, ref: str) -> dict[str, Any]:
    """Preview what ``<Model>.delete()`` does to the rest of the schema.

    Groups every inbound relation by its ``on_delete`` behaviour:
    ``cascade_kills`` (rows deleted with the target), ``set_null``
    (FK nulled/reset), ``protected`` (delete blocked by PROTECT/RESTRICT).
    Static source analysis — ``count_hint`` stays ``"unknown"`` because we
    never touch a database.

    Shared by the CLI ``cascade`` command and the MCP ``cascade_preview``
    tool so both surfaces answer identically. Returns an ``"error"`` key
    (instead of raising) when ``ref`` doesn't resolve, matching the
    analyzer-module convention.
    """
    m = find_model(index, ref)
    if m is None:
        return {"target": ref, "error": "model not found in workspace"}
    target_app = None
    for app in index.apps:
        if m in app.models:
            target_app = app.name
            break
    out: dict[str, Any] = {
        "target": f"{target_app}.{m.name}" if target_app else m.name,
        "cascade_kills": [],
        "set_null": [],
        "protected": [],
    }
    user_model = find_user_model(index)
    user_name = user_model.name if user_model is not None else None
    for app in index.apps:
        for other in app.models:
            if other is m:
                continue
            for f in other.fields:
                if not f.is_relation or not f.related_model:
                    continue
                if resolve_related_tail(f.related_model, user_name) != m.name:
                    continue
                on_delete = (f.on_delete or "").upper()
                entry = {
                    "model": f"{app.name}.{other.name}",
                    "via_field": f.name,
                }
                if on_delete == "CASCADE":
                    entry["count_hint"] = "unknown"
                    out["cascade_kills"].append(entry)
                elif on_delete in ("SET_NULL", "SET_DEFAULT", "SET"):
                    out["set_null"].append(entry)
                elif on_delete in ("PROTECT", "RESTRICT"):
                    out["protected"].append(entry)
    return out
