import * as vscode from 'vscode';

/**
 * Django ORM Lens — static-analysis QuickFix / CodeAction provider.
 *
 * Detects common Django ORM anti-patterns in Python source and suggests
 * idiomatic replacements as VS Code CodeActions. Zero runtime, zero DB —
 * pure regex + line-context inspection, feature-flagged via
 * `djangoOrmLens.codeFixes.enabled` (default true).
 *
 * Ships v0.8 as WOW-feature #3 from the community roadmap in Discussion #27.
 * Complements the sidebar / ER diagram / CLI without replacing existing
 * runtime tools like django-debug-toolbar or nplusone.
 *
 * Coverage on release:
 *   1. `.filter(...).count() > 0`   → `.filter(...).exists()`
 *   2. `.filter(...).count() == 0`  → `not .filter(...).exists()`
 *   3. `.first() is None`           → `not ...exists()`
 *   4. `.first() is not None`       → `...exists()`
 *   5. bare `.all()` inside a for-loop over a QuerySet — flag missing
 *      `select_related` when a `.` field access on the loop var appears.
 *
 * Each finding surfaces two artefacts:
 *   - a Diagnostic (squiggle, Information/Warning severity)
 *   - a CodeAction (yellow lightbulb) that applies the fix on click.
 */
export const DIAGNOSTIC_SOURCE = 'Django ORM Lens';
export const DOL_RULE_PREFIX = 'dol/';

/** Rule identifiers used both in Diagnostic.code and in messages. */
export const RULES = {
  countGtZero: `${DOL_RULE_PREFIX}count-gt-zero`,
  countEqZero: `${DOL_RULE_PREFIX}count-eq-zero`,
  firstIsNone: `${DOL_RULE_PREFIX}first-is-none`,
  firstIsNotNone: `${DOL_RULE_PREFIX}first-is-not-none`,
  fkAccessInLoop: `${DOL_RULE_PREFIX}fk-access-in-loop`,
} as const;

const RE_COUNT_GT_ZERO =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.count\(\)\s*(?:>\s*0|>=\s*1)\b/g;

const RE_COUNT_EQ_ZERO =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.count\(\)\s*==\s*0\b/g;

const RE_FIRST_IS_NONE =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.first\(\)\s+is\s+None\b/g;

const RE_FIRST_IS_NOT_NONE =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.first\(\)\s+is\s+not\s+None\b/g;

const RE_FOR_LOOP_HEAD =
  /^\s*for\s+([A-Za-z_]\w*)\s+in\s+([A-Za-z_][\w.]*(?:\([^()]*\))*(?:\.all\(\))?)\s*:/;

interface RawFinding {
  rule: string;
  message: string;
  range: vscode.Range;
  replacement: string;
  actionTitle: string;
}

function scanLine(
  doc: vscode.TextDocument,
  lineIndex: number,
): RawFinding[] {
  const findings: RawFinding[] = [];
  const text = doc.lineAt(lineIndex).text;

  const stripped = text.trimStart();
  if (stripped.startsWith('#')) return findings;

  const singleShotRules: Array<[RegExp, (m: RegExpExecArray) => Omit<RawFinding, 'range'>]> = [
    [
      RE_COUNT_GT_ZERO,
      (m) => ({
        rule: RULES.countGtZero,
        message: `Prefer .exists() over .count() > 0 — cheaper and clearer.`,
        replacement: `${m[1]}.exists()`,
        actionTitle: `Use .exists() instead of .count() > 0`,
      }),
    ],
    [
      RE_COUNT_EQ_ZERO,
      (m) => ({
        rule: RULES.countEqZero,
        message: `Prefer not .exists() over .count() == 0 — cheaper and clearer.`,
        replacement: `not ${m[1]}.exists()`,
        actionTitle: `Use not .exists() instead of .count() == 0`,
      }),
    ],
    [
      RE_FIRST_IS_NONE,
      (m) => ({
        rule: RULES.firstIsNone,
        message: `Prefer not .exists() over .first() is None — no row fetch needed.`,
        replacement: `not ${m[1]}.exists()`,
        actionTitle: `Use not .exists() instead of .first() is None`,
      }),
    ],
    [
      RE_FIRST_IS_NOT_NONE,
      (m) => ({
        rule: RULES.firstIsNotNone,
        message: `Prefer .exists() over .first() is not None — no row fetch needed.`,
        replacement: `${m[1]}.exists()`,
        actionTitle: `Use .exists() instead of .first() is not None`,
      }),
    ],
  ];

  for (const [regex, mkFinding] of singleShotRules) {
    regex.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = regex.exec(text)) !== null) {
      const start = match.index;
      const end = start + match[0].length;
      const range = new vscode.Range(lineIndex, start, lineIndex, end);
      findings.push({ ...mkFinding(match), range });
    }
  }
  return findings;
}

/**
 * Detect a possible N+1 pattern by scanning up to `MAX_LOOP_LINES` lines
 * after a `for <var> in <qs>:` header. If we see `<var>.<name>` where
 * `<name>` looks like a relation, flag it. Regex-only; no ast module.
 */
