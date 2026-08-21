import { Finding, Rule, RuleContext } from './types';
import { lookupTypos } from '../lookupTypos';
import {
  MAX_ASSIGN_LOOKBACK,
  classifyAttr,
  isCovered,
  resolveLoopSource,
} from '../nPlusOne';

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
 * Method names that produce a new QuerySet, so a call ending in one is
 * still a QuerySet and the loop over it stays in scope.
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
  'alias',
  'dates',
  'datetimes',
  'union',
  'intersection',
  'difference',
  'select_related',
  'prefetch_related',
  'extra',
  'select_for_update',
  'raw',
]);

function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/**
 * Can `expr` — the iterable of a `for` head — be a QuerySet?
 *
 * An `expr` containing no `(` — a bare name, a dotted chain — is in
 * scope: it names no call, so the line carries no evidence either way, and
 * `users = User.objects.all()` is the common idiom.
 *
 * One that does contain a `(` is in scope only when the text before that
 * first `(` is exactly three dotted segments with `objects` in the middle
 * (`<Model>.objects.<method>`), or a dotted chain ending in a
 * queryset-producing method. Every other call-shaped source is skipped —
 * `range(10)`, `os.listdir(path)`, `apps.get_models()`,
 * `auditory_models()`, `self.get_queryset()` — because the call name alone
 * says nothing about what comes back and a line-oriented rule cannot
 * follow a callee's return.
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
 * The loop head is gated by `mayIterateQuerySet`, which skips a source
 * that looks like a call unless it names a queryset-producing method.
 *
 * Two gates from `../nPlusOne` keep the shape match from firing on code that
 * costs nothing, which is what issue #85 reported:
 *
 *   1. an attribute the schema says is a plain column — or that a known model
 *      does not declare at all, which is how a Python property looks — is
 *      skipped. Needs `ctx.index`; without one this gate is simply off.
 *   2. a relation the chain already spans with `.select_related(...)` /
 *      `.prefetch_related(...)` is skipped. Needs no schema, so it applies on
 *      a cold start too — and it is the gate that stops the rule from
 *      contradicting code that has already taken its advice.
 *
 * Still `unsafe` when it does fire: without type inference an FK access and a
 * property access can share a shape, so the user reviews before fixing.
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
      // The chain that produced the loop's source is usually on an earlier
      // line (`codes = list(Model.objects.select_related("x"))`), so both the
      // model and its coverage have to be recovered from above the head.
      const source = resolveLoopSource(
        qsExpr,
        ctx.windowBefore(i, MAX_ASSIGN_LOOKBACK),
      );
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
          // Gate 1 — the schema knows this attribute costs nothing.
          const kind =
            ctx.index && source.model
              ? classifyAttr(ctx.index, source.model, attr)
              : null;
          if (kind === 'scalar') continue;
          // Gate 2 — the chain already spans it.
          if (isCovered(attr, kind, source)) continue;
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


/**
 * DOL008 — a lookup name that looks like a misspelling of a real one.
 *
 * The check itself lives in `lookupTypos`, which reuses the completion
 * resolver: it can only report a name completion would not have offered, and
 * only when there is a near match to suggest. That is what keeps a red
 * underline off correct code — see the module comment there for why the bar
 * is higher for a diagnostic than for a completion.
 *
 * Silent without `ctx.index`. A cold start, or a document scanned before the
 * first workspace scan finishes, has no schema to judge against, and guessing
 * would be exactly the failure this rule is designed around.
 */
const DOL008: Rule = {
  meta: {
    code: 'DOL008',
    title: 'Field name in a lookup looks misspelled',
    category: 'correctness',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL008.md`,
    since: '0.18.0',
    messages: {
      default: '{typed} is not a field on this model. Did you mean {suggestion}?',
    },
  },
  check(ctx: RuleContext): Finding[] {
    if (!ctx.index) return [];
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      for (const typo of lookupTypos(text, ctx.index)) {
        out.push({
          code: 'DOL008',
          messageId: 'default',
          args: { typed: typo.typed, suggestion: typo.suggestion },
          range: { line: i, startCol: typo.startCol, endCol: typo.endCol },
          // The suggestion is a guess about intent, however close the spelling
          // is. Renaming a lookup unattended could silently change what a
          // query returns, so it is offered and never auto-applied.
          applicability: 'suggestion',
        });
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
  DOL008,
];
