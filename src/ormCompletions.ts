/**
 * Field completion inside `Post.objects.filter(...)` and its siblings.
 *
 * The whole decision is a pure function over a line of text and the parsed
 * index: no `vscode` import, no document, no cursor object. That is deliberate
 * and it is the house pattern — `starPrompt.shouldPrompt` and
 * `webviewMessages.acceptsMessage` are shaped the same way, for the reason
 * #55 made expensive: a decision reachable only through a VS Code host is a
 * decision no test reaches, and the suite stays green while it is wrong.
 *
 * Scope is deliberately "best effort, never wrong-looking". Resolving a
 * queryset's model in general needs type inference across assignments,
 * managers and mixins. What is implemented is the shape that covers the great
 * majority of real filter calls — a literal `<Model>.objects.<method>(` on the
 * same line — and every shape outside it returns nothing rather than a guess.
 * An empty list costs the user nothing; a list of fields from the wrong model
 * costs them a debugging session.
 */

import type { ParsedField, ParsedModel, WorkspaceIndex } from './types';

/**
 * Manager methods whose arguments are field lookups.
 *
 * `values`, `values_list`, `only`, `defer` and `order_by` take field *names*
 * as strings rather than kwargs, but the useful completion there is the same
 * field list, so they are in scope too. `order_by` additionally accepts a
 * leading `-`, handled where the partial token is read.
 */
export const QUERY_METHODS = new Set([
  'filter',
  'exclude',
  'get',
  'get_or_create',
  'update_or_create',
  'annotate',
  'aggregate',
  'order_by',
  'values',
  'values_list',
  'only',
  'defer',
  'distinct',
  'create',
  'update',
]);

/** Lookups every field type accepts. */
const COMMON_LOOKUPS = ['exact', 'in', 'isnull'];

const TEXT_LOOKUPS = [
  'iexact',
  'contains',
  'icontains',
  'startswith',
  'istartswith',
  'endswith',
  'iendswith',
  'regex',
  'iregex',
];

const ORDERED_LOOKUPS = ['gt', 'gte', 'lt', 'lte', 'range'];

const DATE_PARTS = ['year', 'month', 'day', 'week', 'week_day', 'quarter', 'date'];

const TIME_PARTS = ['hour', 'minute', 'second', 'time'];

const TEXT_FIELDS = /^(Char|Text|Slug|Email|URL|File|Image|FilePath|IP|GenericIP)/;
const NUMBER_FIELDS =
  /^(Integer|BigInteger|SmallInteger|PositiveInteger|PositiveSmallInteger|PositiveBigInteger|Float|Decimal|Duration|AutoField|BigAutoField|SmallAutoField)/;
const DATE_FIELDS = /^(Date|DateTime)/;
const TIME_FIELDS = /^(DateTime|Time)/;

/**
 * The lookups Django accepts on `field`, most useful first.
 *
 * Ordering matters more than completeness: the list is what a user scans, and
 * `icontains` on a CharField is wanted far more often than `iregex`.
 */
export function lookupsForField(field: ParsedField): string[] {
  if (field.isRelation) {
    // A relation still accepts `__exact` / `__in` against a pk or instance,
    // and `__isnull` is the idiomatic "has no related row" test.
    return [...COMMON_LOOKUPS];
  }
  const type = field.type;
  if (/^Boolean/.test(type)) {
    // `__exact` and `__isnull` only; ordered lookups are meaningless here and
    // listing them is noise in the one place the list should be shortest.
    return [...COMMON_LOOKUPS];
  }
  const out: string[] = [...COMMON_LOOKUPS];
  if (TEXT_FIELDS.test(type)) out.push(...TEXT_LOOKUPS);
  if (NUMBER_FIELDS.test(type) || DATE_FIELDS.test(type) || /^Time/.test(type)) {
    out.push(...ORDERED_LOOKUPS);
  }
  if (DATE_FIELDS.test(type)) out.push(...DATE_PARTS);
  if (TIME_FIELDS.test(type)) out.push(...TIME_PARTS);
  return out;
}

export interface QueryContext {
  /** Model whose fields are in scope, as written in the source. */
  model: string;
  /** The manager method the cursor sits inside. */
  method: string;
  /** Lookup path typed so far, e.g. `author__na`. May be empty. */
  partial: string;
}

