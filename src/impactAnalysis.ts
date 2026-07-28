import * as vscode from 'vscode';

/**
 * Impact Analysis engine.
 *
 * Answers "what breaks if I remove this field/model?" — a grouped list
 * of every reference across the workspace with a confidence tier.
 *
 * Design distilled from proven prior art (research-first):
 *
 *   - Sourcegraph / Zoekt   → "index once, filter twice" — cheap
 *     literal candidate pass, then a precise regex/context pass.
 *   - Knip (JS)             → per-framework buckets + confidence tag
 *     on every finding. Users trust tools that admit uncertainty.
 *   - PyCharm Django plugin → layer-by-layer sweep is the mental model
 *     Django users already carry.
 *   - Bundled ripgrep       → VS Code ships `@vscode/ripgrep`; use it
 *     when available for the literal pass, fall back to pure-TS glob.
 *
 * Trade-off: this engine intentionally does NOT do full type inference —
 * that's Pyright's job and it already fails on Django's string-typed
 * FK/related_name/template surface. We accept a "Possibly" tier so
 * the noise is transparent rather than silent.
 *
 * Public API: `scanImpact(needle, options)` returns findings ordered
 * by layer, then confidence, then file path.
 *
 * Callers:
 *   - `src/extension.ts` — `djangoOrmLens.findImpact` command handler
 *   - `test/impact-analysis.test.js` — pure classifier tests
 */

/** Which Django layer does this file belong to? */
export type Layer =
  | 'models'
  | 'serializers'
  | 'forms'
  | 'admin'
  | 'views'
  | 'urls'
  | 'templates'
  | 'tests'
  | 'migrations'
  | 'other';

/** Confidence tier — mirrors Knip's "certain / likely / possibly". */
export type Confidence = 'certain' | 'likely' | 'possibly';

export interface Finding {
  layer: Layer;
  confidence: Confidence;
  /** Absolute file path. */
  filePath: string;
  /** Zero-based line number where the reference sits. */
  line: number;
  /** Zero-based column of the match start. */
  column: number;
  /** The matched text and a small surrounding snippet for the UI. */
  snippet: string;
  /** Explanation of why we tagged this confidence tier. */
  reason: string;
}

export interface ScanOptions {
  /** Skip these globs on top of the extension's excludeGlobs. */
  extraExcludes?: string[];
  /** Absolute file paths to skip entirely (usually the definition site). */
  skipFiles?: string[];
  /** Optional cancellation token. */
  token?: vscode.CancellationToken;
}

/* ---------------------------  layer detection  ----------------------- */

/**
 * Classify a file into a Django layer purely by its normalised path.
 * Cheap; runs once per candidate file before any content scan.
 */
