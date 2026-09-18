import { Finding, Rule, RuleContext } from './types';

/**
 * Raw SQL / database-session rules.
 *
 * Codes DOL041..DOL050 are reserved for this group. Codes are stable public
 * surface; do not renumber. When a rule is removed, its code stays retired.
 *
 * Like the queryset rules these are line-oriented (regex only), so the pass
 * stays O(lineCount) and works without a Python parser. The signal lives in
 * the SQL text itself — a GUC name survives parameterization, so
 * `cursor.execute('SET enable_seqscan = %s', ['off'])` is as visible as a
 * literal `off`.
 */

const DOCS_BASE =
  'https://github.com/FROWNINGdev/django-orm-lens/blob/main/docs/rules';

/**
 * Planner-toggling GUCs only.
 *
 * Deliberately not the whole `SET` surface. `search_path`, `timezone`,
 * `statement_timeout` and `work_mem` have legitimate per-request uses and
 * flagging them would drown the rule. The family below exists for one
 * purpose: telling the planner which plan shapes it may consider, which is
 * exactly the decision the planner exists to make.
 */
const RE_PLANNER_OVERRIDE =
  /\bSET\s+(?:(LOCAL|SESSION)\s+)?((?:enable_[a-z_]+)|plan_cache_mode|jit(?:_[a-z_]+)?)\s*(?:=|TO)\s*('[^']*'|[A-Za-z0-9_%.]+)/gi;

function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/**
 * DOL041 — raw SQL in application code overriding the query planner.
 *
 * `SET enable_hashjoin = off` (and friends) does not make a query faster;
 * it removes the planner's ability to choose otherwise. On a small dataset
 * the forced plan may look fine and then collapse as the filtered row set
 * grows — the classic case being a forced nested-loop join over a multi-level
 * `IN` chain. Worse, a plain `SET` is connection-scoped: with connection
 * pooling it leaks into whatever runs next on that connection. `SET LOCAL`
 * scopes the override to the transaction, which is the only form that has an
 * excuse, and even that is a judgement call the reviewer should see.
 *
 * No QuickFix on purpose: the safe repair is a query/index change, not a
 * mechanical text edit, so the finding is `unsafe`.
 */
const DOL041: Rule = {
  meta: {
    code: 'DOL041',
    title: 'Planner setting overridden in raw SQL',
    category: 'performance',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL041.md`,
    since: '0.19.0',
    messages: {
      default:
        'Planner setting {guc} = {value} is overridden here — this forces the query planner for every query on the connection and can turn a fast plan into a nested-loop scan as data grows. Fix the query or index instead; scope with SET LOCAL only when intentional.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_PLANNER_OVERRIDE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_PLANNER_OVERRIDE.exec(text)) !== null) {
        out.push({
          code: 'DOL041',
          messageId: 'default',
          args: { guc: m[2], value: m[3] },
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'unsafe',
        });
      }
    }
    return out;
  },
};

export const rawSqlRules: Rule[] = [DOL041];
