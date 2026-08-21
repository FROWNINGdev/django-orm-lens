/**
 * Schema-aware support for DOL007 (possible N+1 inside a for-loop).
 *
 * Why this module exists
 * ----------------------
 * DOL007 used to be pure text shape: `for x in <queryset>:` followed by any
 * `x.<attr>` in the body. That fires on a local column, an inherited Python
 * property, and even a foreign key the very same statement already covered
 * with `.select_related()` — reported as issue #85, with four reproducers.
 * The practical result is that the rule has to be disabled workspace-wide,
 * which also loses the true positives it exists to catch.
 *
 * The Python CLI gets this right by construction: `NPlusOneScanner._classify`
 * resolves the attribute against the parsed schema and skips a declared
 * non-relational field, and `_chain_prefetch_args` skips a relation the chain
 * already prefetches. Per the parser-parity contract the CLI is the reference
 * and the TypeScript side is what lags, so this module ports those two gates
 * rather than inventing a third set of semantics.
 *
 * The two gates are deliberately independent
 * ------------------------------------------
 * Gate 2 (already covered by the chain) needs no schema at all — it is pure
 * string matching against `.select_related(...)` arguments — so it applies
 * even on a cold start, and on its own it fixes the case where the rule
 * contradicts code that has already taken its advice. Gate 1 (scalar) needs
 * the workspace index and stays off without one. That split is why this is
 * not a single `if (index)` branch.
 */

import { ParsedField, ParsedModel, WorkspaceIndex } from './types';

/** What an attribute access on a model instance costs. */
export type AccessKind = 'fk' | 'o2o' | 'm2m' | 'reverse' | 'scalar';

/** How far above the loop head to look for the binding that produced it. */
export const MAX_ASSIGN_LOOKBACK = 40;

/** Guard against a cycle of self-rebinding names (`qs = qs.filter(...)`). */
const MAX_HOPS = 4;

/** `<Model>.objects` at the head of an expression. */
const RE_MANAGER_ROOT = /^([A-Za-z_]\w*)\s*\.\s*objects\b/;

/** `name = <rhs>` — a plain binding, not `==` and not an augmented assign. */
const RE_ASSIGN = /^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$/;

/** A line that starts a new scope, so bindings above it are not in effect. */
const RE_SCOPE = /^\s*(?:def|class|async\s+def)\s/;

/**
 * Methods that keep a QuerySet a QuerySet, so `qs = base.filter(...)` can hop
 * to whatever `base` resolved to. Mirrors `_QS_SOURCE_METHODS` in the CLI.
 */
const QUERY_METHODS = new Set([
  'all',
  'filter',
  'exclude',
  'annotate',
  'alias',
  'distinct',
  'order_by',
  'reverse',
  'select_related',
  'prefetch_related',
  'only',
  'defer',
  'using',
  'none',
  'iterator',
]);

/**
 * A reverse accessor Django creates by default (`comment_set`). An explicit
 * `related_name` is matched by name instead — see `reverseNamesFor`.
 */
const RE_REVERSE_SUFFIX = /_set$/;

export interface LoopSource {
  /** Model whose instances the loop yields, when resolvable. */
  model: string | null;
  /** Lookups already spanned by `.select_related(...)`; `*` means all FKs. */
  selectRelated: Set<string>;
  /** Lookups already spanned by `.prefetch_related(...)`; `*` means all. */
  prefetchRelated: Set<string>;
}

/**
 * Pull the string literals out of every `.select_related(...)` and
 * `.prefetch_related(...)` in `expr`.
 *
 * Only the first segment of a `a__b__c` lookup is kept, because that is the
 * attribute the loop body can name. A no-argument `.select_related()` spans
 * every FK, recorded as the wildcard `*` exactly as the CLI does.
 *
 * `Prefetch("comments", queryset=...)` contributes its first positional
 * string, which is why the literal scan is not anchored to the call's start.
 */
