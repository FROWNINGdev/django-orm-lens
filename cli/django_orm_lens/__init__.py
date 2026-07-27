"""Django ORM Lens — sidebar tree, ER diagrams, and JSON for Django models.

Terminal / editor-agnostic parser for Django models.py files.
Ships a CLI and an optional MCP server for AI coding agents.
"""

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version
    try:
        __version__ = _pkg_version("django-orm-lens")
    except PackageNotFoundError:
        __version__ = "0.0.0+local"
except ImportError:
    __version__ = "0.0.0+local"

from .models import (
    ParsedApp,
    ParsedField,
    ParsedModel,
    WorkspaceIndex,
    cascade_preview,
    find_model,
    find_user_model,
    find_user_model_from_dict,
    resolve_related_tail,
)
from .parser import (
    BROAD_SKIP_DIRS,
    iter_workspace_py_files,
    parse_models_file,
    scan_workspace,
)

__all__ = [
    "ParsedApp",
    "ParsedField",
    "ParsedModel",
    "WorkspaceIndex",
    "parse_models_file",
    "scan_workspace",
    # v1.2.0 — shared helpers for downstream tools that build on the parser.
    "BROAD_SKIP_DIRS",
    "find_model",
    "find_user_model",
    "find_user_model_from_dict",
    "iter_workspace_py_files",
    "resolve_related_tail",
    # shared relation analysis used by both the CLI and the MCP server.
    "cascade_preview",
    "__version__",
]
