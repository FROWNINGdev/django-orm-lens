"""Data classes for parsed Django models.

Mirrors the TypeScript ``types.ts`` shape so the CLI and the VS Code
extension emit the same camelCase JSON schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

RelationKind = Literal["ForeignKey", "ManyToManyField", "OneToOneField"]


@dataclass
class ParsedField:
    name: str
    type: str
    args: str
    is_relation: bool
    line_number: int
    related_model: Optional[str] = None
    relation_kind: Optional[RelationKind] = None

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
        return out


@dataclass
class ParsedModel:
    name: str
    app_name: str
    file_path: str
    line_number: int
    base_classes: List[str]
    fields: List[ParsedField] = field(default_factory=list)
    meta: Dict[str, str] = field(default_factory=dict)

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
    models: List[ParsedModel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "models": [m.to_dict() for m in self.models],
        }


@dataclass
class WorkspaceIndex:
    apps: List[ParsedApp] = field(default_factory=list)
    scanned_at: int = 0

    def to_dict(self) -> dict:
        return {
            "apps": [a.to_dict() for a in self.apps],
            "scannedAt": self.scanned_at,
        }

    def total_models(self) -> int:
        return sum(len(a.models) for a in self.apps)
