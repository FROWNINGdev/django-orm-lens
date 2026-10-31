"""Pre-rename import path of :mod:`orm_lens`.

django-orm-lens became orm-lens in 1.16.0. ``import django_orm_lens`` and
any ``django_orm_lens.<module>`` resolve to the very same module objects as
``orm_lens`` and ``orm_lens.<module>``, so code, ``mock.patch`` targets and
pickles written against the old name keep working.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType

from orm_lens import *  # noqa: F403
from orm_lens import __all__, __version__  # noqa: F401

_PREFIX = __name__ + "."


class _AliasFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve ``django_orm_lens.x`` to the already-importable ``orm_lens.x``."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if not fullname.startswith(_PREFIX):
            return None
        return importlib.util.spec_from_loader(fullname, self)

    def __init__(self) -> None:
        self._own_specs: dict[int, ModuleSpec | None] = {}

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        module = importlib.import_module("orm_lens." + spec.name[len(_PREFIX):])
        self._own_specs[id(module)] = module.__spec__
        return module

    def exec_module(self, module: ModuleType) -> None:
        # The module is already executed. importlib has just pointed its
        # __spec__ at the alias spec, though; give it back its own, or its
        # relative imports warn (__package__ != __spec__.parent) and a reload
        # would go through the alias.
        own = self._own_specs.pop(id(module), None)
        if own is not None:
            module.__spec__ = own


# Appended, not prepended: real files in this directory (__main__.py) are
# found first by the normal path finder.
if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
    sys.meta_path.append(_AliasFinder())
