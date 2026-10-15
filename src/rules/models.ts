import { denormalizeRules } from './denormalize';
import { recommendedMetaName } from './indexNaming';
import { Finding, Rule, RuleContext } from './types';

/**
 * Model-definition rules.
 *
 * Codes DOL011..DOL020 are reserved for model-shape rules. Inspired by
 * flake8-django (DJ01, DJ08) but rewritten from scratch against real
 * Django source patterns. Regex-only — no AST — so multi-line detection
 * uses indentation-based class-body walking.
 *
 * Public callers: src/rules/index.ts aggregates modelRules into ALL_RULES.
 */

const DOCS_BASE =
  'https://github.com/nam-tong/orm-synapse/blob/main/docs/rules';

/** `models.CharField(...)` or `models.TextField(...)` — string-based fields. */
const RE_STRING_FIELD_LINE =
  /\b(?:models\.)?(CharField|TextField)\s*\(([^()]*)\)/g;
/** ForeignKey call opener — used to detect missing on_delete on the same line. */
const RE_FOREIGN_KEY_LINE =
  /\b(?:models\.)?ForeignKey\s*\(([^()]*)\)/g;
/** class Foo(models.Model): or class Foo(SomethingWithModel): */
const RE_CLASS_HEAD =
  /^(\s*)class\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:/;

/** Detect null=True in field-call argument body. */
function hasKwarg(argBody: string, kw: string): boolean {
  const re = new RegExp(`\\b${kw}\\s*=\\s*True\\b`);
  return re.test(argBody);
}

/** Detect the presence of a keyword argument by name (regardless of value). */
function hasKwargName(argBody: string, kw: string): boolean {
  const re = new RegExp(`\\b${kw}\\s*=`);
  return re.test(argBody);
}

/** Skip lines whose leading non-space char is `#`. */
function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/** Get leading whitespace prefix (spaces or tabs) for indent depth compare. */
function leadingIndent(line: string): string {
  const m = /^(\s*)/.exec(line);
  return m ? m[1] : '';
}

/**
 * Walk a class body starting at the line AFTER the class head. Yields each
 * body line until an outdent (line with indent <= classHeadIndent) closes
 * the block. Empty and comment lines are yielded too (caller filters).
 */
function* iterClassBody(
  ctx: RuleContext,
  classHeadLine: number,
  classHeadIndent: string,
): Generator<{ lineIndex: number; text: string }> {
  for (let i = classHeadLine + 1; i < ctx.lineCount; i++) {
    const text = ctx.lineAt(i);
    if (text.trim() === '') {
      yield { lineIndex: i, text };
      continue;
    }
    const indent = leadingIndent(text);
    // outdent — we're out of the class body
    if (indent.length <= classHeadIndent.length) return;
    yield { lineIndex: i, text };
  }
}

/**
 * DOL011 — CharField/TextField with `null=True`.
 *
 * Django's own docs: "Avoid using null on string-based fields such as
 * CharField and TextField. If a string-based field has null=True, that
 * means it has two possible values for 'no data': NULL, and the empty
 * string." Prefer `blank=True` (form-layer) instead.
 */