/**
 * Find the innermost unclosed `(` in `line`, ignoring parens inside strings.
 *
 * :returns: index of that paren, or -1 when every paren is balanced — the
 *   common "cursor is not inside a call" case.
 */
function innermostOpenParen(line: string): number {
  let quote: string | null = null;
  const stack: number[] = [];
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      if (ch === quote && line[i - 1] !== '\\') quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (ch === '(') stack.push(i);
    else if (ch === ')') stack.pop();
  }
  return stack.length ? stack[stack.length - 1] : -1;
}

/**
 * Read the partial lookup path the cursor is sitting on.
 *
 * :returns: the token, or `null` when the cursor is somewhere a field name
 *   cannot go — past an `=` (typing a value), or past a closed string.
 */
function partialToken(args: string): string | null {
  // Only the argument under the cursor matters. Splitting on the last comma is
  // safe because a comma inside a nested call or string would have made that
  // paren the innermost one instead.
  const lastComma = args.lastIndexOf(',');
  let seg = lastComma >= 0 ? args.slice(lastComma + 1) : args;
  // `filter(title=` — the cursor is in the value, where field names do not go.
  if (seg.includes('=')) return null;
  seg = seg.trimStart();
  // `order_by('-crea` and `values('ti` are the string form of the same
  // completion, so a leading quote is stripped rather than rejected. A closing
  // quote means the string is finished and the cursor sits past it.
  if (seg.startsWith("'") || seg.startsWith('"')) {
    const q = seg[0];
    seg = seg.slice(1);
    if (seg.includes(q)) return null;
  }
  if (seg.startsWith('-')) seg = seg.slice(1); // order_by descending
  return /^[A-Za-z_][A-Za-z0-9_]*$|^$/.test(seg) ? seg : null;
}

/** Expression wrappers worth stepping out of to find the naming call. */
const WRAPPERS = /\b(Q|F|Count|Sum|Avg|Min|Max|Exists|OuterRef|Subquery)\s*$/;

/**
 * Pull the model name out of `... Post.objects` / `... Post.objects.filter(x)`.
 *
 * Anchored at the end so a chained call resolves to the model that started the
 * chain rather than to some earlier name on the line.
 */
function receiverModel(before: string): string | null {
  const m = before.match(
    /([A-Za-z_]\w*)\s*\.\s*objects\b(?:\s*\.\s*\w+\s*\([^()]*\))*\s*$/
  );
  return m ? m[1] : null;
}

/**
 * Work out which model's fields belong at the cursor.
 *
 * :param linePrefix: text from the start of the line up to the cursor.
 * :returns: the context, or `null` when the cursor is not in a recognised
 *   manager call.
 */
export function parseQueryContext(linePrefix: string): QueryContext | null {
  let head = linePrefix;
  // What the user is typing is always read from the *innermost* call, because
  // that is where the cursor is. Stepping outward afterwards only looks for
  // the call that names the model — re-reading the token out there would find
  // the wrapper's own name (`filter(Q(auth` would complete `Q`, not `auth`).
  let partial: string | null = null;
  // Up to two levels, so `filter(Q(auth` resolves: the innermost unclosed
  // paren belongs to `Q`, and the call that names the model is one out.
  for (let depth = 0; depth < 2; depth++) {
    const open = innermostOpenParen(head);
    if (open < 0) return null;
    if (partial === null) {
      partial = partialToken(head.slice(open + 1));
      if (partial === null) return null;
    }
    const before = head.slice(0, open);
    // Split the receiver from the method rather than matching the method
    // alone: `receiverModel` anchors at the end of its input, so it has to be
    // handed `Post.objects` / `Post.objects.filter(...)` with the method that
    // opened this paren already removed.
    const call = before.match(/^(.*)\.\s*([A-Za-z_]\w*)\s*$/);
    const method = call?.[2];
    if (call && method && QUERY_METHODS.has(method)) {
      const model = receiverModel(call[1]);
      if (!model) return null;
      return { model, method, partial };
    }
    if (!WRAPPERS.test(before)) return null;
    head = before;
  }
  return null;
}

