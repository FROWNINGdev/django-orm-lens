# Changelog

All notable changes to Django ORM Lens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`blast-radius`** — the review-time question the tool could not answer
  before: *what does this schema change actually hit?* Every destructive
  migration operation (`RemoveField`, `DeleteModel`, `RenameField`,
  `RenameModel`, `AlterField`) becomes a target carrying its migration risks,
  every place in the codebase that still references it, and — for whole-model
  operations — the cascade fallout. The three analyzers behind it already
  shipped separately; nobody joined them by hand, so the tool does it now.
  `--format markdown` emits a ready-to-post PR comment, `--format github`
  emits annotations naming the reference count in the title, and `--only`
  narrows the scan to a PR's changed migration files. Exit code `1` on
  remaining critical risks, matching `migration-risk`. Available through the
  GitHub Action as `command: blast-radius`.
- **`drift`** — `makemigrations --check` without booting Django. Each app's
  migrations are replayed in numeric order into the field set they imply, and
  compared against what `models.py` declares. Django's own check needs a
  working settings module, an importable app registry and every dependency
  installed, so it is unavailable on a cold clone or a broken venv — exactly
  when acting on the answer is cheapest. Only the dangerous direction fails
  the build: a field declared but never migrated (the column will not exist,
  and the first query touching it errors), or a model with no `CreateModel`
  anywhere. Columns present in the migrations but absent from `models.py` are
  reported without blocking, because static analysis cannot see fields
  injected by mixins or metaclass-resolved abstract bases, and failing on
  those would teach people to pass `--exit-zero` permanently.
- **`nplusone` now resolves across functions** — the detector used to give up
  whenever a loop's source was a call rather than an inline chain or a local
  variable, which is how a large share of real Django code is written: the
  queryset is built in a helper or in `get_queryset()`, and the loop lives
  elsewhere. `for post in recent():` is now analysed. Resolution is one hop
  within the module and covers `helper()`, `self.get_queryset()`,
  `cls.build()`, a helper returning a local binding, a return from inside an
  `if`, and a helper defined *after* its caller. Fixes count from either side
  of the call — `select_related` inside the helper and
  `recent().select_related(...)` applied by the caller are both silent, since
  the two chains are spliced before the check. A nested `def`'s return is
  never attributed to the function enclosing it, and a call to a name the
  module does not define is left alone rather than assigned an invented
  model.
- **`blast-radius --stats` and `stats-sql`** — optional production table
  statistics, with **no database connection**. `stats-sql` prints a read-only
  query (`pg_stat_user_tables` + `pg_total_relation_size`, no locks, no user
  data); you run it against a replica and pass the JSON to `--stats`. The
  report then says `blog_post: ~41 000 000 rows, 12.0 GB, 4 index(es)`
  instead of leaning on the "anything after `0001_` is populated" heuristic.
  A credential never enters CI config and there is nothing to leak; the file
  can be committed and reviewed like any other input. Numbers are always
  labelled as estimates — `n_live_tup` drifts between `ANALYZE` runs — and a
  table absent from the file is reported as **unknown**, never as zero, so a
  model production has never seen cannot read as "safe to drop".
  `Meta.db_table` is honoured when resolving a model to its table.
- **`blast-radius` as a real PR bot** — the Action gained `comment: true`,
  which posts the markdown report and then *updates that same comment* on
  every later push, so a twenty-push PR carries one report rather than
  twenty. Matching is by the `<!-- django-orm-lens: blast-radius -->` marker
  the renderer emits as its first line. `only-changed: true` narrows the
  report to migrations the PR actually touches and exits early when it
  touches none; the file list comes from the API rather than `git diff`,
  because `actions/checkout` defaults to `fetch-depth: 1` and the base commit
  is simply not in the local history. The comment is posted *before* the job
  fails, so a blocked PR still carries the explanation — the exit code is
  preserved either way. On `push` events both flags skip with a notice
  instead of failing, so one workflow covers both triggers.
- **`impact <name>`** — "what still references this field or model?", grouped
  by Django layer with a `certain` / `likely` / `possibly` confidence tag.
  The analysis existed only inside the VS Code extension; it now ships in the
  CLI too, which is what makes `blast-radius` possible in CI.
