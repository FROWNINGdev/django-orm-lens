import { Finding, Rule, RuleContext } from './types';

/**
 * Datetime / timezone rules.
 *
 * Codes DOL021..DOL025 are reserved for datetime handling.
 *
 * Django defaults `USE_TZ=True` since Django 4. The idiomatic clock is
 * `django.utils.timezone.now()`, not `datetime.now()` / `datetime.utcnow()`.
 * Python's `datetime.utcnow()` is deprecated since Python 3.12.
 *
 * Public callers: src/rules/index.ts aggregates datetimeRules into ALL_RULES.
 */

const DOCS_BASE =
  'https://github.com/FROWNINGdev/django-orm-lens/blob/main/docs/rules';

/** Detect `datetime.now()` (bare-module reference). Excludes attribute access. */
const RE_DATETIME_NOW = /(?<![\w.])datetime\.now\s*\(\s*\)/g;
/** Detect `datetime.utcnow()`. Deprecated in Python 3.12. */
const RE_DATETIME_UTCNOW = /(?<![\w.])datetime\.utcnow\s*\(\s*\)/g;

function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/**
 * DOL021 — `datetime.now()` in a Django module.
 *
 * With `USE_TZ=True` this returns a naive datetime, and Django will warn
 * ("RuntimeWarning: DateTimeField received a naive datetime"). The safe
 * replacement is `timezone.now()`.
 *
 * Applicability: suggestion — safe when USE_TZ=True (the modern default),
 * unsafe if the project explicitly opted into naive datetimes.
 */
const DOL021: Rule = {
  meta: {
    code: 'DOL021',
    title: 'datetime.now() should be timezone.now()',
    category: 'correctness',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL021.md`,
    since: '0.8.0',
    messages: {
      default:
        'datetime.now() returns a naive datetime; Django with USE_TZ=True will warn. Use django.utils.timezone.now() instead.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_DATETIME_NOW.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_DATETIME_NOW.exec(text)) !== null) {
        out.push({
          code: 'DOL021',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'suggestion',
        });
      }
    }
    return out;
  },
};

/**
 * DOL022 — `datetime.utcnow()` is deprecated in Python 3.12 and returns
 * a naive datetime. Replace with `datetime.now(timezone.utc)` for stdlib
 * or `django.utils.timezone.now()` when inside a Django module.
 */
const DOL022: Rule = {
  meta: {
    code: 'DOL022',
    title: 'datetime.utcnow() is deprecated',
    category: 'correctness',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL022.md`,
    since: '0.8.0',
    messages: {
      default:
        'datetime.utcnow() is deprecated in Python 3.12 and returns a naive datetime. Use timezone.now() (Django) or datetime.now(timezone.utc) (stdlib).',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_DATETIME_UTCNOW.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_DATETIME_UTCNOW.exec(text)) !== null) {
        out.push({
          code: 'DOL022',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'suggestion',
        });
      }
    }
    return out;
  },
};

export const datetimeRules: Rule[] = [DOL021, DOL022];
