"""Static Django signal graph extractor — pure AST, no Django boot, no DB.

Walks every ``.py`` file in the workspace and extracts three things:

1. Every ``@receiver(signal[, sender=X])`` decorated function — captured as a
   ``sender → signal → handler`` edge. ``sender`` is normalised to
   ``app.Model`` when the class name resolves against the parsed workspace,
   or left as the raw source token when it doesn't (with a note).
2. Every ``foo = Signal(...)`` module-level assignment — captured as a
   custom signal definition with fully-qualified name.
3. Every ``<custom_signal>.send(...)`` / ``.send_robust(...)`` call — used
   to populate the ``sent_from`` list on each custom signal definition.

A separate ``orphan_handlers`` bucket lists receivers whose declared
``sender`` couldn't be resolved to any model in the workspace — a common
smell (typo, string reference to an app not imported, obsolete signal).

Directories skipped: ``migrations/``, ``node_modules/``, ``venv/``, ``env/``,
``.git/``, ``__pycache__/`` and any dot-prefixed folder.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from .models import WorkspaceIndex, find_user_model

# Django built-in signals we know about — used for tagging edges as "django-native".
_BUILTIN_SIGNALS = frozenset(
    {
        "pre_init", "post_init",
        "pre_save", "post_save",
        "pre_delete", "post_delete",
        "m2m_changed",
        "pre_migrate", "post_migrate",
        "request_started", "request_finished", "got_request_exception",
        "setting_changed",
        "user_logged_in", "user_logged_out", "user_login_failed",
    }
)


def _rel(root: Path, path: Path, line: int) -> str:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    return f"{rel}:{line}"


def _module_path_from_file(root: Path, path: Path) -> str:
    """``root/notifications/signals.py`` → ``notifications.signals``."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _name_of(node: ast.AST) -> str | None:
    """Best-effort textual dotted name of a Name/Attribute AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        if base is None:
            return node.attr
        return f"{base}.{node.attr}"
    return None


def _extract_receiver_call(dec: ast.AST) -> ast.Call | None:
    """Return the ``receiver(...)`` Call node if ``dec`` is one, else None.

    Accepts both ``@receiver(...)`` and ``@dispatch.receiver(...)`` forms.
    """
    if not isinstance(dec, ast.Call):
        return None
    func_name = _name_of(dec.func)
    if not func_name:
        return None
    tail = func_name.rsplit(".", 1)[-1]
    if tail != "receiver":
        return None
    return dec


def _signal_arg_name(call: ast.Call) -> str | None:
    """First positional arg of ``receiver(signal, sender=..., ...)`` as a dotted
    name (``post_save`` or ``orders.signals.order_shipped``)."""
    if not call.args:
        return None
    return _name_of(call.args[0])


def _sender_kwarg(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if kw.arg == "sender":
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
            return _name_of(kw.value)
    return None


def _iter_signal_definitions(tree: ast.Module) -> list[tuple[str, int]]:
    """Yield (var_name, lineno) for every module-level ``x = Signal(...)``."""
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func_name = _name_of(node.value.func)
        if not func_name:
            continue
        if func_name.rsplit(".", 1)[-1] != "Signal":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                out.append((target.id, node.lineno))
    return out


def _resolve_sender(
    raw: str | None,
    model_index: dict[str, str],
    user_model_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Turn a raw sender token into (canonical, note).

    * ``None`` → (None, None) → fires for all models (caller adds a note).
    * ``"Order"`` → look up in model_index; return (``"orders.Order"``, None)
      or (raw, "sender model not found in workspace") on miss.
    * dotted / string forms (``"orders.Order"``, ``"MyApp.Model"``) →
      normalise via model_index tail lookup.
    * ``"settings.AUTH_USER_MODEL"`` / bare ``"AUTH_USER_MODEL"`` →
      resolve to the workspace's User model when known; otherwise
      surface as an orphan (helps flag misconfigured signal receivers).
    """
    if raw is None:
        return None, None
    tail = raw.rsplit(".", 1)[-1]
    if tail == "AUTH_USER_MODEL":
        if user_model_name:
            canonical = model_index.get(user_model_name)
            if canonical:
                return canonical, None
        return raw, "sender model not found in workspace"
    canonical = model_index.get(tail)
    if canonical:
        return canonical, None
    return raw, "sender model not found in workspace"


def _build_model_index(workspace: WorkspaceIndex) -> dict[str, str]:
    """``Order`` → ``orders.Order``. Last write wins on collisions (rare in
    real Django projects — model names are usually unique per project)."""
    out: dict[str, str] = {}
    for app in workspace.apps:
        for m in app.models:
            out[m.name] = f"{app.name}.{m.name}"
    return out


