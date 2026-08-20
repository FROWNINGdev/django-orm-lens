import * as vscode from 'vscode';
import { WorkspaceIndex } from '../types';

/**
 * Django ORM Lens — rules engine core types.
 *
 * The architecture is a hybrid distilled from the mainstream lint ecosystems:
 *
 *   - Roslyn Analyzers (.NET) — analyzer and fixer are separate concerns,
 *     connected only by a stable diagnostic code. One diagnostic can have
 *     zero, one, or many fixers.
 *   - Ruff (Python) — namespaced short codes like DOL001, DOL002. Greppable,
 *     stable across renames, category-inferrable at a glance.
 *   - Clippy (Rust) — `Applicability` gates whether a fix runs unattended.
 *     `safe` fixes can auto-apply; `unsafe` never do without user intent.
 *   - ktlint (Kotlin) — fixability is a property of the individual FINDING,
 *     not the rule, so one rule can have both fixable and unfixable hits.
 *   - PHPStan (PHP) — rules RETURN findings; no push/context-report mutation.
 *     Testable without mocks.
 *   - ESLint (JS) — `messageId` + `args` indirection instead of raw strings.
 *     Message text lives in metadata; rewording is a metadata change.
 *
 * Every rule is a plain metadata object (not a class) with a pure
 * `check(ctx): Finding[]` function. Fixers are registered in a separate
 * table keyed by `code`. This keeps the analyzer testable with plain
 * strings and lets third parties (or later versions) grow more fixers
 * against the same code without editing the rule file.
 *
 * We only replicate IDEAS, not code — every regex here is written from
 * scratch against Django ORM idioms and vetted against real repos.
 */

/** Diagnostic.source shown in Problems panel and hover. Stable. */
export const DIAGNOSTIC_SOURCE = 'Django ORM Lens';

/** Prefix for every rule code. Codes are strings like `DOL001`. */
export const DOL_CODE_PREFIX = 'DOL';

/** Categories borrowed from Clippy's taxonomy. */
export type Category =
  | 'correctness'
  | 'performance'
  | 'style'
  | 'django-idiom';

/**
 * Clippy's Applicability enum. Controls whether an editor may auto-apply
 * a fix without asking, and whether "Fix All" bulk commands include the fix.
 *
 *  - `safe`: semantically equivalent, always correct to apply.
 *  - `suggestion`: usually right but may need review — offer as CodeAction,
 *    do not include in "Fix All".
 *  - `unsafe`: likely-correct but breaks in edge cases — offer only as an
 *    explicit suggestion, never auto-apply.
 */
export type Applicability = 'safe' | 'suggestion' | 'unsafe';

/**
 * Severity levels mirroring VS Code's own but expressed as strings so
 * user-facing settings can be human-readable (`"warning"`, not `1`).
 */
export type Severity = 'error' | 'warning' | 'info' | 'hint';

/**
 * Rule metadata. Everything static about a rule. No behaviour.
 * `code` must be unique and stable across versions — rename-friendly
 * because callers reference codes, not internal file names.
 */
export interface RuleMeta {
  /** Stable public code like `DOL001`. Appears in Diagnostic.code. */
  code: string;
  /** Short human title — one line, sentence case, no full stop. */
  title: string;
  /** Category for grouping in docs and settings. */
  category: Category;
  /** Default severity — user can override via djangoOrmLens.rules.<code>. */
  defaultSeverity: Severity;
  /** URL rendered as Diagnostic.code target — "Learn more" link on hover. */
  docsUrl: string;
  /** Semver of the extension when this rule shipped. */
  since: string;
  /**
   * ESLint-style message table. Rule reports a `messageId`, the framework
   * renders the template with `args`. Placeholder syntax: `{name}`.
   */
  messages: Record<string, string>;
}

/**
 * A single finding produced by a rule. Immutable-friendly plain data.
 * Range uses zero-based line/column so it round-trips through JSON tests.
 */
export interface Finding {
  code: string;
  messageId: string;
  args?: Record<string, string | number>;
  range: {
    line: number;
    startCol: number;
    endCol: number;
  };
  /** Fix safety — controls auto-apply eligibility. */
  applicability: Applicability;
  /**
   * Symbolic hint identifying WHICH fixer variant should apply, when a
   * rule has multiple fixers. Omit if the rule has a single canonical fix.
   */
  fixHint?: string;
  /**
   * Per-finding severity override. If unset, uses rule.defaultSeverity
   * (which itself may be overridden by user settings).
   */
  severityOverride?: Severity;
}