/**
 * How many characters at the end of `linePrefix` the suggestion replaces.
 *
 * Suggestion labels carry the whole traversal path (`author__name`), so the
 * edit has to consume the whole path already typed. VS Code's default word
 * range stops at the last `__`, which would turn accepting `author__name`
 * after typing `author__na` into `author__author__name`. Lives here rather
 * than in the provider so the arithmetic is covered by the same suite as the
 * suggestions it has to line up with.
 */
export function lookupPathLength(linePrefix: string): number {
  return (linePrefix.match(/[A-Za-z0-9_]*$/)?.[0] ?? '').length;
}

export type SuggestionKind = 'field' | 'relation' | 'lookup';

export interface CompletionSuggestion {
  /** Full lookup path, so the editor filters it against what was typed. */
  label: string;
  /** Right-hand column in the completion list. */
  detail: string;
  kind: SuggestionKind;
  /** Ordering hint; lower sorts first. */
  sortGroup: number;
}

function modelIndex(index: WorkspaceIndex): Map<string, ParsedModel> {
  const byName = new Map<string, ParsedModel>();
  for (const app of index.apps) {
    for (const model of app.models) {
      // First declaration wins. Two apps declaring the same model name is
      // legal Django and one line of text cannot say which is meant; picking
      // deterministically beats picking differently on each keystroke.
      if (!byName.has(model.name)) byName.set(model.name, model);
    }
  }
  return byName;
}

/** Resolve `field`'s target model, following `'self'` back to its owner. */
function relatedModelOf(
  field: ParsedField,
  owner: ParsedModel,
  byName: Map<string, ParsedModel>
): ParsedModel | undefined {
  if (!field.isRelation || !field.relatedModel) return undefined;
  if (field.relatedModel === 'self') return owner;
  // `orders.Order` → `Order`; the parser may hand back either form.
  const tail = field.relatedModel.split('.').pop() ?? field.relatedModel;
  return byName.get(tail);
}

/**
 * Complete the lookup path at the cursor.
 *
 * :param linePrefix: text from the start of the line up to the cursor.
 * :returns: suggestions, or an empty array when nothing resolves with
 *   confidence. Never a guess.
 */
export function completionsAt(
  linePrefix: string,
  index: WorkspaceIndex
): CompletionSuggestion[] {
  const ctx = parseQueryContext(linePrefix);
  if (!ctx) return [];
  const byName = modelIndex(index);
  const root = byName.get(ctx.model);
  if (!root) return [];

  // Everything before the final `__` is already-committed traversal; the tail
  // is what the user is still typing.
  const parts = ctx.partial.split('__');
  const typed = parts.pop() ?? '';
  const walked = parts;
  const prefix = walked.length ? walked.join('__') + '__' : '';

  let current: ParsedModel | undefined = root;
  let lastField: ParsedField | undefined;
  for (const step of walked) {
    if (!current) return [];
    const field: ParsedField | undefined = current.fields.find((f) => f.name === step);
    if (!field) {
      // Not a field. It may be a lookup that is already complete
      // (`title__icontains`), in which case there is nothing further to offer.
      return [];
    }
    lastField = field;
    current = relatedModelOf(field, current, byName);
  }

  const out: CompletionSuggestion[] = [];

  if (current) {
    for (const field of current.fields) {
      const related = relatedModelOf(field, current, byName);
      out.push({
        label: prefix + field.name,
        detail: field.isRelation
          ? `${field.type} → ${related?.name ?? field.relatedModel ?? '?'}`
          : field.type,
        kind: field.isRelation ? 'relation' : 'field',
        sortGroup: field.isRelation ? 1 : 0,
      });
    }
    // `pk` is not in `fields` — the parser reports declared fields — but it is
    // valid in every lookup and is what people reach for constantly.
    out.push({
      label: prefix + 'pk',
      detail: 'primary key alias',
      kind: 'field',
      sortGroup: 0,
    });
  }

  // Lookups hang off the field walked into, whether or not it is a relation:
  // `author__isnull` is as valid as `title__icontains`.
  if (lastField) {
    for (const lookup of lookupsForField(lastField)) {
      out.push({
        label: prefix + lookup,
        detail: `lookup on ${lastField.type}`,
        kind: 'lookup',
        sortGroup: 2,
      });
    }
  }

  if (!typed) return out;
  const needle = typed.toLowerCase();
  return out.filter((s) => s.label.slice(prefix.length).toLowerCase().startsWith(needle));
}
