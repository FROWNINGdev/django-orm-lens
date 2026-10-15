"""Static QuerySet usage analyzer — pure AST, no Django boot, no DB.

Walks every ``.py`` file in the workspace (skipping ``migrations/``, ``venv/``,
``node_modules/``, ``.git/`` and other hidden dirs) and extracts every call
of the form ``<ModelClassName>.objects.<qs_method>(...)`` where ``qs_method``
is one of ``filter``, ``exclude``, ``get``, ``order_by``, ``aggregate``.

Captured signals per usage site:
* keyword-arg names (field names, dropping ``__lookup`` suffixes)
* positional ``order_by`` string args (preserving the ``-`` prefix)
* ``advanced=True`` flag when the call contains a positional non-string
  arg (typically ``Q()``/``F()`` expressions) that we don't statically
  decompose

The analyzer proposes ``Meta.indexes`` entries by frequency:
* every field used in >=2 filter/exclude sites → single-field index candidate
* every co-occurrence in the SAME filter/exclude call → composite candidate
* every field appearing in >=2 order_by sites → order_by index candidate

Existing ``Meta.indexes`` are read from the parser output and returned so
callers can dedupe suggestions the user has already covered.

Implementation is split by concern; this module re-exports both halves so
existing ``from orm_synapse.query_analyzer import ...`` callers keep working:

* ``index_suggestions`` — ``suggest_indexes`` and its helpers
* ``nplusone`` — ``scan_for_nplusone`` and the N+1 detector
"""

from __future__ import annotations

from .index_suggestions import *  # noqa: F401,F403
from .index_suggestions import (  # noqa: F401
    _unique_together_tuples,
)
from .nplusone import *  # noqa: F401,F403
from .nplusone import (  # noqa: F401
    _build_schema_from_index,
    _helper_call_name,
    _ReturnedQuerySetTracker,
)
