import * as vscode from 'vscode';
import { querysetRules } from './queryset';
import { modelRules } from './models';
import { datetimeRules } from './datetime';
import { formsRules } from './forms';
import { ALL_FIXERS, findFixersForCode } from './fixers';
import {
  DIAGNOSTIC_SOURCE,
  Finding,
  Rule,
  RuleContext,
  Severity,
  makeRuleContext,
  renderMessage,
  toDiagnosticSeverity,
} from './types';

/**
 * Rules aggregator. This is the ONLY module that other extension code
 * needs to import from `src/rules/`. It exposes:
 *
 *   - ALL_RULES: the canonical rule catalogue
 *   - ALL_FIXERS: the fixer registry (re-exported from fixers.ts)
 *   - findFixersForCode: lookup helper (re-exported)
 *   - scanDocument(doc): the entry point that runs every enabled rule
 *     against a document and returns findings decorated with a resolved
 *     severity (user setting > per-finding override > rule default).
 *
 * User configuration surface:
 *   djangoOrmLens.rules.<CODE> = "off" | "hint" | "info" | "warning" | "error"
 *   djangoOrmLens.rulesSelect  = string[]     (whitelist by code or prefix)
 *   djangoOrmLens.rulesIgnore  = string[]     (blacklist by code or prefix)
 *
 * Inline suppression:
 *   `# django-orm-lens-disable-next-line DOL001[,DOL021]`
 *   `# django-orm-lens-disable-line DOL001`
 *   `# django-orm-lens-disable DOL001` on its own line disables the rule
 *   for the rest of the file.
 */

/** Canonical rule catalogue in stable order (queryset, model, datetime, forms). */
export const ALL_RULES: Rule[] = [
  ...querysetRules,
  ...modelRules,
  ...datetimeRules,
  ...formsRules,
];

/** Re-exports so callers only need `from './rules'`. */
export {
  ALL_FIXERS,
  findFixersForCode,
  DIAGNOSTIC_SOURCE,
  renderMessage,
  toDiagnosticSeverity,
};

/** A finding, ready for consumption by the CodeActionProvider. */
export interface ResolvedFinding {
  finding: Finding;
  rule: Rule;
  severity: Severity;
  renderedMessage: string;
}

/** VS Code severity string as user-facing setting value. */
type SettingSeverity = 'off' | Severity;

interface RulesConfig {
  perCode: Record<string, SettingSeverity>;
  select: string[];
  ignore: string[];
}

function readConfig(): RulesConfig {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  const perCode = cfg.get<Record<string, SettingSeverity>>('rules', {}) ?? {};
  const select = cfg.get<string[]>('rulesSelect', []) ?? [];
  const ignore = cfg.get<string[]>('rulesIgnore', []) ?? [];
  return { perCode, select, ignore };
}

/**
 * Ruff-style prefix match. `select`/`ignore` accept exact codes ("DOL001")
 * or any prefix ("DOL" disables all Django ORM Lens rules; "DOL0" only
 * queryset+model rules).
 */
function matchesAny(code: string, entries: string[]): boolean {
  return entries.some((e) => code === e || code.startsWith(e));
}

/**
 * Resolve the effective severity for a rule against user configuration.
 * Returns `null` when the rule should not run at all.
 *
 * Precedence (highest → lowest):
 *   1. per-code setting ("off" / severity)
 *   2. rulesIgnore blacklist ("off")
 *   3. rulesSelect whitelist (if set and rule isn't in it, "off")
 *   4. rule.meta.defaultSeverity
 */
export function resolveRuleSeverity(
  rule: Rule,
  cfg: RulesConfig,
): Severity | null {
  const explicit = cfg.perCode[rule.meta.code];
  if (explicit === 'off') return null;
  if (explicit) return explicit;
  if (cfg.ignore.length && matchesAny(rule.meta.code, cfg.ignore)) return null;
  if (cfg.select.length && !matchesAny(rule.meta.code, cfg.select)) return null;
  return rule.meta.defaultSeverity;
}

/** Parse `# django-orm-lens-disable-...` comments to a per-line suppression map. */
interface SuppressionMap {
  /** Codes disabled for the whole file (starting at their declaration line). */
  fileWide: Set<string>;
  /** Line → set of codes disabled just for that line. */
  perLine: Map<number, Set<string>>;
  /** true if `disable` (no codes) appears — disables all rules file-wide. */
  disableAll: boolean;
  disableAllFrom: number;
}