function collectChainArgs(expr: string, method: string): Set<string> {
  const out = new Set<string>();
  const re = new RegExp(`\\.${method}\\s*\\(`, 'g');
  let m: RegExpExecArray | null;
  while ((m = re.exec(expr)) !== null) {
    // Walk to the matching close paren so a nested `Prefetch(...)` is included
    // rather than truncating the argument list at the first `)`.
    let depth = 1;
    let i = m.index + m[0].length;
    const start = i;
    for (; i < expr.length && depth > 0; i++) {
      if (expr[i] === '(') depth++;
      else if (expr[i] === ')') depth--;
    }
    const args = expr.slice(start, Math.max(start, i - 1));
    if (args.trim() === '') {
      out.add('*');
      continue;
    }
    const lit = /['"]([^'"]*)['"]/g;
    let s: RegExpExecArray | null;
    while ((s = lit.exec(args)) !== null) {
      const head = s[1].split('__', 1)[0];
      if (head) out.add(head);
    }
  }
  return out;
}

/** Strip the wrappers a queryset is commonly materialised through. */
function unwrap(expr: string): string {
  let e = expr.trim();
  for (;;) {
    const m = e.match(/^(?:list|tuple|set|iter|reversed|enumerate)\s*\((.*)\)$/s);
    if (!m) return e;
    e = m[1].trim();
  }
}