export function detectLayer(filePath: string): Layer {
  const p = filePath.replace(/\\/g, '/').toLowerCase();
  if (/\/templates\/.+\.html$/.test(p) || /\/jinja2\/.+\.html$/.test(p))
    return 'templates';
  if (/\/migrations\/[^/]+\.py$/.test(p)) return 'migrations';
  if (/\/tests?\.py$/.test(p) || /\/tests?\//.test(p) || /\/test_[^/]+\.py$/.test(p))
    return 'tests';
  if (/\/models(\.py|\/[^/]+\.py)$/.test(p)) return 'models';
  if (/\/serializers?(\.py|\/[^/]+\.py)$/.test(p) || /\/api\/[^/]+\.py$/.test(p))
    return 'serializers';
  if (/\/forms?(\.py|\/[^/]+\.py)$/.test(p)) return 'forms';
  if (/\/admin(\.py|\/[^/]+\.py)$/.test(p)) return 'admin';
  if (/\/views?(\.py|\/[^/]+\.py)$/.test(p) || /\/viewsets?\.py$/.test(p))
    return 'views';
  if (/\/urls?\.py$/.test(p)) return 'urls';
  return 'other';
}

/**
 * Classify a file by where it sits *inside the workspace*.
 *
 * Absolute paths are the wrong input for `detectLayer`: the layer patterns
 * match anywhere in the string, so a project checked out under `~/tests/shop`
 * or `services/tests/api` had every one of its files classified as `tests` —
 * `views.py` reported as a test, and so on. Everything above the workspace
 * root is the developer's machine layout, not the project's, so callers pass
 * the workspace-relative path here instead.
 *
 * Mirrors `layer_of()` in cli/django_orm_lens/impact.py. Change both together.
 */
export function layerOf(relativePath: string): Layer {
  const rel = relativePath.replace(/\\/g, '/').replace(/^\/+/, '');
  // Leading slash so patterns anchored on `/models.py` still match a file
  // sitting directly at the workspace root.
  return detectLayer(`/${rel}`);
}

/** Glob patterns per layer — order matters (models first for early wins). */
export const LAYER_GLOBS: Record<Exclude<Layer, 'other'>, string[]> = {
  models: ['**/models.py', '**/models/*.py'],
  serializers: [
    '**/serializers.py',
    '**/serializers/*.py',
    '**/api/serializers*.py',
  ],
  forms: ['**/forms.py', '**/forms/*.py'],
  admin: ['**/admin.py', '**/admin/*.py'],
  views: ['**/views.py', '**/views/*.py', '**/viewsets.py'],
  urls: ['**/urls.py'],
  templates: ['**/templates/**/*.html', '**/jinja2/**/*.html'],
  tests: ['**/tests.py', '**/tests/**/*.py', '**/test_*.py'],
  migrations: ['**/migrations/*.py'],
};

/* --------------------------  text classifier  ------------------------ */

/**
 * Classify a single line's reference to `needle`. Returns `undefined`
 * when the line is definitely noise (in a comment, in a docstring).
 *
 * The classifier uses a small set of confident-hit regexes first
 * (Django ORM string arguments, ModelForm.fields tuples) and falls
 * back to `Possibly` for anything that just contains the identifier.
 */
export function classifyLine(
  layer: Layer,
  line: string,
  needle: string,
): { confidence: Confidence; reason: string } | undefined {
  // Skip pure-comment lines and long docstring markers.
  const stripped = line.trimStart();
  if (stripped.startsWith('#')) return undefined;
  if (stripped.startsWith('"""') || stripped.startsWith("'''"))
    return undefined;

  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Word boundary at the START only — Django lookups like `author__id`
  // read `author` as a field reference even though `\b` doesn't sit
  // between `r` and `_`. The classifier below decides confidence.
  const startBoundary = new RegExp(`\\b${escaped}\\b|\\b${escaped}__`);
  if (!startBoundary.test(line)) return undefined;

  // A) Quoted string inside an ORM function argument list — canonical
  //    "certain" hit: order_by("-author"), select_related("author"), etc.
  const quotedInOrm = new RegExp(
    `\\b(?:F|Q|order_by|values|values_list|only|defer|select_related|prefetch_related|filter|exclude|annotate)\\s*\\([^)]*['"][^'"]*\\b${escaped}\\b`,
  );
  // B) Keyword-argument reference inside a QuerySet call — includes the
  //    common `field__lookup=value` traversal (e.g. author__id=1).
  const kwargInOrm = new RegExp(
    `\\b(?:filter|exclude|get|annotate|update|create|values|values_list|Q)\\s*\\([^)]*\\b${escaped}(?:__\\w+)?\\s*=`,
  );
  // C) Meta-config tuples: fields = ['author', ...], list_display = (...),
  //    search_fields, ordering, list_filter, filterset_fields, etc.
  const fieldsTuple = new RegExp(
    `\\b(?:fields|list_display|search_fields|readonly_fields|list_filter|ordering|filterset_fields|autocomplete_fields|exclude)\\s*=\\s*[\\[(][^\\])]*['"]${escaped}['"]`,
  );
  // D) Template variable — {{ obj.author }} or {% for x in author %}
  const templateVar = new RegExp(
    `\\{\\{[^}]*\\.${escaped}\\b[^}]*\\}\\}|\\{%[^%]*\\b${escaped}\\b[^%]*%\\}`,
  );
  // E) Attribute access — obj.author. `\b` before the dot is fine because
  //    `.` is non-word.
  const attrAccess = new RegExp(`\\.${escaped}(?:__\\w+)?\\b`);

  if (quotedInOrm.test(line)) {
    return { confidence: 'certain', reason: 'ORM string reference' };
  }
  if (kwargInOrm.test(line)) {
    return { confidence: 'certain', reason: 'ORM keyword-arg reference' };
  }
  if (fieldsTuple.test(line)) {
    return {
      confidence: 'certain',
      reason: 'declared in fields/list_display/search_fields tuple',
    };
  }
  if (layer === 'templates' && templateVar.test(line)) {
    return { confidence: 'likely', reason: 'template variable' };
  }

  // Attribute access — likely if we're in a Django-layer file, possibly otherwise.
  if (attrAccess.test(line)) {
    if (layer === 'other') {
      return { confidence: 'possibly', reason: 'attribute access, layer unclear' };
    }
    return { confidence: 'likely', reason: `${layer} attribute access` };
  }

  return { confidence: 'possibly', reason: 'bare identifier match' };
}

/**
 * Scan a single file's text buffer for references. Pure — no I/O.
 * Useful in isolation for the test suite; called by the orchestrator
 * once VS Code hands us the file content.
 */
export function scanFileText(
  filePath: string,
  text: string,
  needle: string,
  knownLayer?: Layer,
): Finding[] {
  // Callers that know the workspace root pass the layer they computed from
  // the relative path — see `layerOf`. Falling back to the absolute path
  // keeps the pure-function tests and any ad-hoc caller working.
  const layer = knownLayer ?? detectLayer(filePath);
  const lines = text.split(/\r?\n/);
  const out: Finding[] = [];
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Detect either bare `\bneedle\b` or the Django lookup form `\bneedle__`.
  const detect = new RegExp(`\\b${escaped}\\b|\\b${escaped}__`);
  const startAt = new RegExp(`\\b${escaped}`);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!detect.test(line)) continue;
    const cls = classifyLine(layer, line, needle);
    if (!cls) continue;
    const column = line.search(startAt);
    out.push({
      layer,
      confidence: cls.confidence,
      filePath,
      line: i,
      column: column < 0 ? 0 : column,
      snippet: line.trim().slice(0, 200),
      reason: cls.reason,
    });
  }
  return out;
}

