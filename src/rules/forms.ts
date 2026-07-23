import { Finding, Rule, RuleContext } from './types';

/**
 * Forms and views rules.
 *
 * Codes DOL031..DOL040 are reserved for form/view/admin idioms.
 * Inspired by flake8-django DJ03 (locals-as-context) and DJ07
 * (fields='__all__'), rewritten from scratch against real templates.
 *
 * Public callers: src/rules/index.ts aggregates formsRules into ALL_RULES.
 */

const DOCS_BASE =
  'https://github.com/FROWNINGdev/django-orm-lens/blob/main/docs/rules';

/** `render(request, "template", locals())` and its close variants. */
const RE_RENDER_LOCALS =
  /\brender\s*\(\s*[A-Za-z_]\w*\s*,\s*[^,()]+,\s*locals\s*\(\s*\)\s*\)/g;

/** `fields = '__all__'` or `fields = "__all__"` (both quote styles). */
const RE_FIELDS_ALL =
  /\bfields\s*=\s*(?:'|")__all__(?:'|")/g;

function isCommentLine(text: string): boolean {
  return text.trimStart().startsWith('#');
}

/**
 * DOL031 — `render(request, template, locals())` leaks every local
 * variable into the template context, including debugging placeholders
 * and helpers. Explicit dicts document what the template needs.
 */
const DOL031: Rule = {
  meta: {
    code: 'DOL031',
    title: 'render() with locals() as context',
    category: 'style',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL031.md`,
    since: '0.8.0',
    messages: {
      default:
        'Passing locals() as the render context leaks every local variable into the template. Pass an explicit dict of only what the template needs.',
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_RENDER_LOCALS.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_RENDER_LOCALS.exec(text)) !== null) {
        out.push({
          code: 'DOL031',
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
 * DOL032 — `fields = '__all__'` inside a ModelForm or ModelAdmin Meta.
 * Every future model field auto-exposes without review. Common source
 * of unintended-write vulnerabilities.
 *
 * Applicability: unsafe — auto-expanding to a concrete list requires
 * the model definition, which is out of this file's line-oriented scope.
 * The finding surfaces a hint; the fix is a manual audit.
 */
const DOL032: Rule = {
  meta: {
    code: 'DOL032',
    title: "fields = '__all__' in Meta",
    category: 'correctness',
    defaultSeverity: 'warning',
    docsUrl: `${DOCS_BASE}/DOL032.md`,
    since: '0.8.0',
    messages: {
      default:
        "fields = '__all__' auto-exposes every model field — including future ones added later. Prefer an explicit list to prevent unintended writes and information disclosure.",
    },
  },
  check(ctx: RuleContext): Finding[] {
    const out: Finding[] = [];
    for (let i = 0; i < ctx.lineCount; i++) {
      const text = ctx.lineAt(i);
      if (isCommentLine(text)) continue;
      RE_FIELDS_ALL.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = RE_FIELDS_ALL.exec(text)) !== null) {
        out.push({
          code: 'DOL032',
          messageId: 'default',
          range: { line: i, startCol: m.index, endCol: m.index + m[0].length },
          applicability: 'unsafe',
        });
      }
    }
    return out;
  },
};

export const formsRules: Rule[] = [DOL031, DOL032];