const DOL011: Rule = {
  meta: {
    code: 'DOL011',
    title: 'null=True on CharField/TextField',
    category: 'django-idiom',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL011.md`,
    since: '0.8.0',
    messages: {
      default:
        "Avoid null=True on {field} — Django's docs recommend blank=True for string-based fields (two 'no data' values NULL and '' otherwise).",
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_STRING_FIELD_LINE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_STRING_FIELD_LINE.exec(text)) !== null) {
        const argBody = m[2];
        if (!hasKwarg(argBody, 'null')) continue;
        out.push({
          code: 'DOL011',
          messageId: 'default',
          args: { field: m[1] },
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'suggestion',
        });
      }
    }
    return out;
  },
};

/**
 * DOL012 — Model class without a `__str__` method.
 *
 * flake8-django's DJ08: readable admin listings, shell debugging,
 * template `{{ obj }}` rendering all break without one. Suggestion-only
 * because auto-generating a body needs a reasonable field to render.
 */
const DOL012: Rule = {
  meta: {
    code: 'DOL012',
    title: 'Model without __str__ method',
    category: 'style',
    defaultSeverity: 'info',
    docsUrl: `${DOCS_BASE}/DOL012.md`,
    since: '0.8.0',
    messages: {
      default:
        'Model {name} defines no __str__ — admin listings and shell reprs will be unhelpful. Add def __str__(self) -> str.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      const head = RE_CLASS_HEAD.exec(text);
      if (!head) continue;
      const parents = head[3];
      // Only inspect Django models — either `models.Model` or a `...Model` base.
      if (!/\bmodels\.Model\b|(?<![A-Za-z_])Model\b/.test(parents)) continue;
      const className = head[2];
      const classIndent = head[1];
      let hasDunderStr = false;
      let hasMetaAbstract = false;
      for (const { text: body } of iterClassBody(ctx, i, classIndent)) {
        if (/^\s*def\s+__str__\s*\(/.test(body)) {
          hasDunderStr = true;
          break;
        }
        if (/^\s*abstract\s*=\s*True\b/.test(body)) hasMetaAbstract = true;
      }
      if (hasDunderStr) continue;
      if (hasMetaAbstract) continue;
      const startCol = text.indexOf('class');
      const endCol = startCol + `class ${className}`.length;
      out.push({
        code: 'DOL012',
        messageId: 'default',
        args: { name: className },
        range: { line: i, startCol, endCol },
        applicability: 'suggestion',
      });
    }
    return out;
  },
};

/**
 * DOL013 — ForeignKey / OneToOneField / ManyToManyField called without an
 * explicit `on_delete=`. Django dropped the default in 2.0 — omitting it
 * on FK/1to1 is a hard TypeError, but on models still-being-written it's
 * easy to miss. Detect at author-time.
 *
 * Applicability: suggestion (we insert `on_delete=models.CASCADE` as a
 * template — user must decide the real behaviour).
 */
const DOL013: Rule = {
  meta: {
    code: 'DOL013',
    title: 'ForeignKey without on_delete',
    category: 'correctness',
    defaultSeverity: 'error',
    docsUrl: `${DOCS_BASE}/DOL013.md`,
    since: '0.8.0',
    messages: {
      default:
        'ForeignKey requires on_delete — this raises TypeError at model-load time. Add on_delete=models.CASCADE (or PROTECT/SET_NULL/SET_DEFAULT/DO_NOTHING).',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_FOREIGN_KEY_LINE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_FOREIGN_KEY_LINE.exec(text)) !== null) {
        const argBody = m[1];
        if (hasKwargName(argBody, 'on_delete')) continue;
        out.push({
          code: 'DOL013',
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
 * DOL014 — CharField without `max_length=`. Django requires max_length
 * for CharField; omitting it errors at model-load. Author-time hint.
 */
const DOL014: Rule = {
  meta: {
    code: 'DOL014',
    title: 'CharField without max_length',
    category: 'correctness',
    defaultSeverity: 'error',
    docsUrl: `${DOCS_BASE}/DOL014.md`,
    since: '0.8.0',
    messages: {
      default:
        'CharField requires max_length — this errors at model-load. Add max_length=... (255 is a common default).',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    const RE = /\b(?:models\.)?CharField\s*\(([^()]*)\)/g;
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE.exec(text)) !== null) {
        const argBody = m[1];
        if (hasKwargName(argBody, 'max_length')) continue;
        out.push({
          code: 'DOL014',
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
 * DOL015 — TextField WITH `max_length=`. TextField maps to TEXT/CLOB;
 * max_length is only cosmetic (form-layer) and confuses readers. Django
 * docs explicitly note: "TextField max_length is not enforced at the DB
 * level." Recommend either dropping to CharField or removing the kwarg.
 */
const DOL015: Rule = {
  meta: {
    code: 'DOL015',
    title: 'TextField with max_length has no DB effect',
    category: 'style',
    defaultSeverity: 'hint',
    docsUrl: `${DOCS_BASE}/DOL015.md`,
    since: '0.8.0',
    messages: {
      default:
        'max_length on TextField is only enforced at form layer, not the DB. Use CharField if you need a DB limit, or drop max_length.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    const RE = /\b(?:models\.)?TextField\s*\(([^()]*)\)/g;
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE.exec(text)) !== null) {
        const argBody = m[1];
        if (!hasKwargName(argBody, 'max_length')) continue;
        out.push({
          code: 'DOL015',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'suggestion',
        });
      }
    }
    return out;
  },
};

/** `models.Index(`, `GinIndex(`, `UniqueConstraint(`, `CheckConstraint(`. */
const RE_NAMED_META_CALL =
  /\b(?:models\.)?((?:[A-Z]\w*)?Index|UniqueConstraint|CheckConstraint)\s*\(/g;

const RE_META_HEAD = /^(\s*)class\s+Meta\b[^:]*:/;
const RE_TOGETHER = /^(\s*)(index_together|unique_together)\s*=/;

/**
 * Argument text of the call whose opening `(` is at `openIdx` on `startLine`.
 * The opening paren itself is not included. Stops at the matching close.
 */
function readCallArgs(ctx: RuleContext, startLine: number, openIdx: number): string {
  let depth = 0;
  let args = '';
  for (let line = startLine; line < ctx.lineCount; line++) {
    const text = ctx.lineAt(line);
    for (let i = line === startLine ? openIdx : 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '(') {
        depth++;
        if (depth > 1) args += ch;
        continue;
      }
      if (ch === ')') {
        depth--;
        if (depth === 0) return args;
        args += ch;
        continue;
      }
      if (depth > 0) args += ch;
    }
    if (depth > 0) args += '\n';
  }
  return args;
}

/**
 * True when `name=` is a keyword of this call, not of a nested call or a
 * string. `condition=Q(name="active")` does not count; `name="idx_a"` does.
 */
function hasTopLevelName(args: string): boolean {
  let depth = 0;
  let bracket = 0;
  let brace = 0;
  let quote: "'" | '"' | null = null;
  for (let i = 0; i < args.length; i++) {
    const ch = args[i];
    if (quote) {
      if (ch === '\\') {
        i++;
        continue;
      }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(') depth++;
    else if (ch === ')') depth--;
    else if (ch === '[') bracket++;
    else if (ch === ']') bracket--;
    else if (ch === '{') brace++;
    else if (ch === '}') brace--;
    else if (depth === 0 && bracket === 0 && brace === 0 && /^name\s*=/.test(args.slice(i))) {
      return true;
    }
  }
  return false;
}

/**
 * DOL016 — Meta index or uniqueness declaration with no explicit name.
 *
 * `index_together` and `unique_together` cannot name their entries at all.
 * `models.Index`, postgres `*Index`, `UniqueConstraint`, and `CheckConstraint`
 * can, via `name=`. The rule only looks inside `class Meta`.
 */
const DOL016: Rule = {
  meta: {
    code: 'DOL016',
    title: 'Meta index or constraint without a name',
    category: 'correctness',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL016.md`,
    since: '0.19.4',
    messages: {
      together:
        '{option} cannot name its entries. Use indexes/constraints with an explicit name= instead.',
      call: '{kind} is missing name=. Name every index and constraint in Meta explicitly.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const head = RE_META_HEAD.exec(ctx.lineAt(i));
      if (!head) continue;
      for (const { lineIndex, text } of iterClassBody(ctx, i, head[1])) {
        if (isCommentLine(text)) continue;
        const together = RE_TOGETHER.exec(text);
        if (together) {
          const option = together[2];
          const startCol = text.indexOf(option);
          out.push({
            code: 'DOL016',
            messageId: 'together',
            args: { option },
            range: { line: lineIndex, startCol, endCol: startCol + option.length },
            applicability: 'unsafe',
          });
        }
        RE_NAMED_META_CALL.lastIndex = 0;
        let call: RegExpExecArray | null;
        while ((call = RE_NAMED_META_CALL.exec(text)) !== null) {
          const openIdx = call.index + call[0].length - 1;
          const args = readCallArgs(ctx, lineIndex, openIdx);
          if (hasTopLevelName(args)) continue;
          out.push({
            code: 'DOL016',
            messageId: 'call',
            args: { kind: call[1] },
            range: {
              line: lineIndex,
              startCol: call.index,
              endCol: call.index + call[0].length,
            },
            applicability: 'unsafe',
          });
        }
      }
    }
    return out;
  },
};

interface NameLiteral {
  line: number;
  startCol: number;
  endCol: number;
  value: string;
  quote: '"' | "'";
}

/**
 * Top-level `name=` string and `fields=` list of one Meta index or constraint
 * call. The opening `(` is at `openIdx` on `startLine`. Nested calls are
 * ignored. Returns undefined fields when the list is not plain strings.
 */
function readMetaCall(
  ctx: RuleContext,
  startLine: number,
  openIdx: number,
): { name?: NameLiteral; fields?: string[] } {
  let depth = 0;
  let bracket = 0;
  let brace = 0;
  let quote: '"' | "'" | null = null;
  let name: NameLiteral | undefined;
  let fields: string[] | undefined;
  let fieldsInvalid = false;
  const collecting: string[] = [];
  let inFields = false;
  let fieldBracket = 0;

  for (let line = startLine; line < ctx.lineCount; line++) {
    const text = ctx.lineAt(line);
    for (let i = line === startLine ? openIdx : 0; i < text.length; i++) {
      const ch = text[i];
      if (quote) {
        if (ch === '\\') {
          i++;
          continue;
        }
        if (ch === quote) quote = null;
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch;
        if (inFields && fieldBracket === 1) {
          const end = text.indexOf(ch, i + 1);
          if (end < 0) {
            fieldsInvalid = true;
            quote = null;
            continue;
          }
          collecting.push(text.slice(i + 1, end));
          i = end;
          quote = null;
        }
        continue;
      }
      if (!inFields && depth === 1 && bracket === 0 && brace === 0) {
        const rest = text.slice(i);
        const nameMatch = /^name\s*=\s*(['"])/.exec(rest);
        if (nameMatch) {
          const q = nameMatch[1] as '"' | "'";
          const valueStart = i + nameMatch[0].length;
          const valueEnd = text.indexOf(q, valueStart);
          if (valueEnd >= 0) {
            name = {
              line,
              startCol: i + nameMatch[0].length - 1,
              endCol: valueEnd + 1,
              value: text.slice(valueStart, valueEnd),
              quote: q,
            };
            i = valueEnd;
          }
          continue;
        }
        const fieldsMatch = /^fields\s*=\s*([\[(])/.exec(rest);
        if (fieldsMatch) {
          inFields = true;
          fieldBracket = 1;
          fields = collecting;
          i += fieldsMatch[0].length - 1;
          continue;
        }
      }
      if (inFields) {
        if (ch === '[' || ch === '(') fieldBracket++;
        else if (ch === ']' || ch === ')') {
          fieldBracket--;
          if (fieldBracket === 0) inFields = false;
        } else if (/[A-Za-z0-9_]/.test(ch)) {
          fieldsInvalid = true;
        }
        continue;
      }
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0) {
          return { name, fields: fieldsInvalid ? undefined : fields };
        }
      } else if (ch === '[') bracket++;
      else if (ch === ']') bracket--;
      else if (ch === '{') brace++;
      else if (ch === '}') brace--;
    }
  }
  return { name, fields: fieldsInvalid ? undefined : fields };
}

/**
 * DOL017 — a Meta index or unique constraint whose name does not match the
 * MySQL naming convention. Missing names stay on DOL016.
 */
const DOL017: Rule = {
  meta: {
    code: 'DOL017',
    title: 'Meta index or unique name breaks the MySQL naming convention',
    category: 'style',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL017.md`,
    since: '0.19.4',
    messages: {
      mismatch: "{kind} name '{name}' should be '{recommended}'.",
      truncated:
        "{kind} name '{name}' should be '{recommended}'. The convention shortens it to 64 characters.",
    },
  },
  check(ctx: RuleContext): Finding[] {
    // The convention is MySQL's; it means nothing on another engine.
    if (ctx.dbEngine === 'postgres' || ctx.dbEngine === 'sqlite') return [];
    const out: Finding[] = [];
    let modelName: string | undefined;
    let modelIndent = -1;
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      const modelHead = RE_CLASS_HEAD.exec(text);
      if (modelHead && modelHead[2] !== 'Meta') {
        modelName = modelHead[2];
        modelIndent = modelHead[1].length;
        continue;
      }
      const metaHead = RE_META_HEAD.exec(text);
      if (!metaHead || !modelName || metaHead[1].length <= modelIndent) continue;

      let dbTable: string | undefined;
      const calls: { kind: string; line: number; openIdx: number }[] = [];
      for (const body of iterClassBody(ctx, i, metaHead[1])) {
        if (isCommentLine(body.text)) continue;
        const table = /^\s*db_table\s*=\s*(['"])([^'"]+)\1/.exec(body.text);
        if (table) dbTable = table[2];
        RE_NAMED_META_CALL.lastIndex = 0;
        let call: RegExpExecArray | null;
        while ((call = RE_NAMED_META_CALL.exec(body.text)) !== null) {
          calls.push({
            kind: call[1],
            line: body.lineIndex,
            openIdx: call.index + call[0].length - 1,
          });
        }
      }

      const table = dbTable ?? tableFromIndex(ctx, modelName);
      if (!table) continue;
      for (const call of calls) {
        const kind = call.kind === 'UniqueConstraint'
          ? 'unique'
          : call.kind.endsWith('Index')
            ? 'index'
            : undefined;
        if (!kind) continue;
        const parts = readMetaCall(ctx, call.line, call.openIdx);
        if (!parts.name || !parts.fields || parts.fields.length === 0) continue;
        const expected = recommendedMetaName(kind, table, parts.fields);
        if (expected.name === parts.name.value) continue;
        out.push({
          code: 'DOL017',
          messageId: expected.truncated ? 'truncated' : 'mismatch',
          args: {
            kind: call.kind,
            name: parts.name.value,
            recommended: expected.name,
          },
          range: {
            line: parts.name.line,
            startCol: parts.name.startCol,
            endCol: parts.name.endCol,
          },
          applicability: 'suggestion',
          fixHint: `${parts.name.quote}${expected.name}${parts.name.quote}`,
        });
      }
    }
    return out;
  },
};

function tableFromIndex(ctx: RuleContext, modelName: string): string | undefined {
  const index = ctx.index;
  const filePath = ctx.document?.uri?.fsPath;
  if (!index || !filePath) return undefined;
  const want = filePath.replace(/\\/g, '/').toLowerCase();
  for (const app of index.apps) {
    for (const model of app.models) {
      const path = model.filePath.replace(/\\/g, '/').toLowerCase();
      if (path === want && model.name === modelName) {
        return `${app.name}_${modelName.toLowerCase()}`;
      }
    }
  }
  return undefined;
}

export const modelRules: Rule[] = [
  DOL011,
  DOL012,
  DOL013,
  DOL014,
  DOL015,
  DOL016,
  DOL017,
  ...denormalizeRules,
];
