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
  'https://github.com/FROWNINGdev/django-orm-lens/blob/main/docs/rules';

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

export const modelRules: Rule[] = [DOL011, DOL012, DOL013, DOL014, DOL015];
