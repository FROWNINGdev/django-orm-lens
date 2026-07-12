"""Django ORM Lens — sidebar tree, ER diagrams, and JSON for Django models.

Terminal / editor-agnostic parser for Django models.py files.
Ships a CLI and an optional MCP server for AI coding agents.
"""

__version__ = "1.0.2"

from .models import ParsedApp, ParsedField, ParsedModel, WorkspaceIndex
from .parser import parse_models_file, scan_workspace

__all__ = [
    "ParsedApp",
    "ParsedField",
    "ParsedModel",
    "WorkspaceIndex",
    "parse_models_file",
    "scan_workspace",
    "__version__",
]