/**
 * Everything a rule sees when it scans. Line-oriented — we're regex based,
 * no AST — with helpers for bounded windows so N+1 style detectors do not
 * scan the whole document per node.
 */
export interface RuleContext {
  document: vscode.TextDocument;
  lineCount: number;
  lineAt(index: number): string;
  /** Return up to `n` lines ending at `lineIndex - 1`. */
  windowBefore(lineIndex: number, n: number): string[];
  /** Return up to `n` lines starting at `lineIndex + 1`. */
  windowAfter(lineIndex: number, n: number): string[];
  /**
   * The parsed workspace, when the caller has one.
   *
   * Optional because most rules are pure text shape — `.count() > 0` needs no
   * schema — and because a rule pass must still run before the first scan
   * completes. A rule that needs the schema returns no findings when this is
   * absent rather than guessing, so a cold start is quiet, not wrong.
   */
  index?: WorkspaceIndex;
}

/** The rule object itself. Metadata + a pure check function. */
export interface Rule {
  meta: RuleMeta;
  check(ctx: RuleContext): Finding[];
}

/** Concrete edit produced by a fixer — line/column based, zero indexed. */
export interface FixEdit {
  line: number;
  startCol: number;
  endCol: number;
  newText: string;
}

export interface FixerContext {
  finding: Finding;
  document: vscode.TextDocument;
}

/**
 * Fixer registration. A fixer knows how to translate one finding into
 * a concrete text edit. Registered separately from rules — one rule
 * can have zero, one, or many fixers, and vice versa.
 */
export interface Fixer {
  /** Diagnostic code this fixer targets. */
  code: string;
  /**
   * Optional narrower match. If set, this fixer only applies when the
   * finding's `fixHint` matches. Omit to catch all findings of this code.
   */
  fixHint?: string;
  /** Human-readable title shown in the QuickFix lightbulb menu. */
  title: string;
  /** Return null to opt out of fixing a particular finding at runtime. */
  build(ctx: FixerContext): FixEdit[] | null;
}

/**
 * Map a Severity string to a VS Code DiagnosticSeverity enum value.
 * Kept here so the rest of the code can stay string-typed and JSON-friendly.
 */
export function toDiagnosticSeverity(sev: Severity): vscode.DiagnosticSeverity {
  switch (sev) {
    case 'error':
      return vscode.DiagnosticSeverity.Error;
    case 'warning':
      return vscode.DiagnosticSeverity.Warning;
    case 'info':
      return vscode.DiagnosticSeverity.Information;
    case 'hint':
      return vscode.DiagnosticSeverity.Hint;
  }
}

/** Render a message template with args, ESLint-style. Missing keys stay literal. */
export function renderMessage(
  template: string,
  args: Record<string, string | number> | undefined,
): string {
  if (!args) return template;
  return template.replace(/\{(\w+)\}/g, (m, key) =>
    Object.prototype.hasOwnProperty.call(args, key) ? String(args[key]) : m,
  );
}

/**
 * Build a `RuleContext` from a `vscode.TextDocument`. Centralised so rules
 * cannot reach into TextDocument APIs directly — makes them testable with
 * a minimal shim in unit tests.
 */
export function makeRuleContext(
  document: vscode.TextDocument,
  index?: WorkspaceIndex
): RuleContext {
  const lineCount = document.lineCount;
  return {
    document,
    lineCount,
    index,
    lineAt(index: number): string {
      if (index < 0 || index >= lineCount) return '';
      return document.lineAt(index).text;
    },
    windowBefore(lineIndex: number, n: number): string[] {
      const out: string[] = [];
      for (let i = Math.max(0, lineIndex - n); i < lineIndex; i++) {
        out.push(document.lineAt(i).text);
      }
      return out;
    },
    windowAfter(lineIndex: number, n: number): string[] {
      const out: string[] = [];
      const stop = Math.min(lineCount, lineIndex + 1 + n);
      for (let i = lineIndex + 1; i < stop; i++) {
        out.push(document.lineAt(i).text);
      }
      return out;
    },
  };
}
