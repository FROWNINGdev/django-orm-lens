import { Finding, Rule, RuleContext } from './types';

/**
 * QuerySet anti-patterns.
 *
 * Codes DOL001..DOL010 are reserved for QuerySet-shape rules. Codes are
 * stable public surface; do not renumber. When a rule is removed, its
 * code stays retired.
 *
 * Every rule here is line-oriented (regex + optional bounded window) so
 * the whole pass stays O(lineCount) and works without a Python parser.
 */

const DOCS_BASE =
  'https://github.com/FROWNINGdev/django-orm-lens/blob/main/docs/rules';

const RE_COUNT_GT_ZERO =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.count\(\)\s*(?:>\s*0|>=\s*1)\b/g;
const RE_COUNT_EQ_ZERO =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.count\(\)\s*==\s*0\b/g;
const RE_FIRST_IS_NONE =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.first\(\)\s+is\s+None\b/g;
const RE_FIRST_IS_NOT_NONE =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.first\(\)\s+is\s+not\s+None\b/g;
const RE_FILTER_EXCLUDE_CHAIN =
  /(\b[A-Za-z_][\w.]*(?:\([^()]*\))*)\.filter\(([^()]*)\)\s*\.exclude\(([^()]*)\)/g;
const RE_LIST_OF_QS_IN_FOR =
  /^\s*for\s+[A-Za-z_]\w*\s+in\s+list\(([A-Za-z_][\w.]*(?:\([^()]*\))*)\)\s*:/;
const RE_FOR_LOOP_HEAD =
  /^\s*for\s+([A-Za-z_]\w*)\s+in\s+([A-Za-z_][\w.]*(?:\([^()]*\))*(?:\.all\(\))?)\s*:/;
const LOOP_VAR_ATTR_RE = /\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b/g;
const MAX_LOOP_LINES = 15;

/**
 * Methods that return a lazily-evaluated QuerySet and accept a
 * `select_related()` / `prefetch_related()` chain after them. Mirrors
 * `_QS_SOURCE_METHODS` in the CLI's `django_orm_lens/query_analyzer.py`.
 */
const QS_SOURCE_METHODS = new Set([
  'all',
  'filter',
  'exclude',
  'annotate',
  'distinct',
  'order_by',
  'values',
  'values_list',
  'reverse',
  'none',
  'iterator',
  'only',
  'defer',
  'using',
]);

function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/**
 * Can `expr` — the iterable of a `for` head — be a QuerySet?
 *
 * Mirrors the source gate the CLI's N+1 analyzer applies in
 * `_process_loop`: a chain is in scope only when it roots at
 * `<Model>.objects.<method>(...)` or begins with a queryset-producing
 * method. Anything else — `range(10)`, `os.listdir(path)`,
 * `apps.get_models()` — iterates ranges, lists or model *classes*, where
 * attribute access is an in-memory lookup and `select_related()` has
 * nothing to act on.
 *
 * A bare name (`for user in users:`) names no call, so it is evidence
 * neither way: the CLI resolves it through an AST binding tracker, which a
 * line-oriented rule has no equivalent of, so those loops keep reporting.
 */
function mayIterateQuerySet(expr: string): boolean {
  const callAt = expr.indexOf('(');
  if (callAt === -1) return true;
  const segments = expr.slice(0, callAt).split('.');
  // A bare `helper()` call is not a method call, so there is no chain.
  if (segments.length < 2) return false;
  // `<Model>.objects.<anything>()` is a manager call whatever follows.
  if (segments.length === 3 && segments[1] === 'objects') return true;
  return QS_SOURCE_METHODS.has(segments[segments.length - 1]);
}

/** DOL001 — `qs.count() > 0` → `qs.exists()`. */
const DOL001: Rule = {
  meta: {
    code: 'DOL001',
    title: 'Prefer .exists() over .count() > 0',
    category: 'performance',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL001.md`,
    since: '0.8.0',
    messages: {
      default:
        'Prefer .exists() over .count() > 0 — .exists() runs SELECT 1 LIMIT 1; .count() runs SELECT COUNT(*).',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_COUNT_GT_ZERO.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_COUNT_GT_ZERO.exec(text)) !== null) {
        out.push({
          code: 'DOL001',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'safe',
          fixHint: m[1],
        });
      }
    }
    return out;
  },
};

/** DOL002 — `qs.count() == 0` → `not qs.exists()`. */
const DOL002: Rule = {
  meta: {
    code: 'DOL002',
    title: 'Prefer not .exists() over .count() == 0',
    category: 'performance',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL002.md`,
    since: '0.8.0',
    messages: {
      default:
        'Prefer `not .exists()` over `.count() == 0` — no row count required.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_COUNT_EQ_ZERO.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_COUNT_EQ_ZERO.exec(text)) !== null) {
        out.push({
          code: 'DOL002',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'safe',
          fixHint: m[1],
        });
      }
    }
    return out;
  },
};