/* ---------------------------  orchestrator  -------------------------- */

const CONFIDENCE_ORDER: Record<Confidence, number> = {
  certain: 0,
  likely: 1,
  possibly: 2,
};

const LAYER_ORDER: Record<Layer, number> = {
  models: 0,
  serializers: 1,
  forms: 2,
  admin: 3,
  views: 4,
  urls: 5,
  templates: 6,
  tests: 7,
  migrations: 8,
  other: 9,
};

/** Public sort — used by the UI so the top of the list is always most-relevant. */
export function sortFindings(a: Finding, b: Finding): number {
  const d = LAYER_ORDER[a.layer] - LAYER_ORDER[b.layer];
  if (d !== 0) return d;
  const c = CONFIDENCE_ORDER[a.confidence] - CONFIDENCE_ORDER[b.confidence];
  if (c !== 0) return c;
  const p = a.filePath.localeCompare(b.filePath);
  if (p !== 0) return p;
  return a.line - b.line;
}

/**
 * The VS-Code-side driver. Walks each layer's glob set in sequence and
 * calls the classifier on every candidate file. Streaming is left to
 * a later revision — this MVP returns after the whole scan completes.
 */
export async function scanImpact(
  needle: string,
  options: ScanOptions = {},
): Promise<Finding[]> {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  const baseExcludes = cfg.get<string[]>('excludeGlobs', [
    '**/migrations/**',
    '**/node_modules/**',
    '**/venv/**',
    '**/.venv/**',
    '**/env/**',
  ]);
  // Migrations bucket wants migration files, so drop the migration exclusion
  // from the base list when we scan that bucket. For every other bucket the
  // caller-visible exclusion is honoured.
  const excludeCommon = [...baseExcludes, ...(options.extraExcludes ?? [])];
  const skipSet = new Set(options.skipFiles ?? []);
  const findings: Finding[] = [];

  for (const [layer, patterns] of Object.entries(LAYER_GLOBS) as [
    Exclude<Layer, 'other'>,
    string[],
  ][]) {
    if (options.token?.isCancellationRequested) break;
    const excludes =
      layer === 'migrations'
        ? excludeCommon.filter((g) => !/\bmigrations\b/.test(g))
        : excludeCommon;
    const excludeGlob = excludes.length
      ? `{${excludes.join(',')}}`
      : undefined;
    for (const pat of patterns) {
      if (options.token?.isCancellationRequested) break;
      const uris = await vscode.workspace.findFiles(
        pat,
        excludeGlob,
        5000,
        options.token,
      );
      for (const uri of uris) {
        if (options.token?.isCancellationRequested) break;
        const fp = uri.fsPath;
        if (skipSet.has(fp)) continue;
        try {
          const buf = await vscode.workspace.fs.readFile(uri);
          const text = Buffer.from(buf).toString('utf8');
          // Classify on the workspace-relative path, never the absolute one:
          // a checkout under a directory called `tests` must not make every
          // file in the project a test.
          const rel = vscode.workspace.asRelativePath(uri, false);
          const hits = scanFileText(fp, text, needle, layerOf(rel));
          findings.push(...hits);
        } catch {
          // Unreadable file — skip silently, don't fail the whole scan.
        }
      }
    }
  }

  findings.sort(sortFindings);
  return findings;
}
