"""SQLAlchemy N+1: query shapes followed to the loop, loader options, precision.

Census (CTFd, Airflow, Dispatch, Mealie, Polar, Prefect, Redash, Superset, the
FastAPI template): every finding in the sample was a real per-row query. The
negative cases below are the shapes that must stay quiet.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from django_orm_lens.cli import main
from django_orm_lens.models import ParsedApp, WorkspaceIndex
from django_orm_lens.sqlalchemy_nplusone import (
    scan_all_nplusone,
    scan_source,
    scan_sqlalchemy_nplusone,
)
from django_orm_lens.sqlalchemy_parser import parse_sqlalchemy_sources

MODELS = '''
from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")
    profile: Mapped["Profile"] = relationship(lazy="joined")
    groups: Mapped[list["Group"]] = relationship(lazy="selectin")
    audit: Mapped[list["Audit"]] = relationship(lazy="raise")
    feed: Mapped[list["Post"]] = relationship(lazy="dynamic", viewonly=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    author: Mapped[User] = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship()


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
'''

HEADER = (
    "from sqlalchemy import select\n"
    "from sqlalchemy.orm import Load, defaultload, joinedload, raiseload, selectinload\n\n"
)


@pytest.fixture(scope="module")
def index() -> WorkspaceIndex:
    models = parse_sqlalchemy_sources([("app/models.py", MODELS)])
    return WorkspaceIndex(apps=[ParsedApp(name="app", path="app", models=models)])


def _scan(index: WorkspaceIndex, body: str) -> list:
    return scan_source(HEADER + body, "views.py", index)


def _accessed(index: WorkspaceIndex, body: str) -> list[list[str]]:
    return [f.accessed for f in _scan(index, body)]


def test_collection_in_a_loop_over_scalars_is_high(index) -> None:
    (finding,) = _scan(index, '''
def view(session):
    users = session.scalars(select(User).where(User.id > 1)).all()
    for user in users:
        print(user.posts, user.id)
''')
    assert finding.accessed == ["posts"]
    assert finding.confidence == "high"
    assert finding.loop_var == "user" and finding.queryset_var == "users"
    assert finding.suggested_fix == ".options(selectinload(User.posts))"
    assert finding.line == 7  # the for statement, 1-based


def test_many_to_one_is_medium_with_a_joinedload_fix(index) -> None:
    (finding,) = _scan(index, '''
def view(session):
    for post in session.query(Post).filter(Post.id > 1).all():
        print(post.author.id)
''')
    assert finding.accessed == ["author"] and finding.confidence == "medium"
    assert finding.suggested_fix == ".options(joinedload(Post.author))"


@pytest.mark.parametrize(
    "options",
    [
        "selectinload(User.posts)",
        "joinedload(User.posts)",
        'selectinload("posts")',
        "Load(User).selectinload(User.posts)",
        'raiseload("*")',
        "selectinload(User.posts).raiseload('*')",
    ],
)
def test_loader_options_cover_the_relationship(index, options: str) -> None:
    assert _scan(index, f'''
def view(session):
    stmt = select(User).options({options})
    for user in session.scalars(stmt):
        print(user.posts)
''') == []


def test_chained_options_cover_each_hop(index) -> None:
    body = '''
def view(session):
    stmt = select(Post).options({opts})
    for post in session.scalars(stmt):
        print(post.author.posts)
'''
    assert _accessed(index, body.format(opts="joinedload(Post.author).selectinload(User.posts)")) == []
    # defaultload walks the path without loading author itself.
    assert _accessed(index, body.format(opts="defaultload(Post.author).selectinload(User.posts)")) == [
        ["author"]
    ]
    assert _accessed(index, body.format(opts="joinedload(Post.author)")) == [["author.posts"]]


def test_eager_or_raising_relationships_are_not_reported(index) -> None:
    assert _scan(index, '''
def view(session):
    for user in session.scalars(select(User)):
        print(user.profile, user.groups, user.audit, user.feed)
''') == []


def test_flask_query_property_and_options(index) -> None:
    assert _accessed(index, '''
def view():
    for user in User.query.filter_by(active=True).all():
        print(user.posts)
''') == [["posts"]]
    assert _scan(index, '''
def view():
    for user in User.query.options(selectinload(User.posts)):
        print(user.posts)
''') == []


def test_execute_scalars_await_and_comprehensions(index) -> None:
    found = _accessed(index, '''
async def view(session):
    result = await session.execute(select(Post))
    for post in result.scalars().all():
        print(post.comments)
    return [p.comments for p in (await session.scalars(select(Post))).all()]
''')
    assert found == [["comments"], ["comments"]]


def test_rows_unpacked_per_entity(index) -> None:
    (finding,) = _scan(index, '''
def view(session):
    for user, post in session.execute(select(User, Post).join(User.posts)):
        print(post.comments, user.id)
''')
    assert finding.loop_var == "post" and finding.accessed == ["comments"]


def test_nested_loop_over_a_loaded_collection(index) -> None:
    (finding,) = _scan(index, '''
def view(session):
    stmt = select(User).options(selectinload(User.posts))
    for user in session.scalars(stmt):
        for post in user.posts:
            print(post.comments, post.author)
''')
    # post.author is the user being looped over: already in the identity map.
    assert finding.loop_var == "post" and finding.accessed == ["comments"]
    assert finding.suggested_fix == ".options(selectinload(User.posts).selectinload(Post.comments))"


def test_loop_over_a_single_objects_collection(index) -> None:
    (finding,) = _scan(index, '''
def view(session, pk):
    user = session.get(User, pk)
    for post in user.posts:
        print(post.comments)
''')
    assert finding.accessed == ["comments"]


def test_writes_method_calls_and_columns_are_not_reads(index) -> None:
    assert _scan(index, '''
def view(session):
    for user in session.scalars(select(User)):
        user.posts = []
        user.refresh()
        del user.profile
        print(user.id, user.name)
''') == []


def test_unreadable_options_or_rebound_queries_stay_quiet(index) -> None:
    assert _scan(index, '''
def view(session, opts, filters):
    for user in session.scalars(select(User).options(*opts)):
        print(user.posts)
    stmt = select(User)
    for f in filters:
        stmt = f.apply(stmt)
    for user in session.scalars(stmt):
        print(user.posts)
''') == []


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "models.py").write_text(MODELS, encoding="utf-8")
    loop = HEADER + (
        "def view(session):\n"
        "    for user in session.scalars(select(User)):\n"
        "        print(user.posts)\n"
    )
    (tmp_path / "app" / "views.py").write_text(loop, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_views.py").write_text(loop, encoding="utf-8")
    (tmp_path / "alembic" / "versions").mkdir(parents=True)
    (tmp_path / "alembic" / "versions" / "0002_backfill.py").write_text(
        'revision = "0002"\ndown_revision = "0001"\n\n\n' + loop, encoding="utf-8"
    )
    # Not SQLAlchemy code: Django's schema-less heuristics would flag it.
    (tmp_path / "app" / "legacy.py").write_text(
        "def run(Order):\n    for o in Order.objects.all():\n        print(o.item_set.all())\n",
        encoding="utf-8",
    )
    return tmp_path


def test_project_scan_skips_tests_and_revisions(tmp_path: Path) -> None:
    from django_orm_lens.parser import scan_workspace

    root = _project(tmp_path)
    index = scan_workspace(str(root), include_sqlalchemy=True)
    files = [f.file for f in scan_sqlalchemy_nplusone(str(root), index)]
    assert files == ["app/views.py"]
    with_tests = scan_sqlalchemy_nplusone(str(root), index, include_tests=True)
    assert sorted(f.file for f in with_tests) == ["app/views.py", "tests/test_views.py"]
    # A SQLAlchemy-only project does not get Django advice.
    assert [f.file for f in scan_all_nplusone(str(root), index)] == ["app/views.py"]


def test_cli_nplusone_reports_sqlalchemy_findings(tmp_path: Path) -> None:
    root = _project(tmp_path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(["nplusone", "--path", str(root), "--format", "json"])
    assert code == 1
    (finding,) = json.loads(out.getvalue())
    assert finding["file"] == "app/views.py" and finding["accessed"] == ["posts"]
    assert finding["suggested_fix"] == ".options(selectinload(User.posts))"