- **`er --format dot`** — Graphviz DOT export alongside Mermaid, DBML, D2 and
  PlantUML, exposed through both the CLI and the MCP `er_diagram` tool. Apps
  become `subgraph cluster_*` blocks and model bodies are HTML tables rather
  than record labels, so field names containing `|` or `<` cannot break the
  render. Useful in particular for projects migrating from
  `django-extensions graph_models`, which emits the same format.
  Contributed by [@JJordan0C](https://github.com/JJordan0C) in
  [#53](https://github.com/FROWNINGdev/django-orm-lens/pull/53) — the project's
  first outside contribution. Closes
  [#48](https://github.com/FROWNINGdev/django-orm-lens/issues/48).
- **Vietnamese rule reference** — `docs/i18n/rules/vi/` covers the queryset
  family `DOL001`–`DOL007`, the first translation of the rule pages into any
  language. Code samples, rule codes and suppression syntax stay identical to
  the English source so they remain copy-pasteable and greppable. Contributed
  by [@RinZ27](https://github.com/RinZ27) in
  [#54](https://github.com/FROWNINGdev/django-orm-lens/pull/54), against
  [#52](https://github.com/FROWNINGdev/django-orm-lens/issues/52).

### Fixed

- **Layer detection no longer reads the checkout path** — impact analysis
  classifies a file by matching patterns like `/tests/` and `/views.py`
  against its path, and it was matching the *absolute* path. A project
  checked out under any directory called `tests` (or `api`, `forms`, …) had
  every one of its files classified into that layer — `views.py` reported as
  `tests`, and so on, in the Impact Analysis panel. Classification now runs
  on the path relative to the workspace root, so only the project's own
  layout counts. Fixed in both implementations: the CLI analyzer and the
  VS Code extension (`layerOf`, which the extension feeds from
  `workspace.asRelativePath`). Caught by the first end-to-end run of
  `blast-radius`, whose fixture happens to live under `cli/tests/`.
- **DOL005 and DOL006 documentation** — DOL005 claimed the `Q(...)` rewrite
  buys "one pass for the query planner"; Django already compiles the chained
  form into a single query, so the rule is a legibility hint and now says so.
  DOL006 claimed `list(qs)` builds "a second in-memory copy of every row"; it
  does not duplicate the model instances, and dropping the wrapper does not
  give you streaming — that still needs an explicit `.iterator()`. Both had
  been wrong since the rules shipped, and surfaced during review of #54.

## [py-1.6.0] - 2026-07-28

### Added

- **`conflicting_migration_leaves`** (migration-risk rule 16) — flags an app
  whose migration graph has more than one leaf, the state Django rejects with
  "Conflicting migrations detected; multiple leaf nodes in the migration
  graph". Two branches each adding a migration on the same parent produce it.
  Detected from the `dependencies` tuples alone, so it fires on a cold clone
  and in CI rather than waiting for someone to run `migrate` against a real
  database. Reported once per conflicting leaf, and inherits the existing
  SARIF and GitHub-annotation output. The Django app *label* is recovered from
  the dependencies, since `AppConfig.label` may differ from the package
  directory; the rule stays silent when that is ambiguous.
- **Sidebar visibility toggles** — checkboxes on apps and models. Unchecking
  hides the item from the ER diagram, cascading from an app to its models, and
  relations pointing at a hidden model are dropped so no edge dangles. The
  state persists per workspace, and stores what is *hidden* rather than what is
  visible, so a model added later shows up instead of silently disappearing.

### Fixed

- The ER webview reloaded a cached `graph.js`: the script URI never changed
  between builds, so a rebuilt bundle could not reach the panel. Cache-busted
  on the bundle's mtime.

## [py-1.5.1] - 2026-07-28

### Fixed

- `python -m django_orm_lens` now works. The package shipped without a
  `__main__.py`, so the module invocation failed with "No module named
  django_orm_lens.__main__" even though the `django-orm-lens` console script
  was fine. `python -m` is the invocation that does not depend on the scripts
  directory being on PATH, which is what CI images, tox environments and fresh
  venvs rely on. Two regression tests cover it.

## [py-1.5.0] - 2026-07-28

The "one core, three surfaces" wave: the CLI gains CI-native output formats,
four analyzers that were previously MCP-only, community-standard diagram
exports, and a documentation page for every rule.

### Added

- **CI output formats** — `nplusone` and `migration-risk` accept
  `--format sarif` (SARIF 2.1.0 for GitHub Code Scanning via
  `upload-sarif`) and `--format github` (workflow-command PR annotations,
  zero extra permissions). New module `ci_formats.py`; 20 tests.
- **Four new CLI subcommands** exposing analyzers that existed only behind
  MCP: `suggest-indexes <model>` (Meta.indexes proposals from observed
  QuerySet usage), `signals` (sender→signal→handler graph),
  `migration-deps <app>` (per-app migration DAG — text/json/mermaid),
  `cascade <model>` (delete blast-radius grouped by on_delete). Cascade
  logic moved into shared `models.cascade_preview` so the CLI and the MCP
  server can never drift.
- **ER diagram export formats** — `er --format dbml | d2 | plantuml`
  alongside the Mermaid default; the MCP `er_diagram` tool takes the same
  choice via a new optional `diagram_format` argument. DBML maps
  `on_delete` onto ref settings and apps onto schemas; D2 uses `sql_table`
  shapes with apps as containers; PlantUML uses crow's-foot entities.
  Explicit `primary_key=True` is respected; Django's implicit `id` is
  synthesized otherwise. 11 tests.
- **Three new migration-risk rules** (15 total): `runpython_no_reverse`
  (data migration without reverse_code), `alter_unique_together_lock`
  (unique index build/validation on a populated table — recognises all
  four clearing forms including Django's serialized `set()`), and
  `alter_index_together_deprecated` (operation removed in Django 5.1).
- **pre-commit hooks** — `.pre-commit-hooks.yaml` with
  `django-orm-lens-nplusone` and `django-orm-lens-migration-risk`, plus a
  root pyproject shim so pre-commit can install the repo directly.
- **GitHub Action** — composite `action.yml`
  (`uses: FROWNINGdev/django-orm-lens@<ref>`) wrapping the CLI with
  annotation/SARIF-friendly defaults.
- **docs/rules/** — 19 documentation pages: one per DOL rule (16), the
  migration-risk catalogue, the N+1 analyzer, and an index. Fixes the 16
  dead `docsUrl` links the Problems panel has been shipping.
- **Golden snapshot suite** — full parser-output snapshots for the five
  vendored real-world projects (59 models, 13,478 LOC); parser regressions
  now fail with a diff instead of passing silently.
  `UPDATE_GOLDEN_SNAPSHOTS=1` regenerates.
- **Manifest-sync test** — pyproject / server.json / smithery.yaml versions
  and the MCP tool count vs docstring can no longer drift.
- **CI lint job** — ruff + mypy on every push/PR, both starting green
  (433 ruff findings fixed, 9 mypy errors fixed across 5 files).

### Fixed

- `AlterUniqueTogether` clearing form `unique_together=set()` — the form
  `makemigrations` actually writes — no longer raises a false
  `alter_unique_together_lock`.
- MCP tool-count drift: 9 → **10 tools** everywhere (module docstring,
  section comment, `smithery.yaml` 1.2.7 → 1.4.0 with "10 read-only
  tools", `cli/README.md`).
- README accuracy: MCP table lists all 10 tools (was 5), migration-risk
  rule count corrected ("7 classes" → 15 rules), stale v0.8 labels
  removed.
- DBML export notes are workspace-relative — no absolute machine paths in
  shareable diagrams.

### Changed

- README repositioned as "The schema intelligence layer for Django":
  10-second `uvx` quickstart, a Gate-your-CI section, a measured
  performance section (59 real-world models / 13,478 LOC parsed in ~21 ms
  best-of-3 locally), honest "when you want something else" boundaries,
  and the rule catalogue moved to `docs/rules/`.
- `migration-risk` severity filtering computes its threshold only for
  explicit severities instead of relying on a `.get(..., 99)` fallback
  for `--severity all`.

### Removed

- `media/vendor/mermaid.min.js` (3.34 MB) — dead weight since the webview
  moved to React Flow; the VSIX shrinks accordingly.

## [py-1.4.0] - 2026-07-25

Adds the tenth MCP tool: **`nplusone_scan`** — a static scan for Django ORM
N+1 anti-patterns across the workspace. Wraps the existing
`query_analyzer.scan_for_nplusone` (which had 100% CLI-level test coverage
via `test_nplusone_detector.py`) as an MCP handler so AI coding agents can
ask "are there N+1 problems in this project?" and get actionable answers
with `path:line`, the queryset variable, which related fields were
accessed, and a suggested `select_related` / `prefetch_related` fix.

### Added

- **`nplusone_scan` MCP tool** — walks every `.py` file, finds
  `for x in <queryset>:` loops, and flags attribute-chain accesses against
  the loop target that touch a related object (FK / O2O / M2M / reverse FK)
  without a matching `select_related` / `prefetch_related` clause on the
  source queryset. Uses the parsed `WorkspaceIndex` to classify relations;
  falls back to a schema-less heuristic when a model is unknown.
- **Structured findings** — returns `[{file, line, loop_var, queryset_var,
  accessed, suggested_fix, confidence}]` where `confidence` is `"high"` or
  `"medium"`. Same `WorkspaceError` envelope pattern as the other 9 tools
  on workspace-resolution failure.
- **Tests** — 2 new tests in `test_mcp_server.py` (envelope on invalid
  workspace + happy-path detection against a textbook `for book in
  Book.objects.all(): print(book.author.name)` pattern). Full Python suite:
  **238 passed** (was 236), zero regressions. Existing 40+ unit tests in
  `test_nplusone_detector.py` continue to pin scanner behaviour.

### Changed

- **`server.json` description** — bumped tool count from 9 to 10 with the
  N+1 scanner mention, so MCP Registry + Smithery listings advertise the
  new capability accurately.

## [py-1.3.0] - 2026-07-25

Professional-grade fix for the workspace-resolution silent-drop bug. Before
1.3.0 every MCP tool function was registered without a ``workspace_root``
parameter in its Python signature — FastMCP therefore treated any
``workspace_root`` kwarg passed by an AI agent as an unknown argument and
silently discarded it, then fell back to ``$DJANGO_ORM_LENS_ROOT`` or
``os.getcwd()``. Cursor, Claude Desktop and Aider intuitively call
``list_apps(workspace_root="...")``; the argument vanished, the tool returned
``[]``, and the agent concluded the server was broken. Root cause verified
against microsoft/AL#8273, openai/codex#9989, aws-toolkit-jetbrains#6173,
kirodotdev/Kiro#5662 and modelcontextprotocol/python-sdk#1097 — every one is
the same class of silent-workspace-drop symptom.

### Added

- **``workspace_root`` argument on all 9 MCP tools.** Declared in every
  handler signature so FastMCP includes it in the ``inputSchema`` served to
  ``tools/list`` — agents now see it as a first-class parameter and its
  value reaches the resolution helper unchanged.
- **New ``django_orm_lens.workspace`` module.** Single home for resolution,
  path hardening, and caching. Priority chain: explicit argument →
  ``$DJANGO_ORM_LENS_ROOT`` → current working directory. A failure at any
  chosen source is surfaced immediately instead of falling through — that
  silent fall-through is exactly what produced the pre-1.3.0 bug.
- **Path hardening.** ``os.path.expanduser`` + ``expandvars`` +
  ``Path.resolve()`` collapses ``..`` traversal and follows symlinks before
  any validation. Windows reserved device names (``CON``, ``PRN``, ``AUX``,
  ``NUL``, ``COMn``, ``LPTn``) are rejected on every OS because paths flow
  between machines. Django-marker requirement (``manage.py`` /
  ``manage.pyw`` / ``django`` in ``pyproject.toml`` / any ``models.py`` in
  the tree) rejects agent typos before they scan the wrong directory.
- **Optional allowlist.** ``DJANGO_ORM_LENS_ALLOWED_ROOTS`` (``;``-separated
  on Windows, ``:``-separated elsewhere) restricts which prefixes the agent
  may resolve to. Empty / unset preserves the historical unrestricted
  behaviour.
- **Structured error envelope.** Every failure now returns
  ``{"error": "WORKSPACE_...", "message": "...", "hint": "...", "path": "..."}``
  as the tool result — agents get an actionable message instead of ``[]``.
  Stable error codes: ``WORKSPACE_EMPTY``, ``WORKSPACE_NOT_FOUND``,
  ``WORKSPACE_NOT_A_DIRECTORY``, ``WORKSPACE_NOT_DJANGO``,
  ``WORKSPACE_NOT_ALLOWED``, ``WORKSPACE_WINDOWS_RESERVED``,
  ``WORKSPACE_RESOLVE_FAILED``.
- **Compound cache key.** Index cache is now keyed by
  ``(resolved_absolute_path, manage.py mtime)`` — touching ``manage.py``
  invalidates on the next call without waiting for the 30 s TTL. Cache is
  LRU-capped at 8 workspaces so multi-project agents (Cursor with several
  folders open) can't unbounded-grow memory.
- **Tests:** ``test_mcp_workspace.py`` (23 unit tests: hardening, priority
  chain, allowlist, cache) + ``test_mcp_server.py`` (22 integration tests +
  18 subtests: registry contract, error envelope on every tool, happy path
  equivalence). Full Python suite: **236 passed** (up from 191), zero
  regressions. TS suite: 104/104 green (unchanged).

### Referenced upstream

- <https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem>
  — reference implementation of workspace hardening and containment (path
  resolve + allowlist), whose semantics this fix ports to Python.
- <https://github.com/modelcontextprotocol/servers-archived/tree/main/src/git>
  — reference example of per-tool ``repo_path`` argument that inspired the
  explicit-argument-first priority chain.
- <https://github.com/microsoft/AL/issues/8273>,
  <https://github.com/openai/codex/issues/9989>,
  <https://github.com/aws/aws-toolkit-jetbrains/issues/6173>,
  <https://github.com/kirodotdev/Kiro/issues/5662> — real-world reports of
  the identical silent-workspace-drop bug in adjacent MCP servers.
- <https://github.com/modelcontextprotocol/python-sdk/issues/1097> — the
  ``roots/list`` deadlock that motivated the deliberate choice to keep this
  release synchronous and defer MCP-roots integration.

## [0.9.0] - 2026-07-24

Schema-diff gets a first-class **partial UniqueConstraint** tracker. Inspired
by django-extensions [#1813](https://github.com/django-extensions/django-extensions/issues/1813)
(BoPeng, 2023) — `sqldiff` drops the `condition=` predicate from
`UniqueConstraint` output, so migration reviewers never see what actually
changed. Django ORM Lens now surfaces these as typed events so PR diffs stop
lying.

### Added

- **`PartialUniqueConstraint` schema-diff event with four ops:**
  - `add` — new conditioned `UniqueConstraint` appeared in the new snapshot
  - `drop` — constraint existed only in the old snapshot
  - `change` — same name, condition (or field list) mutated; `fromCondition`
    carries the pre-change predicate so the review comment can show
    `Q(is_primary=True) → Q(is_primary=True, deleted=False)`
  - `rename` — same fields + same condition, only the name changed; renamed
    constraints no longer show up as a lossy `add + drop` pair
- **Anonymous-safe.** Multiple unnamed constraints on the same model no longer
  collapse into a single event — internal keying falls back to `#anon-<index>`.
- **Markdown rendering** grew four dedicated bullet variants (`**added** …`,
  `**dropped** …`, `**changed** …`, `**renamed** …`) so the PR description
  reads like a review comment, not a raw diff.
- **Tests:** 4 new snapshot tests for each op variant (add / drop / change /
  rename). Schema-diff suite: 17/17 green; full TS suite: 104/104 green.

### Referenced upstream

- <https://github.com/django-extensions/django-extensions/issues/1813> —
  root-cause description + reproducer + workaround acknowledged in
  [comment #5062767387](https://github.com/django-extensions/django-extensions/issues/1813#issuecomment-5062767387).

## [0.7.8] - 2026-07-21

Marketplace SEO polish — no runtime changes, no behaviour changes. VS Code extension only (CLI/MCP unchanged, still on py-1.2.7).

### Changed

- **VS Code Marketplace metadata refreshed** for better discoverability.
  - `description` rewritten to lead with the value ("See your entire Django schema in your editor") instead of the feature list.
  - `categories` expanded from `[Visualization, Other]` → `[Visualization, Programming Languages, AI, Other]` to surface in more Marketplace filters.
  - `keywords` expanded from 7 → 29 with real search terms users type: `erd`, `entity relationship`, `schema visualizer`, `model explorer`, `foreign key`, `n+1`, `query optimization`, `mcp`, `ai agent`, `cursor`, `vscodium`, `postgresql`, `django-rest-framework`, and more.
  - Added `galleryBanner` (`#0c4b33` Django-green) — the extension page now has a themed header instead of default grey.
  - Added `qna: "marketplace"` (enable built-in Q&A) and `sponsor.url` (GitHub Sponsors link surfaced in the sidebar).
- **CI:** GHCR `Wait for PyPI` step widened 5 min → 15 min. The `py-v1.2.7` publish raced the PyPI CDN and the container step failed at the pip install; wider window makes future releases robust to slow PyPI propagation.

## [0.7.7] + [py-1.2.7] - 2026-07-21

### Fixed

- **UTF-8 BOM (`U+FEFF`) at the start of a models.py file no longer eats the whole class.** Windows editors — Notepad, older Sublime, VS Code with certain encoding settings — save files with a byte-order mark. Without this fix the first line becomes `"﻿class Foo..."` and `CLASS_RE` fails to match, so every model in the file silently disappears. Both parsers now strip the leading BOM in the content-read step.

### Added

- **`test_bom_prefix.py`** — 2 Python regression tests (BOM-prefixed file parses; no-BOM backward-compat).

## [0.7.6] + [py-1.2.6] - 2026-07-21

### Fixed

- **Tab-indented model bodies now parse.** Editors that default to tabs (or projects that use PEP-8 exceptions with tabs) had every field silently dropped. `FIELD_RE` uses `\s{indent}` as its column prefix and `_detect_class_indent` correctly returns width 4 for tabs, but a single `\t` character is only one `\s` match, not four. Fixed by pre-expanding tabs to 4 spaces in the line buffer before regex matching. Applies to both parsers. Line numbers preserved (per-line expansion only).

### Added

- **`test_tab_indented_models.py`** — 3 Python regression tests (pure-tab body, mixed tab+space, and space-indent backward-compat).

## [0.7.5] + [py-1.2.5] - 2026-07-21

Two more field-detection gaps closed via targeted fuzz of realistic Django user code.

### Fixed

- **Aliased `models` module.** `from django.db import models as m` followed by `class X(m.Model): x = m.CharField(...)` used to lose every field because `FIELD_RE` hardcoded the `models\.` prefix and `BARE_FIELD_RE` had no prefix allowance. Both parsers now accept any single-identifier prefix on the RHS in `BARE_FIELD_RE`.
- **Third-party field packages.** Fields declared via a namespaced third-party import (`x = jsonfield.JSONField(...)`, `x = timezonefield.TimeZoneField(...)`, `x = arrayfield.ArrayField(...)`) fell through the same gap. Same fix covers both cases in one edit — the type name is still restricted to Django's known field whitelist, so random non-Django calls like `foo.CharField(...)` in an unrelated module don't leak in.

### Added

- **`test_aliased_module_and_third_party_fields.py`** — 4 Python regression tests (aliased-only, mixed aliased+plain+bare interleaved, jsonfield-style third-party, and backward-compat bare imports).

## [0.7.4] + [py-1.2.4] - 2026-07-21

Follow-up to the modern-Python audit that produced 0.7.3 — another shape of typed code that used to silently vanish, surfaced by a targeted fuzz of the class-header regex.

### Fixed

- **PEP-695 generic class headers (Python 3.12+) now parse.** The class-header regex was:

  ```
  ^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*:
  ```

  which had no allowance for a `[T]` group between the class name and the opening `(`. Any model declared as `class Container[T](models.Model):` failed to match — the parser walked past the whole class, no models reported, empty sidebar / ER diagram / n+1 output. Applies to all four common PEP-695 shapes: single-param `[T]`, multi-param `[K, V]`, bounded `[T: str]`, and variadic + paramspec `[*Ts, **P]`.

  Fixed by inserting an optional `(?:\s*\[[^\]]*\])?` group in both `CLASS_RE` and `CLASS_START_RE`, in both parsers (Python + TypeScript). Non-generic classes match identically as before.

### Added

- **`test_pep695_generic_classes.py`** — 5 Python regression tests covering the four PEP-695 shapes plus a backward-compat guard for plain class headers.

## [0.7.3] + [py-1.2.3] - 2026-07-20

Bugfix release for [#25](https://github.com/FROWNINGdev/django-orm-lens/issues/25) — thanks to [@jsabater](https://github.com/jsabater) for the reproducible report against a Django Ninja 1.6 codebase.

### Fixed

- **Fields with PEP-526 type annotations (typed Django / Django Ninja style) no longer disappear from the parser output.** When code uses the modern typed pattern:

  ```python
  jti: CharField[str] = models.CharField(max_length=32, unique=True)
  ```

  the field regex expected `name = models.X(` and had no allowance for a `: <type>` group between the name and the `=`. Result: fields silently vanished from the sidebar tree, the ER diagram entity, and every downstream tool (n+1 detector, MCP `describe_model`, `find_relations`). Adding fields one-by-one made the whole model progressively empty — the exact reproduction jsabater observed.

  Fixed in both parsers (`parser.py::_build_body_regexes`, `src/parser.ts::buildBodyRegexes`) by adding an optional `(?:\s*:[^=]+)?` group after the field name and before `=`. `[^=]+` is safe because `=` never appears inside a Python type expression (subscripts, unions, dotted refs, and generics all use other punctuation). Applied consistently to `FIELD_RE`, `BARE_FIELD_RE`, and `META_ITEM_RE`.

### Added

- **`test_pep526_type_hints.py`** — 6 Python regression tests covering the exact snippet from the bug report, the bare-import form (`IntegerField` without `models.` prefix), simple non-generic annotations (`label: str = ...`), untyped backward-compat, and a Meta block with an annotated attribute (`ordering: list[str] = ["title"]`).
- **`test/pep526.test.js`** — matching TS regression so the VS Code extension stays behaviour-compatible with the CLI.

## [py-1.2.2] - 2026-07-20

CLI welcome UX — bidirectional discoverability between PyPI and the editor extensions. Data motivation: PyPI is doing ~1,663 installs/week while the VS Code Marketplace sits at ~10 installs total. Users who install the CLI don't know the extension exists (and vice-versa in the extension welcome view). This closes the gap.

### Changed

- **`django-orm-lens` welcome (no-arg run)** now prints a "prefer a visual sidebar + ER diagram in your editor?" block after the docs link, with copy-paste install commands for both marketplace paths:
  - `code --install-extension frowningdev.django-orm-lens` — VS Code / Cursor / Windsurf
  - `codium --install-extension frowningdev.django-orm-lens` — VSCodium / code-server / Gitpod / any OSS Code fork (via Open VSX)

  Rest of the welcome (commands table + star CTA) is unchanged.

## [py-1.2.1] - 2026-07-20

Patch release — two crash bugs in the CLI wrapper that unit tests missed because they exercised the underlying helpers directly instead of going through argparse dispatch. Both surfaced during an end-to-end smoke run against a real Django codebase.

### Fixed

- **`django-orm-lens nplusone` crashed with `NameError`** — `_cmd_nplusone` called `_build_schema_from_index` and `scan_for_nplusone` without importing either at module scope. `scan_for_nplusone` now imported at the top of `cli.py`; the intermediate schema flattening is dropped (the underlying function already accepts a `WorkspaceIndex` and normalises internally via `_normalise_schema`).
- **`django-orm-lens migration-risk` (text format) crashed with `AttributeError: 'MigrationRisk' object has no attribute 'filePath'`** — the print statement used camelCase attrs (`filePath` / `lineNumber`) but the dataclass fields are snake_case (`file_path` / `line_number`). The camelCase form only exists inside `to_dict()` (JSON path); text output now reads the snake_case fields directly.
- **`analyze_migration_risks` was not imported at module scope** — same pattern as the nplusone bug, fixed at the same time to prevent a latent `NameError` on the next code path change.

### Added

- **`test_cli_subcommands_smoke.py`** — 8 tests that dispatch every subcommand (`scan`, `list`, `er`, `describe`, `hover`, `nplusone`, `migration-risk` text + JSON) through `main([...])` against fixture data. Any `NameError` / `ImportError` / `AttributeError` in a subcommand body now surfaces as a test failure rather than a crash the next user sees. This closes the coverage gap that let both v0.7.0 bugs ship.

## [0.7.0] + [py-1.2.0] - 2026-07-20

Correctness release focused on `settings.AUTH_USER_MODEL` resolution across every layer (parser / signals / query analyzer / ER diagram / MCP server / VS Code webview) and kwarg-order-independent field parsing. 10 bugs closed + 4 DRY/perf refactors + 36 new regression tests. All 157 Python tests + 3 TypeScript tests green.

### Fixed

- **`ForeignKey(on_delete=CASCADE, to='User')` now resolves correctly regardless of kwarg order.** Both the Python (`_extract_related` in `parser.py`) and TypeScript (`extractRelated` in `src/parser.ts`) parsers previously used a positional-first regex that either returned `undefined` or misread `on_delete` as the target when `to=` wasn't the first kwarg. Python side now uses `ast.parse` on the wrapped arg block; TypeScript side prefers `\bto=` anywhere and falls back to positional-first with a negative lookahead against kwargs. Similar order-independence applied to `_extract_on_delete` / `_extract_related_name` / `_extract_through_model`.
- **`settings.AUTH_USER_MODEL` resolves to the workspace User model in every consumer, not just the MCP layer.** Previously, `.split('.')[-1]` produced `"AUTH_USER_MODEL"` — a name no workspace model carries — dropping User-model edges from: reverse-relation schema used by the n+1 detector (`query_analyzer._build_schema_from_index` + `_build_schema_from_index_dict`), signal receiver resolution (`signals_parser._resolve_sender`), Mermaid ER diagram (`cli._build_mermaid`), VS Code Mermaid webview (`src/graphWebview.ts`), VS Code inbound-relation panel (`src/extension.ts`), and the React ER webview (`src/webview/graph.tsx`). All six paths now delegate to shared `resolve_related_tail` (Python) / `resolveRelatedTail` (TypeScript). The webview additionally receives the pre-resolved User name via the wire payload so it doesn't need `baseClasses` shipped over.
- **`--verbose` no longer walks the workspace twice.** The scan summary previously called `_iter_python_files` a second time just to count files. `WorkspaceIndex` now carries `scanned_files` (populated by `scan_workspace`), so verbose mode reads the count instead of re-iterating — noticeable on large monorepos.
- **`formatters._render_table` no longer crashes on short rows.** A row shorter than the header triggered `IndexError` inside the width-computation genexpr. Rows are now padded with `""` to header width before rendering.

### Added

- **Shared Python helpers under `django_orm_lens` package root:** `find_user_model`, `find_user_model_from_dict`, `resolve_related_tail`, `find_model`, `iter_workspace_py_files`, `BROAD_SKIP_DIRS`. Downstream tools that build on the parser can import these without duplicating the User-model detection heuristic or the walk-skip-list.
- **Shared TypeScript helpers in `src/parser.ts`:** `findUserModel(index)`, `resolveRelatedTail(related, userName)`. Same shape as the Python side so the VS Code extension and the CLI stay in sync.
- **`WorkspaceIndex.scanned_files: int`** — number of `models.py`-style files inspected during the scan. Surfaced in `to_dict()` as `scannedFiles`. Backward-compatible (default 0, extra JSON key).
- **`WireIndex.userModelName?: string`** in `src/webview/types.ts` — resolved User model name shipped to the React webview so it can rewrite `settings.AUTH_USER_MODEL` edges to point at the right node.
- **36 regression tests:** `test_kwarg_order_and_auth_user.py` (35 unit tests covering kwarg-order-independent extractors, User-model discovery, tail resolution, schema-building with AUTH_USER_MODEL, `_resolve_sender` cases) + `test_signals_parser::test_receiver_settings_auth_user_sender_resolves` (E2E `signal_graph`) + `test/kwarg-order.test.js` (TS regression).

### Changed

- **`_iter_py_files` consolidated across three modules.** `signals_parser`, `query_analyzer._iter_py_files`, and `query_analyzer._iter_py_files_broad` were three near-identical copies of the same directory walk with slightly different skip-lists. All three now delegate to `parser.iter_workspace_py_files(root, extra_skip=frozenset())`.
- **`_find_model` / `_find` consolidated.** `cli._find_model` and `mcp_server._find` were near-identical `WorkspaceIndex` lookups by `"app.Model"` or bare `"Model"`. Both now delegate to `models.find_model` so lookup semantics stay in sync.
- **`mcp_server._workspace_user_model` and `_rel_matches_target`** are now thin wrappers over the shared `find_user_model` + `resolve_related_tail`. Semantics unchanged; the tuple-returning signature of `_workspace_user_model` is preserved for existing callers.

## [0.6.0] + [py-1.1.0] - 2026-07-19

Feature release — three new CLI subcommands (`nplusone`, `migration-risk`, `diff`), webview polish, and three README translations. 127 tests passing.

### Added

- **CLI `nplusone` subcommand — static N+1 detector.** Walks `.py` files and flags queryset iteration where FK / M2M attributes are accessed inside the loop without a matching `.select_related(...)` / `.prefetch_related(...)`. Schema-backed high-confidence classification when a workspace index is available, heuristic medium-confidence fallback otherwise. Reports `file:line`, loop variable, queryset variable, accessed relations, and a suggested fix. Flags: `--path`, `--format text|json`, `--confidence high|medium|all`, `--exit-zero`. Exit code 1 on findings (CI-friendly). 18 tests.
- **CLI `migration-risk` subcommand — production-safety linter for Django migrations.** Analyzes `<app>/migrations/*.py` files and flags seven classes of risky operations: `AddField(NOT NULL, no default)`, `RemoveField`/`DeleteModel` still referenced by live code, `RenameField`/`RenameModel` (breaks rolling deployments), `AddIndex` without `CONCURRENTLY`, lossy `AlterField` type changes, `RunSQL` without `reverse_sql`, and `AddField(unique=True)` without a row-unique default. Cross-references the current models schema. Per-finding severity (`critical` / `warning` / `info`) and confidence (`high` / `medium` / `low`). Flags: `--path`, `--format text|json`, `--severity critical|warning|info|all`, `--exit-zero`. 31 tests.
- **CLI `diff` subcommand — compare two schema JSON dumps.** `django-orm-lens list --format=json > before.json` on `main`, then again on a PR branch → `after.json`, then `django-orm-lens diff before.json after.json` prints added / removed models, added / removed / changed fields, and added / removed / changed relations. Text and JSON output. Exit 1 on any delta (git-diff-like), `--exit-zero` for advisory CI stages. 21 tests.
- **Webview: color-code minimap dots by app.** ER-diagram minimap now tints nodes by their owning Django app using a deterministic FNV-1a-based hue, so large schemas can be visually grouped at a glance. Focused node retains the accent color.
- **CLI `list` subcommand now supports `--format json`.** `django-orm-lens list --format json` emits a pipe-friendly JSON array `[{"app": "...", "model": "..."}, ...]`. The default `text` output remains unchanged for backward compatibility.
- **`--verbose` / `-v` flag** on every scan-backed CLI subcommand (`scan`, `describe`, `hover`, `list`, `er`). Prints a one-line summary to stderr after the scan — `scanned 12 files in 34ms, found 8 apps / 47 models` — sourced from the actual file walk, a `time.perf_counter()` measurement around the scan, and the real app/model counts on the returned index. Stdout is untouched either way. (#14)
- **CLI: friendlier hint when no `models.py` is found.** `scan`/`describe`/`hover`/`list`/`er` previously printed a silently-empty result. When zero models are found *and* no `models.py`/`models/*.py` file was walked at all, a `hint: no models.py found under <path>...` line is now printed to stderr (stdout stays clean, exit code stays `0`). New `--quiet`/`-q` flag suppresses the hint. (#12)

### Docs

- **README translations:** `README.ru.md` (Russian), `README.es.md` (Spanish), `README.zh.md` (Chinese). Language switcher added at the top of each file. Closes #9, #10, #11.
- **README: added Screenshots section** between Install and The problem, with capture instructions for six product screenshots covering VS Code (sidebar / ER diagram / hover card), CLI (`list`, `er`), and MCP (Cursor conversation). Closes #15.

## [0.5.1] + [py-1.0.17] - 2026-07-16

Bugfix release focused on parser accuracy and MCP correctness. E2E audit against a synthetic Django project with abstract mixins, custom user model, multi-file `models/` packages, real migrations, signals, and views uncovered five real bugs that would have hit the ~60 % of production Django codebases that use `TimeStampedModel`-style mixins or `settings.AUTH_USER_MODEL`. All fixed here without any behavioural regressions (44 pytests pass — 13 new + 31 pre-existing).

### Fixed
- **Abstract-mixin subclasses now correctly identified as models.** `class Profile(TimeStamped)` where `TimeStamped(models.Model)` is a user-defined abstract base was previously invisible to every tool — parser only walked one inheritance level and only against a small hardcoded list of known-Model tails. `parse_models_file` is now two-pass: first collects every class definition with its bases + Meta, then resolves transitive inheritance via fixed-point iteration. Any concrete subclass of any class that transitively inherits from `models.Model` (through arbitrary user-defined abstracts) is now returned.
- **`Meta.abstract = True` is now respected.** Abstract mixins previously appeared in `list_models`, `describe_model`, ER diagrams, and the VS Code sidebar as if they were concrete tables. They are now filtered out, matching what Django itself does at migration time.
- **`settings.AUTH_USER_MODEL` now resolves to the workspace User model in relation lookups.** `cascade_preview(accounts.User)` and `find_relations(accounts.User)` previously returned empty inbound arrays even when other models had `ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE)` — the recommended Django pattern. MCP layer now detects the workspace's User model (first class inheriting `AbstractUser` / `AbstractBaseUser`, else literal `User`) and treats `AUTH_USER_MODEL` refs as pointing at it.
- **`--version` shows the real installed version.** Previously hardcoded `1.0.7` across nine releases regardless of which package version was actually installed — confusing bug reports. Now sourced from `importlib.metadata` at import time.
- **CLI subcommands error on a non-existent `--path`.** `list --path /nonexistent` previously exited `0` with empty output — silent failure. Now prints `error: --path 'X' is not a directory` to stderr and exits `2`.
- **`list_models(app='wrong_name')` returns a helpful error instead of `(no models)`.** New response: `(app 'wrong_name' not found in workspace; available apps: a, b, c)`.

### Changed
- **MCP Registry description updated:** `"5 read-only tools"` → `"9 read-only tools (models, relations, cascade, migrations, indexes, signals, ER diagram)"`. Registry entry was stuck at 1.0.7 and had never reflected the four v0.4/v0.5 additions (`describe_migration_dependency`, `suggest_indexes`, `signal_graph`, `er_diagram`).

### Added
- **13 regression tests** for the fixes above under `cli/tests/test_abstract_and_auth_user.py` — abstract-drop, two-level abstract chain, plain `User` reference, `AbstractUser` subclass detection, `settings.AUTH_USER_MODEL` resolution, and negative cases (no user model, wrong target). Guards against regressions in the parser's inheritance logic and the MCP resolution helpers.

## [0.5.0] + [py-1.0.16] - 2026-07-16

MCP tools for AI-agent Django expertise. Ships three flagship additions built on the zero-runtime static-analysis moat: two new MCP tools that solve the top pain points in the Django tooling ecosystem — index recommendations and signal graph visualisation — plus a golden-fixture test suite that proves the parser survives real-world Django code (63 models across Zulip, Saleor, Wagtail, django-CMS). Positioning shifts from "ER diagram + navigation" to "the static-analysis brain that Django AI agents plug into."

### Added
- `suggest_indexes(app_label, model_name)` MCP tool — static analysis of every filter/exclude/order_by/get/aggregate usage across the workspace, returns field-usage frequency and proposes `Meta.indexes` covering entries. Zero-runtime, no DB, no Django boot. Solves the top Django performance blind spot for AI coding agents.
- `signal_graph()` MCP tool — parses every `@receiver()` decorator and `Signal()` definition in the workspace, returns the sender→signal→handler DAG plus custom-signal send-sites. Surfaces the invisible connections between models that cause the majority of enterprise Django bugs.
- **Golden fixture suite** — parser now tested against real open-source Django projects: Zulip (Apache-2.0, 33 models across `zerver/models/`), Saleor (BSD-3, 19 models across product/order/discount/warehouse), Wagtail (BSD-3, 8 models from `wagtail/models/`), and django-CMS (BSD-3, 3 models from `cms/models/`). Pytest asserts every project scans without error, finds at least 1 model, and the aggregate scan of all vendored fixtures completes under 2 seconds (currently ~11 ms). Credibility: `django-orm-lens` is proven against 63 total models parsed from real-world Django deployments, not synthetic examples. Fixtures live under `cli/tests/fixtures/golden/<project>/<original-path>/models.py` with attribution + fetch date in that directory's README.md.

## [0.4.2] - 2026-07-16

Hotfix. Extension only.

### Fixed
- **Activity-bar icon actually ships in the VSIX now.** A stray `media/*.svg` line in `.vscodeignore` (introduced during the 0.4.0 React Flow packaging pass) silently excluded `media/activitybar.svg` from the published extension. The branded icon rendered in Extension Development Host (files read from repo path directly) but was completely absent from the Marketplace VSIX — VS Code had nothing to draw, so the sidebar slot appeared blank. Ignore pattern replaced with an explicit whitelist (`!media/**/*.png`, `!media/**/*.svg`, `!media/webview/**`).

## [0.4.1] - 2026-07-16

VS Code extension only. Python CLI unchanged.

### Changed
- **Branded activity-bar icon** — replaced the generic Material database cylinder (which rendered as an apparently blank slot at 24×24 in some VS Code themes) with a three-connected-tables silhouette that reads unambiguously as "ORM schema" at any size. Uses `stroke="currentColor"` so the icon inherits VS Code's activity-bar foreground colour on every theme (dark/light/high-contrast). Reload the VS Code window after updating to pick up the new icon — VS Code caches activity-bar SVGs per extension host.

## [0.4.0] + [py-1.0.15] - 2026-07-16

Major visual upgrade for the ER diagram — the VS Code webview now renders every model as an interactive React Flow node instead of a static Mermaid SVG. Drag models around to lay the diagram out the way you think about it, click a node to highlight its inbound and outbound relations, double-click to jump straight to the class in `models.py`. Edges are colour-coded by relation semantics (ForeignKey CASCADE / SET_NULL / PROTECT, OneToOne, ManyToMany with `through=` label) so the on_delete blast radius is visible at a glance. Ships with a minimap, zoom controls, and PNG / SVG export. Automatic hierarchical layout via `elkjs`. Python CLI is unchanged in behaviour — the version bump keeps the extension and CLI shipping together, and the Mermaid emitter (`build_mermaid`) remains available for the CLI `--mermaid` output.

### Added
- **Interactive ER diagram (React Flow)** — replaces Mermaid rendering in the VS Code webview. Draggable nodes with rounded corners, drop shadow, and Inter-family typography. Each node shows `app · Model` header and every field with a colour-coded badge (FK / 1:1 / M2M / plain). Edges are laid out with `elkjs` layered algorithm (`RIGHT` direction, orthogonal routing) so hierarchies read naturally instead of the force-directed mush the previous Mermaid `erDiagram` rendered as workspace size grew.
- **Click-to-focus highlighting** — clicking any model dims unrelated nodes to 35 % opacity, keeps the selected node plus every connected neighbour at full brightness, and animates its edges. Click empty canvas or the same node again to clear.
- **Double-click to jump to source** — double-clicking a node posts `jumpToModel` back to the extension, which opens the `models.py` file in the primary editor column at the model's class line. Reuses the existing message handler contract from the Mermaid webview.
- **PNG + SVG export** — new Export dropdown in the header uses `html-to-image` to serialise the diagram viewport at 2× pixel ratio (PNG) or as inline SVG. Falls back to VS Code's `showSaveDialog` for the target path.
- **MiniMap + zoom controls** — bottom-right minimap (150×100) with the current selection highlighted in the accent colour; bottom-left React Flow zoom controls (zoom in / out / fit view). Both surfaces inherit VS Code panel colours via CSS variables and use a subtle `backdrop-filter: blur(6px)` for the Linear/ChartDB aesthetic.
- **Relation-kind legend** — small footer chip explains the FK CASCADE / SET_NULL / PROTECT / 1:1 / M2M colour palette so you don't have to guess.

### Changed
- **Webview build pipeline now uses esbuild.** New `npm run build:webview` bundles `src/webview/graph.tsx` → `media/webview/graph.js` as a minified IIFE (~1.85 MB raw / ~565 KB gzipped, well under the 3 MB VSIX budget). `npm run build` runs both `build:extension` (tsc) and `build:webview` (esbuild). The webview source under `src/webview/` is excluded from the extension's `tsc` project via `tsconfig.json`.
- **Webview header rebuilt to Linear/Vercel spec** — 48 px tall, subtle 2 px gradient bottom border (`transparent → focus → transparent`), workspace name in the title, app + model count badge, refresh button, and export dropdown.
- **`diagramTheme` config values `default` / `forest` / `neutral` now collapse to the `light` React Flow palette.** The old Mermaid-specific enum values are still accepted for setting compatibility but no longer produce distinct visuals — Mermaid is the only renderer that had those. `auto` and `dark` behave as before.

### Kept
- **Mermaid vendored file (`media/vendor/mermaid.min.js`) stays in the VSIX** in case a user needs to roll back to v0.3.8 by re-enabling the old renderer.
- **CLI `build_mermaid` emitter is unchanged.** The Python CLI still exposes `--mermaid` for terminal / CI consumers, so agents and pipelines that scrape the Mermaid output are unaffected.

## [0.3.8] + [py-1.0.14] - 2026-07-16

Second hotfix on the two 0.3.6 regressions that 0.3.7's partial fix did not fully resolve for users running a single-app workspace ("hello/" opened at the app root). Icon rendered blank on some installs even after the theme-aware SVG rewrite; the workspace scan still came up empty on cold-start when `vscode.workspace.findFiles` returned no results before the file index was warm. This release simplifies the icon glyph and adds a direct filesystem walker fallback so the scan never depends on the file index being ready.

### Fixed
- **Activity-bar icon is now a single centred database glyph that fills the 24×24 canvas.** The v0.3.7 SVG was already `fill="currentColor"`, but the two-shape database + magnifier composition left large empty margins on the left and top, which on some themes (and at some HiDPI scale factors) rendered as an apparently blank slot in the activity bar. Replaced with a codicon-shaped monochrome database drawn from x=4 to x=20, y=2 to y=22 — visually dense across the whole viewbox and unambiguously visible on every theme.
- **Workspace scan now falls back to a direct filesystem walk when `findFiles` returns empty.** Root cause: `vscode.workspace.findFiles` depends on VS Code's internal file index. On `onStartupFinished` activation the index can be cold, and on some Windows single-folder-workspace setups the `**/models.py` glob silently misses depth-0 `models.py` regardless. v0.3.7 tried to work around this by adding a bare `models.py` `RelativePattern` and a 1.5s startup-retry backstop; both still failed for users who open the Django app folder itself. `scanWorkspace` now runs `findFiles` first as the fast path, and if it returns zero URIs walks each workspace folder with `fs.readdirSync` directly, honouring the same exclude-glob defaults (`**/migrations/**`, `**/venv/**`, ...). Fallback runs once per empty scan — no cost when the file index is warm.

### Tests
- Added `cli/tests/test_scan_root.py` — three regression tests covering "app-as-workspace-root" (models.py at depth 0), "project-as-workspace-root" (app one level down), and the `**/migrations/**` exclude at root depth. Locks in that the shared parser behaviour never regresses on the single-app layout.

## [0.3.7] + [py-1.0.13] - 2026-07-16

Hotfix release — closes the two regressions reported against 0.3.6: the activity-bar icon rendered blank (stroke-based SVG that VS Code's activity-bar CSS couldn't theme reliably), and single-app workspaces opened at the app root ("hello/" containing `models.py` directly) came up empty because the include-glob and initial-scan timing both failed the root-file case. TypeScript extension fixes only; Python CLI + MCP server are re-published at the same version for combined-release parity.

### Fixed
- **Activity-bar icon is now visible on every theme.** The previous SVG was a stroke-based line drawing with `fill="none"` on both the root and every shape. VS Code's activity-bar renderer applies its own theme foreground via `fill: currentColor`, which the inline `fill="none"` overrode — the icon rendered as a blank slot on most themes ("I see the panel open but the sidebar icon is gone" — real user report). Icon is now a fill-based database + magnifier drawn with `fill="currentColor"`, matching the codicon convention for activity-bar entries.
- **Workspace with `models.py` at the root now scans on activation.** Two root causes: (1) `vscode.workspace.findFiles('**/models.py', ...)` was expected to match root-level files, but on some setups (notably single-folder workspaces on Windows) the leading `**/` requires at least one path segment and silently skipped `<root>/models.py`. Now uses a `vscode.RelativePattern` per workspace folder with an explicit `models.py` include alongside `**/models.py` and `**/models/*.py`, de-duplicated on `fsPath`. (2) With `onStartupFinished` activation (added in 0.3.6) the initial `refresh()` can race the workspace file index and return zero results before it's warm. Now also re-scans on `TreeView.onDidChangeVisibility` (user clicks the sidebar), on `workspace.onDidChangeWorkspaceFolders`, and once as a 1.5s startup backstop if the first scan came back empty against a non-empty workspace. Manual `Refresh scan` from the welcome view is unaffected and continues to work.

## [0.3.6] + [py-1.0.12] - 2026-07-16

Combined release — migration-dependency debugger for AI agents, always-visible activity-bar icon with empty-state welcome, and a subtle star-ask on MCP startup. Ships the three feature commits accumulated since 0.3.5: the migration DAG tool closes a gap no other Django MCP server addresses (agents can now trace conflict chains without booting Django), while the UX and star-ask improvements close the discoverability/conversion loop between install and star.

### Added
- `describe_migration_dependency` MCP tool — return per-app migration DAG (dependencies, roots, leaves, cross-app deps) from static AST parse, no Django boot. Standout differentiator: no other Django MCP server or graph tool (django-schema-graph, django-extensions graph_models, gts360/django-mcp-server, kitespark/django-mcp, admin-mcp-api) offers migration-conflict introspection without a running Django process.

### Changed
- **MCP server prints a one-line star-ask on startup** (stderr). Mirrors the CLI welcome convention from py-1.0.9. Zero effect on the JSON-RPC protocol (stderr is out-of-band); surfaces in Cursor, Aider, mcp-inspector, and any client that shows server logs.

### Fixed
- **Activity-bar icon now appears on any workspace, not only Django ones.** Previously the extension activated exclusively on `workspaceContains:**/manage.py` or `workspaceContains:**/models.py`, so a user who installed the extension without a Django project open saw no icon and no way to discover the tool ("I installed it and see nothing" — real user report). Added `onStartupFinished` to `activationEvents` so the icon always renders; added a `viewsWelcome` empty-state message explaining the tool looks for `manage.py` / `models.py`, with quick actions to open a folder, refresh the scan, or read docs on GitHub. Django auto-activation on those files is unchanged.

## [0.3.5] + [py-1.0.11] - 2026-07-15

Combined release — Django 5.2 support, cascade blast-radius preview for AI agents, and a reverse-references sidebar action. Feature-set derived from a competitive analysis of `meshy/django-schema-graph` (stale since 2023, Django ≤ 4.1) and MCP peers (`gts360/django-mcp-server`, `kitespark/django-mcp`) — all of which require a running Django process; django-orm-lens keeps the zero-runtime moat.

### Added
- **Django 5.2 support** — new `Framework :: Django :: 5.2` classifier and a CI matrix job (`python-cli`) that runs pytest against Python 3.10-3.12 × Django 4.2-5.2 in parallel with the existing Node/TS build.
- **`cascade_preview` MCP tool** — new tool `cascade_preview(app_label, model_name)` returns inbound relations grouped by `on_delete` behavior into `cascade_kills` / `set_null` / `protected` buckets. Lets AI agents preview a delete's blast radius before acting, using only static parse (no DB, no boot).
- **`on_delete` on inbound relations** — `find_relations` inbound entries now include the `on_delete` value (`CASCADE`, `SET_NULL`, `PROTECT`, `SET_DEFAULT`, `DO_NOTHING`, `RESTRICT`, or `SET` for callable form) extracted via the existing parser helper.
- **VS Code: "Find Reverse References" context action** — right-click any model in the sidebar tree → `Find Reverse References` → QuickPick of every FK/OneToOne/M2M pointing at this model, using the in-memory workspace index (no re-parse).
- **`[full]` optional-dependencies alias** — `pip install "django-orm-lens[full]"` is now equivalent to `[mcp]`; documents the default install as zero-dependency in a pyproject header comment.

### Changed
- **README hero** — added `Works offline. Works on a broken venv. Works on someone else's laptop. Works in CI.` positioning line under the problem section.
- **README comparison table** — added Django version support row (ours 4.0-5.2 · schema-graph 3.2-4.1 stale since 2023 · django-extensions latest) with an explicit stale-since-2023 note for `django-schema-graph`.

## [0.3.4] + [py-1.0.10] - 2026-07-15

Combined release — the parser hardening ships identically in both the VS Code extension and the Python CLI. Product of a 3-round security + stability + type-design + Django-semantics audit.

### Added
- **`on_delete=models.SET(default_value)` callable form now recognised** — previous regex `[A-Z][A-Z_]+` matched only bare identifiers (`CASCADE`, `SET_NULL`, `PROTECT`, etc.) and silently dropped the callable form used to inject a default value on delete. Parser now falls back to matching `on_delete=SET(` and records `"SET"`, so consumers know the field has a dynamic on_delete rather than treating it as absent.

### Security
- **ReDoS clamp on class-indent detection** — `_detect_class_indent` now clamps the reported indent width to 32 and expands tabs to width 4 before use. A crafted `models.py` with an absurd number of leading spaces (10k+) or a tab that produced a width-mismatched regex could previously build patterns like `\s{20000,}` for the meta-body match and trigger catastrophic backtracking. Fixes both the ReDoS vector and the tab-indent correctness bug (Meta blocks in tab-indented codebases were silently unparsed).

### Fixed
- **Workspace scan no longer aborts on a single broken `models.py`** — `scan_workspace` (Python CLI) and `scanWorkspace` (VS Code extension) previously wrapped both the read AND the parse in one broad try/catch. A parser exception in a single file (e.g. missing `(` after a matched field, malformed multi-line class header) would either abort the whole workspace scan with exit 1 (Python) or silently drop that file's models from the tree (TypeScript). Now the read and parse are caught separately: parse errors log a per-file warning to stderr (Python) or dev-tools console (TypeScript) and scanning continues on the next file.
- **Multi-line class header parser no longer near-loops on malformed signatures** — `_read_multiline_class` used to return `None` when parens closed but the joined buffer didn't match `CLASS_RE`. The caller would then advance by only one line, causing every continuation line of a malformed wrap to be re-evaluated as a potential class header. Now returns `(None, end_index)` so the caller skips past the whole section.
- **`_read_balanced_args` guard for missing `(`** — if a matched field somehow doesn't have `(` on its starting line, `.index("(")` used to raise `ValueError` that propagated out of `parse_models_file` and aborted the entire scan. Now returns an empty args block and the field is captured with no relation metadata.
- **Message handler disposable leak in the ER-diagram webview** — `panel.webview.onDidReceiveMessage(...)` registered its subscription in `context.subscriptions`, but the handler is scoped to the panel's lifetime, not the extension's. Every close/reopen of the diagram panel appended a dead listener to `context.subscriptions` forever. Handler now scoped to the panel's `onDidDispose` cleanup.
- **Watcher listener leak on `autoRefresh` config change + split-module files not watched** — `setupWatcher` disposed the old watcher on config toggle but left the three `onDidChange/Create/Delete` listeners registered in `context.subscriptions` permanently, firing against a disposed watcher. Now tracks a module-level `watcherDisposables` array that fully disposes before re-registering. Same pass also adds a second watcher for `**/models/*.py` — split-module Django apps' sub-files now trigger auto-refresh on save (previously ignored, tree silently went stale on those files).
- **Model-name collision in filtered tree** — two models sharing a name in different apps (a valid Django pattern) collided in the filtered-tree child lookup because identity was matched by `label + kind` only. Now also compares `filePath`, so children resolve to the correct model.

## [0.3.3] - 2026-07-13

### Security
- **Mermaid bundled locally instead of fetched from a CDN** — the ER-diagram webview now loads `mermaid.min.js` from a vendored copy at `media/vendor/`. The `script-src` CSP no longer allows `https://cdn.jsdelivr.net`, and `localResourceRoots` restricts the webview to files under `media/`. Removes a third-party network dependency, works offline, and eliminates supply-chain risk from the CDN.

## [0.3.2] - 2026-07-13

### Security
- **`jumpToModel` workspace check hardened** — the previous manual `.toLowerCase()` prefix comparison was Windows-oriented and could false-positive on case-sensitive filesystems (Linux). Switched to `vscode.workspace.getWorkspaceFolder(uri)`, which VS Code resolves with OS-appropriate case handling. Simpler code, correct on every platform.

## [py-1.0.9] - 2026-07-14

Python package only. VS Code extension unchanged at 0.3.3.

### Added
- **Subtle star ask in the welcome output** — `django-orm-lens` (no args) now closes with a two-line invitation to star the repo if the tool saved a search. Rationale: 134 unique cloners on the 14-day traffic window converted to only 2 stars — infrastructure tools bleed stars silently because users never revisit the repo after `pip install`. A single sentence at the point of first-run gratitude is the smallest touch that closes the loop without becoming spam. No CLI behaviour change.

## [py-1.0.8] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.3.

### Added
- **Friendly welcome when `django-orm-lens` runs without a subcommand** — previously bare invocation printed a cryptic `argparse: the following arguments are required: command` error, killing the pip-install-and-poke-around funnel. Now shows a compact commands table + docs link so a new user immediately sees what to try next.

## [py-1.0.7] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.1.

### Added
- **Mermaid ER edge labels — Python ↔ TypeScript parity** — `django-orm-lens er` and the MCP `er_diagram` tool now emit the same `on_delete`, `through`, and `related_name` metadata as the VS Code diagram. Example: `Book }o--|| Author : "author [CASCADE, as books]"` and `Book }o--o{ Tag : "tags [through BookTag]"`. Previously the Python side stripped all metadata to just the field name.
- **MCP index cache (30s TTL)** — agents chaining multiple tool calls (`list_apps` → `describe_model` → `find_relations`) no longer re-walk the filesystem and re-parse every `models.py` per call. Cache keyed by workspace root; short TTL keeps manual edits visible.

## [py-1.0.6] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.1.

### Changed
- **MCP tool error semantics** — `describe_model` and `find_relations` now raise `ValueError` on missing-model instead of returning a `"error: ..."` string. FastMCP maps this to a protocol-level `isError: true` response, so MCP-compatible agents recognize it as a tool error rather than a successful call with error text.

### Fixed
- **Parser perf** — `_read_balanced_args` was building the args buffer with per-char `str += ch` inside a nested loop (quadratic on multi-line field bodies). Now uses a list + single `"".join`.

## [py-1.0.5] - 2026-07-13

Hotfix release. Python package only. VS Code extension unchanged at 0.3.1.

### Fixed
- **Crash on `ManyToManyField(through=...)`** — `_extract_through_model` was called from `parse_models_file` but never defined, and `through_model` was assigned on `ParsedField` without a matching dataclass field. Any Django project with an M2M `through=` argument would raise `NameError` / `AttributeError` and return an empty index. Both are now declared. Discovered by QA sweep of 1.0.4 with type-design and Python reviewers.

## [0.3.1] - 2026-07-13

### Added
- **`throughModel` on the M2M edge** — Mermaid ER diagrams now render `through=` on `ManyToManyField` relations, e.g. `authors [through Authorship]`. First-time external contribution by [@kingrubic](https://github.com/kingrubic) in [#5](https://github.com/FROWNINGdev/django-orm-lens/pull/5).
- **Listed on [Glama.ai MCP directory](https://glama.ai/mcp/servers/FROWNINGdev/django-orm-lens)** — third discovery channel alongside VS Code Marketplace and the official MCP Registry.

## [py-1.0.4] - 2026-07-13

Python package parity release. Extension bumped in parallel to 0.3.1.

### Added
- **`through_model` on `ParsedField`** — Python parser now extracts `through=` from `ManyToManyField(...)` and emits `"throughModel": "..."` in JSON. Matches the TypeScript port field-for-field.

## [py-1.0.3] - 2026-07-13

Python package only. VS Code extension unchanged at 0.3.0.

### Added
- **Listed in the official [MCP Registry](https://registry.modelcontextprotocol.io/)** — the server is now discoverable through the canonical Model Context Protocol directory. MCP-compatible clients can find it by name (`io.github.FROWNINGdev/django-orm-lens`).
- `cli/server.json` — MCP Registry metadata (PyPI package, stdio transport, uvx runtime hint).
- Ownership-verification marker in `cli/README.md` (hidden HTML comment) so the registry can prove the PyPI package is ours.

### Fixed
- 1.0.1: added `on_delete` and `related_name` extraction — kept for parity with the VS Code extension.

## [0.3.0] - 2026-07-13

Ships the terminal + AI-agent story and a batch of ER-diagram / editor polish.

### Added
- **Python CLI + MCP server** — companion package `django-orm-lens` on PyPI. Zero-dep CLI (`scan`, `describe`, `hover`, `list`, `er`) and an optional MCP stdio server exposing five read-only tools to Cursor, Aider, Continue.dev, Zed, and any MCP client. Install: `pip install "django-orm-lens[mcp]"`.
- **CodeLens above every model class** — shows field count, relation count, and an "Open ER diagram" action. Toggle with `djangoOrmLens.showCodeLens`.
- **Edge labels on the ER diagram** — relation arrows now include `on_delete` (CASCADE / SET_NULL / PROTECT) and `related_name` when present, e.g. `author [CASCADE, as posts]`.
- **Diagram theme picker** — `djangoOrmLens.diagramTheme` accepts `auto` (default, follows VS Code theme), `default`, `dark`, `forest`, and `neutral`.

### Fixed
- CI publish workflow was silently failing because of a YAML quoting bug — restored to green; adds a parallel PyPI publish job.

### Docs
- README rewritten around three surfaces: VS Code extension, Python CLI, and MCP server. New Integrations table, updated roadmap, and Support section.

## [0.2.0] - 2026-07-15

The polish release. Consolidates hover, filter, welcome, security hardening, and diagram export into a single minor bump.

### Added
- **Export ER diagram as SVG** — new button in the diagram panel header saves the rendered graph to a file inside your workspace.
- **Welcome view** — when no Django models are found, the sidebar now shows a friendly explanation and a Refresh action instead of a blank panel.
- **Smart tree expansion** — apps start expanded on small projects (<= 40 models) and collapsed on larger ones; a filter always expands to reveal matches.
- **Multi-line class inheritance** — the parser now handles Black-formatted classes where the base list wraps across two or three lines.

### Security
- **jumpToModel path scoping** — the jump command now rejects any target outside the current workspaceFolders. Prevents a crafted models.py from opening arbitrary local files.
- **Hover markdown sanitization** — parser-derived strings are escaped and the trusted-command scope is narrowed to djangoOrmLens.jumpToModel only. Blocks command-URI injection through model or field names.

### Docs

## [0.1.3] - 2026-07-14

### Added
- **Filter tree** — new sidebar buttons and command palette actions (`Django ORM Lens: Filter Models`, `Clear Filter`) let you type a substring and narrow the tree to matching apps, models, and fields in real time. Parent nodes stay visible when a descendant matches.

## [0.1.2] - 2026-07-14

### Added
- **Hover cards** over `ForeignKey('app.Model')`, `OneToOneField(...)`, and `ManyToManyField(...)` references. Hovering a related-model string in the editor now shows a preview of that model (fields, relations, base classes) and a one-click jump link.

## [0.1.1] - 2026-07-13

### Added
- Support for split `models/` package directories (multi-file apps).
- Support for bare field imports (`from django.db.models import CharField`).
- Output channel "Django ORM Lens" for surfaced scan errors.

### Fixed
- Parser now detects indentation width per class instead of assuming 4 spaces (2-space codebases were showing zero fields).
- False-positive base-class detection: `ModelAdmin`, `ModelSerializer`, `ModelForm`, `ResponseModel`, and similar classes are no longer treated as database models.
- Race condition in the workspace scanner: concurrent saves could leave stale results in the tree.
- `Jump to Model` crashed when the target file had been deleted between scan and click — now shows a warning and refreshes.

### Security
- Webview nonce is now generated via `crypto.randomBytes` instead of `Math.random()`.
- Mermaid CDN reference pinned to `10.9.4` (was floating on `mermaid@10`).

## [0.1.0] - 2026-07-07

### Added
- Initial release.
- Sidebar TreeView grouping apps → models → fields → Meta.
- Field-type-aware icons for CharField, ForeignKey, ManyToManyField, and 20+ built-ins.
- Mermaid-rendered ER diagram in a side webview panel.
- Jump-to-definition on any tree node.
- Auto-refresh via `models.py` file watcher.
- Configurable exclude globs (defaults skip `migrations/`, `venv/`, `node_modules/`).
- Status-bar item showing scanned model count.