const MAX_LOOP_LINES = 15;
const LOOP_VAR_ATTR_RE = /\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g;

function scanForLoops(doc: vscode.TextDocument): RawFinding[] {
  const out: RawFinding[] = [];
  const total = doc.lineCount;
  for (let i = 0; i < total; i++) {
    const headText = doc.lineAt(i).text;
    const head = RE_FOR_LOOP_HEAD.exec(headText);
    if (!head) continue;
    const loopVar = head[1];
    const qsExpr = head[2];

    const end = Math.min(total, i + 1 + MAX_LOOP_LINES);
    for (let j = i + 1; j < end; j++) {
      const line = doc.lineAt(j).text;
      if (line.length > 0 && !/^\s/.test(line)) break;
      LOOP_VAR_ATTR_RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = LOOP_VAR_ATTR_RE.exec(line)) !== null) {
        if (m[1] !== loopVar) continue;
        const attr = m[2];
        if (attr.startsWith('_')) continue;
        if (attr === 'id' || attr === 'pk' || attr === 'save') continue;
        const startCol = m.index;
        const range = new vscode.Range(j, startCol, j, startCol + m[0].length);
        out.push({
          rule: RULES.fkAccessInLoop,
          message: `Attribute access '${m[0]}' inside a loop over '${qsExpr}' — consider .select_related() or .prefetch_related() to avoid an N+1.`,
          range,
          replacement: '',
          actionTitle: `Add .select_related('${attr}') hint to the QuerySet header`,
        });
        break;
      }
    }
  }
  return out;
}

/** CodeActionProvider — thin wrapper that reuses scanLine. */
export class DjangoCodeFixesProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private readonly diagnostics: vscode.DiagnosticCollection) {}

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
  ): vscode.CodeAction[] {
    const relevantDiags = this.diagnostics
      .get(document.uri)
      ?.filter(
        (d) =>
          typeof d.code === 'string' &&
          d.code.startsWith(DOL_RULE_PREFIX) &&
          d.range.intersection(range) !== undefined,
      );
    if (!relevantDiags?.length) return [];

    const actions: vscode.CodeAction[] = [];
    for (const diag of relevantDiags) {
      const findings = scanLine(document, diag.range.start.line);
      const hit = findings.find(
        (f) => f.rule === diag.code && f.range.isEqual(diag.range),
      );
      if (!hit || !hit.replacement) continue;

      const edit = new vscode.WorkspaceEdit();
      edit.replace(document.uri, diag.range, hit.replacement);
      const action = new vscode.CodeAction(hit.actionTitle, vscode.CodeActionKind.QuickFix);
      action.diagnostics = [diag];
      action.edit = edit;
      action.isPreferred = true;
      actions.push(action);
    }
    return actions;
  }
}

/** Lint pass for a single document — safe to call on every save. */
export function refreshDiagnosticsForDoc(
  doc: vscode.TextDocument,
  collection: vscode.DiagnosticCollection,
): void {
  if (doc.languageId !== 'python') {
    collection.delete(doc.uri);
    return;
  }
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  if (!cfg.get<boolean>('codeFixes.enabled', true)) {
    collection.delete(doc.uri);
    return;
  }

  const findings: RawFinding[] = [];
  for (let i = 0; i < doc.lineCount; i++) {
    findings.push(...scanLine(doc, i));
  }
  findings.push(...scanForLoops(doc));

  const diags: vscode.Diagnostic[] = findings.map((f) => {
    const severity =
      f.rule === RULES.fkAccessInLoop
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Information;
    const diag = new vscode.Diagnostic(f.range, f.message, severity);
    diag.code = f.rule;
    diag.source = DIAGNOSTIC_SOURCE;
    return diag;
  });

  collection.set(doc.uri, diags);
}

/**
 * Register the provider + wire diagnostics to active-editor / save / open
 * events. Returns disposables to push into ExtensionContext.subscriptions.
 */
export function registerCodeFixes(
  _context: vscode.ExtensionContext,
): vscode.Disposable[] {
  const collection = vscode.languages.createDiagnosticCollection('djangoOrmLens');
  const provider = new DjangoCodeFixesProvider(collection);

  const disposables: vscode.Disposable[] = [
    collection,
    vscode.languages.registerCodeActionsProvider(
      { language: 'python' },
      provider,
      { providedCodeActionKinds: DjangoCodeFixesProvider.providedCodeActionKinds },
    ),
    vscode.workspace.onDidOpenTextDocument((d) => refreshDiagnosticsForDoc(d, collection)),
    vscode.workspace.onDidChangeTextDocument((e) =>
      refreshDiagnosticsForDoc(e.document, collection),
    ),
    vscode.workspace.onDidSaveTextDocument((d) => refreshDiagnosticsForDoc(d, collection)),
    vscode.workspace.onDidCloseTextDocument((d) => collection.delete(d.uri)),
  ];

  for (const doc of vscode.workspace.textDocuments) {
    refreshDiagnosticsForDoc(doc, collection);
  }

  return disposables;
}