def signal_graph(
    root: str, index: WorkspaceIndex | None = None
) -> dict[str, Any]:
    """Return the sender→signal→handler graph for the workspace.

    Shape matches the MCP tool spec: ``edges``, ``custom_signals``,
    ``orphan_handlers``. Pure AST parse — no Django import, no DB.
    """
    from .parser import DEFAULT_EXCLUDES, scan_workspace

    if index is None:
        index = scan_workspace(root, DEFAULT_EXCLUDES)
    model_index = _build_model_index(index)
    user_model = find_user_model(index)
    user_model_name = user_model.name if user_model else None

    root_path = Path(root).resolve()

    edges: list[dict[str, Any]] = []
    orphan_handlers: list[dict[str, Any]] = []
    # custom_signal FQN → definition metadata
    custom_signals: dict[str, dict[str, Any]] = {}
    # short var name → FQN, per module (populated pass 1, consumed pass 2)
    signal_defs_by_module: dict[str, dict[str, str]] = {}

    from .parser import iter_workspace_py_files  # local to avoid cycles
    py_files: list[Path] = list(iter_workspace_py_files(root_path))
    parsed: list[tuple[Path, ast.Module, str]] = []

    # Pass 1 — collect Signal() definitions so pass 2 can resolve .send()
    # against them.
    for py in py_files:
        try:
            source = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(py))
        except SyntaxError:
            continue
        module_path = _module_path_from_file(root_path, py)
        parsed.append((py, tree, module_path))
        module_defs: dict[str, str] = {}
        for var_name, lineno in _iter_signal_definitions(tree):
            fqn = f"{module_path}.{var_name}" if module_path else var_name
            custom_signals[fqn] = {
                "name": var_name,
                "defined_in": _rel(root_path, py, lineno),
                "sent_from": [],
            }
            module_defs[var_name] = fqn
        if module_defs:
            signal_defs_by_module[module_path] = module_defs

    # Also build a bare-name → FQN map for cross-module short refs
    # (only used when a name is unambiguous across the workspace).
    bare_signal_map: dict[str, list[str]] = {}
    for fqn, meta in custom_signals.items():
        bare_signal_map.setdefault(meta["name"], []).append(fqn)

    # Pass 2 — decorators + .send() calls.
    for py, tree, module_path in parsed:
        # Walk all functions (module-level + nested) for @receiver decorators.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    rcall = _extract_receiver_call(dec)
                    if rcall is None:
                        continue
                    signal_name = _signal_arg_name(rcall) or "<unknown>"
                    sender_raw = _sender_kwarg(rcall)
                    sender, note = _resolve_sender(
                        sender_raw, model_index, user_model_name
                    )

                    handler_fqn = (
                        f"{module_path}.{node.name}" if module_path else node.name
                    )
                    edge: dict[str, Any] = {
                        "signal": signal_name,
                        "sender": sender,
                        "handler": handler_fqn,
                        "file": _rel(root_path, py, node.lineno),
                    }
                    if sender_raw is None:
                        edge["note"] = "no sender = fires for all models"
                    elif note:
                        edge["note"] = note
                        orphan_handlers.append(
                            {
                                "handler": handler_fqn,
                                "reason": "@receiver but sender model not found in workspace",
                            }
                        )
                    if signal_name in _BUILTIN_SIGNALS or signal_name.rsplit(".", 1)[-1] in _BUILTIN_SIGNALS:
                        edge["builtin"] = True
                    edges.append(edge)

            # Custom signal .send() / .send_robust() call collection.
            if isinstance(node, ast.Call):
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                if func.attr not in ("send", "send_robust"):
                    continue
                base_name = _name_of(func.value)
                if not base_name:
                    continue
                # Try local-module resolution first, then bare-name lookup.
                local_defs = signal_defs_by_module.get(module_path, {})
                sig_fqn = local_defs.get(base_name)
                if sig_fqn is None:
                    candidates = bare_signal_map.get(base_name.rsplit(".", 1)[-1], [])
                    if len(candidates) == 1:
                        sig_fqn = candidates[0]
                if sig_fqn is None:
                    continue
                custom_signals[sig_fqn]["sent_from"].append(
                    _rel(root_path, py, node.lineno)
                )

    # Dedup orphan_handlers on (handler,) — a receiver decorated twice for
    # different missing senders shouldn't spam the list.
    seen_orphans: set[str] = set()
    dedup_orphans: list[dict[str, Any]] = []
    for row in orphan_handlers:
        key = row["handler"]
        if key in seen_orphans:
            continue
        seen_orphans.add(key)
        dedup_orphans.append(row)

    return {
        "edges": edges,
        "custom_signals": [
            {"name": meta["name"], "fqn": fqn, **{k: v for k, v in meta.items() if k != "name"}}
            for fqn, meta in sorted(custom_signals.items())
        ],
        "orphan_handlers": dedup_orphans,
    }