/** Net paren depth of `s`, ignoring what is inside string literals. */
function parenDepth(s: string): number {
  let depth = 0;
  let quote: string | null = null;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quote) {
      if (c === '\\') i++;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(' || c === '[') depth++;
    else if (c === ')' || c === ']') depth--;
  }
  return depth;
}

/**
 * Re-join a binding that was wrapped across lines.
 *
 * A queryset long enough to be worth a `.select_related()` is usually long
 * enough that a formatter has already broken it, which is how the issue-#85
 * case-4 reproducer looks: `definitions = list(` on one line and the manager
 * chain on the next. Reading only the first line yields the bare text `list(`,
 * no model, and the rule falls back to the shape heuristic it is meant to be
 * gating — so the wrapped form must be reassembled before anything else.
 */
function joinStatement(
  lines: readonly string[],
  start: number,
  firstRhs: string,
): string {
  let rhs = firstRhs;
  for (let k = start + 1; k < lines.length && parenDepth(rhs) > 0; k++) {
    rhs += ' ' + (lines[k] ?? '').trim();
  }
  return rhs;
}

function union(a: Set<string>, b: Set<string>): Set<string> {
  const out = new Set(a);
  for (const v of b) out.add(v);
  return out;
}

/**
 * Work out which model a loop iterates, and what its chain already spans.
 *
 * `qsExpr` is the loop head's source expression. When it is a bare name the
 * binding is looked up in `precedingLines`, because the reproducers in issue
 * #85 all put the chain on an assignment (`codes = list(OneTimeCode.objects
 * .select_related("issued_by"))`) and iterate the local afterwards — so
 * reading only the loop head would miss both the model and the coverage.
 *
 * A binding whose right-hand side is not recognised stops the walk instead of
 * falling through to an older binding of the same name, matching
 * `ormCompletions.resolveName`: answering with a model the code no longer
 * holds is worse than answering with nothing.
 */
export function resolveLoopSource(
  qsExpr: string,
  precedingLines: readonly string[] = [],
): LoopSource {
  const seen = new Set<string>();

  function walk(expr: string, upto: number, depth: number): LoopSource {
    const e = unwrap(expr);
    const select = collectChainArgs(e, 'select_related');
    const prefetch = collectChainArgs(e, 'prefetch_related');

    const direct = e.match(RE_MANAGER_ROOT);
    if (direct) {
      return { model: direct[1], selectRelated: select, prefetchRelated: prefetch };
    }

    // A bare name — follow it to its binding.
    const bare = e.match(/^([A-Za-z_]\w*)$/);
    const chained = e.match(/^([A-Za-z_]\w*)\s*\.\s*(\w+)\s*\(/);
    const name = bare
      ? bare[1]
      : chained && QUERY_METHODS.has(chained[2])
        ? chained[1]
        : null;
    if (!name || depth >= MAX_HOPS || seen.has(`${name}@${upto}`)) {
      return { model: null, selectRelated: select, prefetchRelated: prefetch };
    }
    seen.add(`${name}@${upto}`);

    for (let i = upto; i >= 0; i--) {
      const line = precedingLines[i];
      if (line === undefined) continue;
      if (RE_SCOPE.test(line)) break;
      const assign = line.match(RE_ASSIGN);
      if (!assign || assign[1] !== name) continue;
      // Guard against `==` / `!=` being read as a binding by RE_ASSIGN.
      if (/^[=!<>]/.test(assign[2])) break;
      const inner = walk(joinStatement(precedingLines, i, assign[2]), i - 1, depth + 1);
      return {
        model: inner.model,
        selectRelated: union(select, inner.selectRelated),
        prefetchRelated: union(prefetch, inner.prefetchRelated),
      };
    }
    return { model: null, selectRelated: select, prefetchRelated: prefetch };
  }

  return walk(qsExpr, precedingLines.length - 1, 0);
}

/**
 * First model in the index carrying this name.
 *
 * Same short-name lookup `factoryGenerator.findModelByRef` uses. Two apps can
 * legitimately declare the same model name; resolving to the first is the
 * established convention here, and the consequence is bounded because an
 * attribute this model does not declare is treated as scalar rather than
 * reported.
 */
function findModel(index: WorkspaceIndex, name: string): ParsedModel | undefined {
  for (const app of index.apps) {
    for (const model of app.models) {
      if (model.name === name) return model;
    }
  }
  return undefined;
}

function kindOfField(field: ParsedField): AccessKind {
  if (!field.isRelation) return 'scalar';
  switch (field.relationKind) {
    case 'ForeignKey':
      return 'fk';
    case 'OneToOneField':
      return 'o2o';
    case 'ManyToManyField':
      return 'm2m';
    default:
      return 'fk';
  }
}

/**
 * Names by which *other* models reach back into `model` — an explicit
 * `related_name`, or Django's default `<lowercase-model>_set`.
 *
 * Needed because a reverse manager is not a field on `model` and would
 * otherwise fall into the "not declared here, so scalar" branch, silencing a
 * genuine N+1 that `.prefetch_related()` is exactly the fix for.
 */
function reverseNamesFor(index: WorkspaceIndex, model: ParsedModel): Set<string> {
  const out = new Set<string>();
  for (const app of index.apps) {
    for (const other of app.models) {
      for (const f of [...other.fields, ...other.inheritedFields]) {
        if (!f.isRelation) continue;
        const target = (f.relatedModel ?? '').split('.').pop();
        if (target !== model.name) continue;
        if (f.relatedName && f.relatedName !== '+') out.add(f.relatedName);
        else out.add(`${other.name.toLowerCase()}_set`);
      }
    }
  }
  return out;
}

/**
 * Classify `attr` read off an instance of `modelName`.
 *
 * Returns `null` when the model is not in the index at all — the caller then
 * has no schema opinion and falls back to the text heuristic. Returns
 * `'scalar'` when the model *is* known but does not declare the attribute:
 * that is the case-3 shape from issue #85, a Python property on an abstract
 * base, and the CLI bails on it for the same reason — an attribute the schema
 * has never heard of is far more often a property than a relation, and
 * guessing "relation" is what produced the false positives.
 */
export function classifyAttr(
  index: WorkspaceIndex,
  modelName: string,
  attr: string,
): AccessKind | null {
  const model = findModel(index, modelName);
  if (!model) return null;
  for (const f of [...model.fields, ...model.inheritedFields]) {
    if (f.name === attr) return kindOfField(f);
  }
  if (reverseNamesFor(index, model).has(attr)) return 'reverse';
  if (RE_REVERSE_SUFFIX.test(attr)) return 'reverse';
  return 'scalar';
}

/**
 * True when `attr` of kind `kind` is already spanned by the chain, so
 * reporting it would contradict code that has taken the rule's advice.
 *
 * Schema-free on purpose: with no index `kind` is `null` and the lookup is
 * checked against both sets, which is enough to clear case 2 on a cold start.
 */
export function isCovered(
  attr: string,
  kind: AccessKind | null,
  source: LoopSource,
): boolean {
  const inSelect = source.selectRelated.has('*') || source.selectRelated.has(attr);
  const inPrefetch = source.prefetchRelated.has('*') || source.prefetchRelated.has(attr);
  if (kind === 'fk' || kind === 'o2o') return inSelect;
  if (kind === 'm2m' || kind === 'reverse') return inPrefetch;
  return inSelect || inPrefetch;
}