const RE_DISABLE_NEXT_LINE =
  /#\s*django-orm-lens-disable-next-line(?:\s+([A-Z0-9,\s]+))?/i;
const RE_DISABLE_LINE =
  /#\s*django-orm-lens-disable-line(?:\s+([A-Z0-9,\s]+))?/i;
const RE_DISABLE_FILE =
  /#\s*django-orm-lens-disable(?:\s+([A-Z0-9,\s]+))?/i;

function parseCodes(list: string | undefined): string[] {
  if (!list) return [];
  return list
    .split(/[\s,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

function buildSuppressions(ctx: RuleContext): SuppressionMap {
  const suppr: SuppressionMap = {
    fileWide: new Set<string>(),
    perLine: new Map<number, Set<string>>(),
    disableAll: false,
    disableAllFrom: -1,
  };
  for (let i = 0; i < ctx.lineCount; i++) {
    const text = ctx.lineAt(i);
    // Match precedence: next-line > this-line > file-wide.
    let m = RE_DISABLE_NEXT_LINE.exec(text);
    if (m) {
      const codes = parseCodes(m[1]);
      const target = i + 1;
      if (!suppr.perLine.has(target)) suppr.perLine.set(target, new Set());
      const set = suppr.perLine.get(target)!;
      if (codes.length === 0) set.add('*');
      else for (const c of codes) set.add(c);
      continue;
    }
    m = RE_DISABLE_LINE.exec(text);
    if (m) {
      const codes = parseCodes(m[1]);
      if (!suppr.perLine.has(i)) suppr.perLine.set(i, new Set());
      const set = suppr.perLine.get(i)!;
      if (codes.length === 0) set.add('*');
      else for (const c of codes) set.add(c);
      continue;
    }
    // Only treat a bare "disable" comment as file-wide if the whole line IS
    // the comment (not a trailing directive on a real code line).
    if (text.trim().startsWith('#')) {
      m = RE_DISABLE_FILE.exec(text);
      if (m) {
        const codes = parseCodes(m[1]);
        if (codes.length === 0) {
          suppr.disableAll = true;
          suppr.disableAllFrom = i;
        } else {
          for (const c of codes) suppr.fileWide.add(c);
        }
      }
    }
  }
  return suppr;
}

function isSuppressed(
  code: string,
  line: number,
  suppr: SuppressionMap,
): boolean {
  if (suppr.disableAll && line >= suppr.disableAllFrom) return true;
  if (suppr.fileWide.has(code)) return true;
  const line0 = suppr.perLine.get(line);
  if (line0 && (line0.has('*') || line0.has(code))) return true;
  return false;
}

/**
 * Main entry point. Runs every enabled rule against the document and
 * returns resolved findings. Callers turn each `ResolvedFinding` into a
 * `vscode.Diagnostic` and (optionally) a `vscode.CodeAction`.
 */
export function scanDocument(document: vscode.TextDocument): ResolvedFinding[] {
  if (document.languageId !== 'python') return [];
  const cfg = readConfig();
  const ctx = makeRuleContext(document);
  const suppr = buildSuppressions(ctx);

  const out: ResolvedFinding[] = [];
  for (const rule of ALL_RULES) {
    const severity = resolveRuleSeverity(rule, cfg);
    if (!severity) continue;
    let findings: Finding[];
    try {
      findings = rule.check(ctx);
    } catch {
      // A rule failure must never break the whole pass. Swallow silently
      // here; the extension's global outputChannel picks up the pattern
      // at a higher level.
      continue;
    }
    for (const finding of findings) {
      if (isSuppressed(finding.code, finding.range.line, suppr)) continue;
      const rendered = renderMessage(
        rule.meta.messages[finding.messageId] ?? '',
        finding.args,
      );
      out.push({
        finding,
        rule,
        severity: finding.severityOverride ?? severity,
        renderedMessage: rendered,
      });
    }
  }
  return out;
}

/** Look up a rule by its stable code. Used by the CodeActionProvider. */
export function getRuleByCode(code: string): Rule | undefined {
  return ALL_RULES.find((r) => r.meta.code === code);
}
