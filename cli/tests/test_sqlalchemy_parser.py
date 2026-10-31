"""SQLAlchemy models: declarative styles, inheritance, and their place in the index.

The census ran over Superset, Airflow, Prefect, Polar, Dispatch, Mealie, CTFd,
Redash and the FastAPI full-stack template. Several cases below come from it:
aliased abstract bases in files with no SQLAlchemy in them (Superset), a
``declared_attr`` table-name rule on the base (Prefect), PEP 758 ``except``
clauses (Polar) and relationships whose direction only ``foreign_keys=``
tells (CTFd).
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from orm_lens.cli import _build_mermaid, main
from orm_lens.er_formats import build_dbml
from orm_lens.models import ParsedApp, WorkspaceIndex
from orm_lens.parser import scan_workspace
from orm_lens.sqlalchemy_parser import (
    declares_sqlalchemy,
    is_sqlalchemy_only_source,
    parse_source,
    parse_sqlalchemy_sources,
    scan_sqlalchemy_models,
)
from orm_lens.workspace import clear_cache, resolve_workspace


def _models(*files: tuple[str, str]) -> dict:
    return {m.name: m for m in parse_sqlalchemy_sources(list(files))}


def _fields(model) -> dict:
    return {f.name: f for f in model.all_fields()}


def _rels(model) -> dict:
    return {r.name: r for r in model.relationships}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


MODERN = '''
from typing import List, Optional

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("user_account.id"), primary_key=True),
    Column("role_id", ForeignKey("role.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    fullname: Mapped[Optional[str]]
    addresses: Mapped[List["Address"]] = relationship(back_populates="user")
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")


class Address(Base):
    __tablename__ = "address"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    user: Mapped["User"] = relationship(back_populates="addresses")


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(primary_key=True)
    users: Mapped[list[User]] = relationship(
        secondary=user_roles, back_populates="roles", lazy="selectin"
    )
'''


def test_modern_declarative_columns_keys_and_relationships() -> None:
    models = _models(("app/models.py", MODERN))
    assert set(models) == {"User", "Address", "Role"}  # Base is not a table
    user, address = models["User"], models["Address"]
    assert user.orm == "sqlalchemy" and user.table_name == "user_account"
    cols = _fields(user)
    assert cols["id"].type == "Integer" and "primary_key=True" in cols["id"].args
    assert cols["name"].type == "String"
    assert cols["fullname"].type == "String"  # Mapped[Optional[str]], no mapped_column
    fk = _fields(address)["user_id"]
    assert (fk.is_relation, fk.relation_kind, fk.related_model, fk.on_delete) == (
        True, "ForeignKey", "User", "CASCADE"
    )
    rels = _rels(user)
    assert rels["addresses"].target == "Address" and rels["addresses"].collection is True
    assert rels["addresses"].lazy == "select"
    assert _rels(address)["user"].collection is False
    assert _rels(models["Role"])["users"].lazy == "selectin"


def test_many_to_many_is_one_field_through_the_association_table() -> None:
    models = _models(("app/models.py", MODERN))
    m2m = [
        (m.name, f.name, f.through_model)
        for m in models.values()
        for f in m.fields
        if f.relation_kind == "ManyToManyField"
    ]
    # Declared on both sides with back_populates, drawn once.
    assert m2m == [("User", "roles", "user_roles")]
    assert _rels(models["User"])["roles"].secondary == "user_roles"
    # A relationship is never a column.
    assert "addresses" not in _fields(models["User"])


def test_legacy_declarative_base_column_style_and_backref() -> None:
    src = '''
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column("user_name", String(50), nullable=False)
    addresses = relationship("Address", backref="user", lazy="dynamic")


class Address(Base):
    __tablename__ = "addresses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
'''
    models = _models(("legacy/models.py", src))
    assert _fields(models["User"])["name"].type == "String"
    assert _fields(models["Address"])["user_id"].on_delete == "SET_NULL"
    assert _rels(models["User"])["addresses"].lazy == "dynamic"
    assert _rels(models["User"])["addresses"].collection is True  # FK on the other side
    backref = _rels(models["Address"])["user"]
    assert backref.via_backref and backref.target == "User" and backref.collection is False


def test_flask_sqlalchemy_auto_table_names_and_single_table_inheritance() -> None:
    src = '''
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class UserAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20))
    posts = db.relationship("BlogPost", backref="author")
    __mapper_args__ = {"polymorphic_on": type}


class Admin(UserAccount):
    level = db.Column(db.Integer)
    __mapper_args__ = {"polymorphic_identity": "admin"}


class BlogPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user_account.id"))
'''
    models = _models(("site/models.py", src))
    assert models["UserAccount"].table_name == "user_account"
    assert models["BlogPost"].table_name == "blog_post"
    assert models["Admin"].table_name == "user_account"  # no key of its own: same table
    assert _fields(models["BlogPost"])["author_id"].related_model == "UserAccount"
    # The subclass reaches the parent's relationships.
    assert _rels(models["Admin"])["posts"].inherited_from == "UserAccount"


def test_sqlmodel_tables_inherit_fields_and_schemas_are_not_models() -> None:
    src = '''
import uuid
from sqlmodel import Field, Relationship, SQLModel


class TeamBase(SQLModel):
    name: str = Field(index=True)


class Team(TeamBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    heroes: list["Hero"] = Relationship(back_populates="team")


class HeroBase(SQLModel):
    name: str
    age: int | None = None


class Hero(HeroBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: int | None = Field(default=None, foreign_key="team.id", ondelete="CASCADE")
    team: Team | None = Relationship(back_populates="heroes")


class HeroCreate(HeroBase):
    secret: str
'''
    models = _models(("api/models.py", src))
    assert set(models) == {"Team", "Hero"}
    assert models["Hero"].table_name == "hero"
    hero = _fields(models["Hero"])
    assert hero["name"].inherited_from == "HeroBase" and hero["age"].type == "Integer"
    assert hero["id"].type == "Uuid"
    assert (hero["team_id"].related_model, hero["team_id"].on_delete) == ("Team", "CASCADE")
    assert _rels(models["Team"])["heroes"].collection is True
    assert _rels(models["Hero"])["team"].collection is False


def test_abstract_bases_and_mixins_lend_columns() -> None:
    src = '''
from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column, relationship


class Model(DeclarativeBase):
    __abstract__ = True


class IDModel(Model):
    __abstract__ = True
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class TimestampedModel(Model):
    __abstract__ = True
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))


class OrganizationMixin:
    organization_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))

    @declared_attr
    def organization(cls) -> Mapped["Organization"]:
        return relationship("Organization", lazy="raise")


class RecordModel(IDModel, TimestampedModel):
    __abstract__ = True


class Organization(RecordModel):
    __tablename__ = "organizations"


class Product(RecordModel, OrganizationMixin):
    __tablename__ = "products"
'''
    models = _models(("server/models.py", src))
    assert set(models) == {"Organization", "Product"}
    product = _fields(models["Product"])
    assert {"id", "created_at", "organization_id"} <= set(product)
    assert product["organization_id"].related_model == "Organization"
    assert product["id"].inherited_from == "IDModel"
    assert _rels(models["Product"])["organization"].lazy == "raise"
    assert models["Product"].fields == []  # the class body declares nothing itself
    dbml = build_dbml(
        WorkspaceIndex(apps=[ParsedApp(name="server", path="server", models=list(models.values()))])
    )
    assert "  id Uuid [pk]" in dbml  # the mixin's key, not a synthesized one
    assert "Ref: server.Product.organization_id > server.Organization.id" in dbml


def test_declared_attr_table_name_rule_on_the_base() -> None:
    src = '''
import re
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

CAMEL_TO_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


class Base(DeclarativeBase):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return CAMEL_TO_SNAKE.sub("_", cls.__name__).lower()

    id: Mapped[int] = mapped_column(primary_key=True)


class FlowRun(Base):
    flow_id: Mapped[int] = mapped_column(sa.ForeignKey("flow.id"))


class Flow(Base):
    pass


class Event(Base):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "events"
'''
    models = _models(("orm_models.py", src))
    assert models["FlowRun"].table_name == "flow_run"
    assert models["Event"].table_name == "events"
    assert _fields(models["FlowRun"])["flow_id"].related_model == "Flow"


def test_foreign_keys_argument_decides_the_direction() -> None:
    src = '''
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Teams(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    captain_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    members = db.relationship("Users", backref="team", foreign_keys="Users.team_id")


class Users(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"))
'''
    models = _models(("ctf/models.py", src))
    # Keys run both ways; foreign_keys says members is the one-to-many side.
    assert _rels(models["Teams"])["members"].collection is True
    assert _rels(models["Users"])["team"].collection is False


def test_base_and_aliased_interface_in_other_files(tmp_path: Path) -> None:
    _write(tmp_path, "core/base.py", "from sqlalchemy.orm import DeclarativeBase\n\n\nclass Base(DeclarativeBase):\n    pass\n")
    # No SQLAlchemy token in this file: it is found through the import.
    _write(
        tmp_path,
        "core/interfaces.py",
        "from core.base import Base\n\n\nclass Dashboard(Base):\n    __abstract__ = True\n",
    )
    _write(
        tmp_path,
        "app/models/dashboard.py",
        "from sqlalchemy import Column, Integer\n"
        "from core.interfaces import Dashboard as CoreDashboard\n\n\n"
        "class Dashboard(CoreDashboard):\n"
        '    __tablename__ = "dashboards"\n'
        "    id = Column(Integer, primary_key=True)\n",
    )
    models, _ = scan_sqlalchemy_models(tmp_path)
    assert [(m.name, m.table_name, m.app_name) for m in models] == [
        ("Dashboard", "dashboards", "app")
    ]


def test_pep758_except_clause_does_not_hide_the_file() -> None:
    src = (
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n\n"
        "class Base(DeclarativeBase):\n    pass\n\n"
        "class Checkout(Base):\n"
        '    __tablename__ = "checkouts"\n'
        "    id: Mapped[int] = mapped_column(primary_key=True)\n\n"
        "def f():\n    try:\n        pass\n    except ValueError, TypeError:\n        pass\n"
    )
    parse_source(src)
    assert "Checkout" in _models(("models.py", src))


def test_alembic_revisions_and_tests_are_not_scanned(tmp_path: Path) -> None:
    model = (
        "from sqlalchemy.orm import declarative_base\nfrom sqlalchemy import Column, Integer\n"
        "Base = declarative_base()\n\n\nclass Slice(Base):\n"
        '    __tablename__ = "slices"\n    id = Column(Integer, primary_key=True)\n'
    )
    _write(tmp_path, "alembic/env.py", "")
    _write(tmp_path, "alembic/versions/0001_fix.py", model)
    _write(tmp_path, "tests/test_models.py", model)
    _write(tmp_path, "app/models.py", model.replace("Slice", "Chart").replace("slices", "charts"))
    models, _ = scan_sqlalchemy_models(tmp_path)
    assert [m.name for m in models] == ["Chart"]


FLASK_MODELS = '''
from app import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True)
'''


def test_flask_models_py_is_not_read_as_django(tmp_path: Path) -> None:
    assert is_sqlalchemy_only_source(FLASK_MODELS)
    assert not is_sqlalchemy_only_source("from django.db import models\nimport sqlalchemy\n")
    _write(tmp_path, "app/models.py", FLASK_MODELS)
    assert scan_workspace(str(tmp_path)).total_models() == 0  # used to be a Django model
    index = scan_workspace(str(tmp_path), include_sqlalchemy=True)
    assert [(m.name, m.orm, m.table_name) for a in index.apps for m in a.models] == [
        ("User", "sqlalchemy", "user")
    ]


def test_mixed_workspace_keeps_each_orm_to_its_own(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "shop/models.py",
        "from django.db import models\n\n\nclass Order(models.Model):\n"
        "    total = models.IntegerField()\n",
    )
    _write(tmp_path, "analytics/tables.py", MODERN)
    # A Django project that does not declare SQLAlchemy is not searched for it:
    # reading every file costs seconds on a large codebase.
    django_only = scan_workspace(str(tmp_path), include_sqlalchemy=True)
    assert [m.name for a in django_only.apps for m in a.models] == ["Order"]
    _write(tmp_path, "analytics/requirements.txt", "SQLAlchemy==2.0.36\n")
    index = scan_workspace(str(tmp_path), include_sqlalchemy=True)
    assert {(m.name, m.orm) for a in index.apps for m in a.models} == {
        ("Order", "django"), ("User", "sqlalchemy"), ("Address", "sqlalchemy"), ("Role", "sqlalchemy"),
    }
    assert index.only("django").total_models() == 1
    assert scan_workspace(str(tmp_path)).total_models() == 1  # default stays Django-only
    order = index.only("django").apps[0].models[0].to_dict()
    assert "orm" not in order and "relationships" not in order  # Django JSON unchanged


def test_declares_sqlalchemy_looks_two_levels_down(tmp_path: Path) -> None:
    assert not declares_sqlalchemy(tmp_path)
    _write(tmp_path, "server/pyproject.toml", '[project]\ndependencies = ["django>=5"]\n')
    assert not declares_sqlalchemy(tmp_path)
    _write(tmp_path, "server/requirements-prod.txt", "sqlmodel==0.0.22\n")
    assert declares_sqlalchemy(tmp_path)
    other = tmp_path / "other"
    _write(other, "a/b/c/alembic.ini", "")
    assert not declares_sqlalchemy(other)  # three levels down: not looked at
    _write(other, "a/alembic.ini", "")
    assert declares_sqlalchemy(other)


def test_er_diagrams_for_sqlalchemy_models() -> None:
    models = list(_models(("app/models.py", MODERN)).values())
    index = WorkspaceIndex(apps=[ParsedApp(name="app", path="app", models=models)])
    mermaid = _build_mermaid(index)
    assert 'Address }o--|| User : "user_id [CASCADE]"' in mermaid
    assert mermaid.count("}o--o{") == 1  # the many-to-many, once
    assert "addresses" not in mermaid  # relationships are not columns
    dbml = build_dbml(index)
    assert dbml.startswith("// SQLAlchemy schema exported by")
    assert "Ref: app.Address.user_id > app.User.id [delete: cascade]" in dbml
    assert "Ref: app.User.roles <> app.Role.id" in dbml


def test_cli_scan_list_describe_include_sqlalchemy(tmp_path: Path) -> None:
    _write(tmp_path, "app/models.py", MODERN)
    code, out = _run("list", "--path", str(tmp_path))
    assert code == 0 and out.split() == ["app.User", "app.Address", "app.Role"]
    code, out = _run("scan", "--path", str(tmp_path))
    user = json.loads(out)["apps"][0]["models"][0]
    assert user["orm"] == "sqlalchemy" and user["tableName"] == "user_account"
    assert {r["name"] for r in user["relationships"]} == {"addresses", "roles"}
    code, out = _run("describe", "User", "--path", str(tmp_path))
    assert "SQLAlchemy, table `user_account`" in out and "| `addresses` | **Address** | many |" in out
    code, out = _run("drift", "--path", str(tmp_path), "--format", "json")
    assert "User" not in out  # Django-only analyses never see SQLAlchemy models


def test_mcp_accepts_sqlalchemy_projects_and_describes_models(tmp_path: Path, monkeypatch) -> None:
    from orm_lens.mcp_server import _tool_describe_model, _tool_find_relations

    monkeypatch.delenv("ORM_LENS_ALLOWED_ROOTS", raising=False)
    _write(tmp_path, "src/db/models.py", MODERN)
    _write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["sqlalchemy>=2"]\n')
    clear_cache()
    resolved = resolve_workspace(str(tmp_path))
    assert isinstance(resolved, Path)
    detail = json.loads(_tool_describe_model({"workspace_root": str(tmp_path), "model": "Address"}))
    assert detail["orm"] == "sqlalchemy" and detail["relationships"][0]["name"] == "user"
    rels = json.loads(_tool_find_relations({"workspace_root": str(tmp_path), "model": "User"}))
    assert {i["from"] for i in rels["inbound"]} == {"db.Address"}
    assert {r["name"] for r in rels["relationships"]} == {"addresses", "roles"}
