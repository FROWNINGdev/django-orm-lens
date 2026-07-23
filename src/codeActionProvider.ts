import * as vscode from 'vscode';
import {
  DIAGNOSTIC_SOURCE,
  findFixersForCode,
  getRuleByCode,
  scanDocument,
  toDiagnosticSeverity,
} from './rules';
import { FixEdit, makeRuleContext } from './rules/types';

/**
 * Django ORM Lens — code-action / diagnostics orchestrator.
 *
 * Historically this file owned regex, findings, message templates, and
 * severity mapping all in one. v0.8 splits those concerns into
 * `src/rules/*` and this module becomes a thin adapter:
 *
 *   scanDocument(doc) → ResolvedFinding[]  (in ./rules/index.ts)
 *   ResolvedFinding    → vscode.Diagnostic
 *   diag.code (DOL###) → findFixersForCode(...) → vscode.CodeAction[]
 *
 * The public wire format is: `Diagnostic.source = "Django ORM Lens"` and
 * `Diagnostic.code` is a `{ value, target }` pair with the Ruff-style
 * short code and a clickable link to the rule docs on hover.
 *
 * Feature flag: `djangoOrmLens.codeFixes.enabled` (default true).
 * Per-rule opt-out: `djangoOrmLens.rules.<CODE> = "off"` (see rules/index.ts).
 */

/** Materialise our line/col FixEdits into a vscode.WorkspaceEdit. */
function applyEdits(
  uri: vscode.Uri,
  edits: FixEdit[],
): vscode.WorkspaceEdit {
  const wsEdit = new vscode.WorkspaceEdit();
  for (const e of edits) {
    wsEdit.replace(
      uri,
      new vscode.Range(e.line, e.startCol, e.line, e.endCol),
      e.newText,
    );
  }
  return wsEdit;
}

/**
 * CodeActionProvider. For each diagnostic in the current range that
 * carries a `DOL###` code, look up matching fixers and materialise
 * a CodeAction per fixer. Fixers whose `build()` returns null are
 * dropped silently — that's how a fixer opts out for edge cases.
 */
export class DjangoCodeFixesProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private readonly diagnostics: vscode.DiagnosticCollection) {}

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
  ): vscode.CodeAction[] {
    const relevant = this.diagnostics
      .get(document.uri)
      ?.filter(
        (d) =>
          typeof d.code === 'object' &&
          d.code !== null &&
          typeof (d.code as { value: unknown }).value === 'string' &&
          (d.code as { value: string }).value.startsWith('DOL') &&
          d.range.intersection(range) !== undefined,
      );
    if (!relevant?.length) return [];

    const actions: vscode.CodeAction[] = [];
    for (const diag of relevant) {
      const code = (diag.code as { value: string }).value;
      const rule = getRuleByCode(code);
      if (!rule) continue;
      // Re-run just this one rule to recover the finding's `fixHint` and
      // `applicability` (both are not preserved on the vscode.Diagnostic).
      // Cheap — one regex pass over an already-open document.
      const findings = rule
        .check(makeRuleContext(document))
        .filter(
          (f) =>
            f.range.line === diag.range.start.line &&
            f.range.startCol === diag.range.start.character &&
            f.range.endCol === diag.range.end.character,
        );
      if (findings.length === 0) continue;
      const finding = findings[0];
      const fixers = findFixersForCode(code, finding.fixHint);
      for (const fixer of fixers) {
        const edits = fixer.build({ finding, document });
        if (!edits || edits.length === 0) continue;
        const action = new vscode.CodeAction(
          fixer.title,
          vscode.CodeActionKind.QuickFix,
        );
        action.diagnostics = [diag];
        action.edit = applyEdits(document.uri, edits);
        action.isPreferred =
          finding.applicability === 'safe' && fixers.length === 1;
        actions.push(action);
      }
    }
    return actions;
  }
}

/** Turn ResolvedFinding[] into vscode.Diagnostic[] and publish them. */
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

  const findings = scanDocument(doc);

  const diags: vscode.Diagnostic[] = findings.map(
    ({ finding, rule, severity, renderedMessage }) => {
      const range = new vscode.Range(
        finding.range.line,
        finding.range.startCol,
        finding.range.line,
        finding.range.endCol,
      );
      const diag = new vscode.Diagnostic(
        range,
        renderedMessage,
        toDiagnosticSeverity(severity),
      );
      diag.source = DIAGNOSTIC_SOURCE;
      diag.code = {
        value: finding.code,
        target: vscode.Uri.parse(rule.meta.docsUrl),
      };
      if (
        rule.meta.category === 'style' &&
        finding.applicability === 'safe'
      ) {
        diag.tags = [vscode.DiagnosticTag.Unnecessary];
      }
      return diag;
    },
  );

  collection.set(doc.uri, diags);
}

/**
 * Register the provider + wire diagnostics to open / change / save / close
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
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration('djangoOrmLens.codeFixes.enabled') ||
        e.affectsConfiguration('djangoOrmLens.rules') ||
        e.affectsConfiguration('djangoOrmLens.rulesSelect') ||
        e.affectsConfiguration('djangoOrmLens.rulesIgnore')
      ) {
        for (const doc of vscode.workspace.textDocuments) {
          refreshDiagnosticsForDoc(doc, collection);
        }
      }
    }),
  ];

  for (const doc of vscode.workspace.textDocuments) {
    refreshDiagnosticsForDoc(doc, collection);
  }

  return disposables;
}

/** Public export for the tree-badge feature: total Django-ORM-Lens issue count. */
export function getIssueCount(
  collection: vscode.DiagnosticCollection,
): number {
  let n = 0;
  collection.forEach((_uri, diags) => {
    for (const d of diags) {
      if (
        d.source === DIAGNOSTIC_SOURCE &&
        typeof d.code === 'object' &&
        d.code !== null &&
        typeof (d.code as { value: unknown }).value === 'string' &&
        (d.code as { value: string }).value.startsWith('DOL')
      ) {
        n++;
      }
    }
  });
  return n;
}