/** DOL003 — `qs.first() is None` → `not qs.exists()`. */
const DOL003: Rule = {
  meta: {
    code: 'DOL003',
    title: 'Prefer not .exists() over .first() is None',
    category: 'performance',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL003.md`,
    since: '0.8.0',
    messages: {
      default:
        'Prefer `not .exists()` over `.first() is None` — .first() fetches a row; .exists() only asks the DB.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_FIRST_IS_NONE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_FIRST_IS_NONE.exec(text)) !== null) {
        out.push({
          code: 'DOL003',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'safe',
          fixHint: m[1],
        });
      }
    }
    return out;
  },
};

/** DOL004 — `qs.first() is not None` → `qs.exists()`. */
const DOL004: Rule = {
  meta: {
    code: 'DOL004',
    title: 'Prefer .exists() over .first() is not None',
    category: 'performance',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL004.md`,
    since: '0.8.0',
    messages: {
      default:
        'Prefer `.exists()` over `.first() is not None` — avoid fetching a row.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_FIRST_IS_NOT_NONE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_FIRST_IS_NOT_NONE.exec(text)) !== null) {
        out.push({
          code: 'DOL004',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'safe',
          fixHint: m[1],
        });
      }
    }
    return out;
  },
};

/**
 * DOL005 — `.filter(a).exclude(b)` chain can often collapse to a single
 * `.filter(Q(a) & ~Q(b))`. Suggestion-only — the equivalence depends on
 * whether the two clauses touch the same row or not.
 */
const DOL005: Rule = {
  meta: {
    code: 'DOL005',
    title: 'Consider Q(...) over .filter().exclude() chain',
    category: 'django-idiom',
    defaultSeverity: 'hint',
    docsUrl: `${DOCS_BASE}/DOL005.md`,
    since: '0.8.0',
    messages: {
      default:
        '.filter(...).exclude(...) can often collapse to .filter(Q(...) & ~Q(...)) — clearer intent, one planner pass.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_FILTER_EXCLUDE_CHAIN.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_FILTER_EXCLUDE_CHAIN.exec(text)) !== null) {
        out.push({
          code: 'DOL005',
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
 * DOL006 — `for x in list(qs):` forces the whole QuerySet into memory
 * before iteration begins. Iterating the QuerySet directly streams and
 * respects `.iterator()` chunk_size. Safe to auto-drop the `list()`.
 */
const DOL006: Rule = {
  meta: {
    code: 'DOL006',
    title: 'Drop list() around a QuerySet in for-loop',
    category: 'performance',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL006.md`,
    since: '0.8.0',
    messages: {
      default:
        'Wrapping a QuerySet in list() forces full evaluation. Iterate {qs} directly — QuerySets are already iterable.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      const m = RE_LIST_OF_QS_IN_FOR.exec(text);
      if (!m) continue;
      const inner = m[1];
      const start = text.indexOf(`list(${inner})`);
      if (start < 0) continue;
      out.push({
        code: 'DOL006',
        messageId: 'default',
        args: { qs: inner },
        range: {
          line: i,
          startCol: start,
          endCol: start + `list(${inner})`.length,
        },
        applicability: 'safe',
        fixHint: inner,
      });
    }
    return out;
  },
};

/**
 * DOL007 — N+1 heuristic. After `for x in qs:` scan the loop body for
 * `x.<attr>` where `<attr>` is not a bare id/pk/save-like operation.
 * The loop head is gated by `mayIterateQuerySet` so loops over ranges,
 * lists and model classes stay out of scope.
 * Unsafe — cannot programmatically distinguish an FK access from a
 * plain field access without type info; user must review before fixing.
 */
const DOL007: Rule = {
  meta: {
    code: 'DOL007',
    title: 'Possible N+1: attribute access inside for-loop',
    category: 'performance',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL007.md`,
    since: '0.8.0',
    messages: {
      default:
        "Attribute access '{expr}' inside a loop over '{qs}' — consider .select_related() or .prefetch_related() to avoid an N+1.",
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const head = RE_FOR_LOOP_HEAD.exec(ctx.lineAt(i));
      if (!head) continue;
      const loopVar = head[1];
      const qsExpr = head[2];
      if (!mayIterateQuerySet(qsExpr)) continue;
      const window = ctx.windowAfter(i, MAX_LOOP_LINES);
      let seenForThisHead = false;
      for (let j = 0; j < window.length; j++) {
        const line = window[j];
        if (line.length > 0 && !/^\s/.test(line)) break;
        if (seenForThisHead) break;
        LOOP_VAR_ATTR_RE.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = LOOP_VAR_ATTR_RE.exec(line)) !== null) {
          if (m[1] !== loopVar) continue;
          const attr = m[2];
          if (attr.startsWith('_')) continue;
          if (attr === 'id' || attr === 'pk' || attr === 'save') continue;
          out.push({
            code: 'DOL007',
            messageId: 'default',
            args: { expr: m[0], qs: qsExpr },
            range: {
              line: i + 1 + j,
              startCol: m.index,
              endCol: m.index + m[0].length,
            },
            applicability: 'unsafe',
            fixHint: attr,
          });
          seenForThisHead = true;
          break;
        }
      }
    }
    return out;
  },
};

export const querysetRules: Rule[] = [
  DOL001,
  DOL002,
  DOL003,
  DOL004,
  DOL005,
  DOL006,
  DOL007,
];
