import { FixEdit, Fixer, FixerContext } from './types';

/**
 * Fixer registry.
 *
 * Kept separate from rule modules so that:
 *  1. one rule can have zero fixers (unsafe detections like DOL007)
 *  2. one rule can have multiple fixers (e.g. DOL013 could offer CASCADE
 *     and PROTECT variants; only CASCADE ships in v0.8)
 *  3. new fixers can be added later without touching rule code
 *  4. tests can exercise the rule detector alone with no fixer coupling.
 *
 * Fixers translate a `Finding` into `FixEdit[]`. They may return null to
 * decline the fix at runtime (e.g. edge case the fixer can't handle).
 *
 * Callers: `src/rules/index.ts` re-exports `ALL_FIXERS` and provides a
 * lookup helper; `src/codeActionProvider.ts` uses that lookup when
 * producing `vscode.CodeAction` for a given diagnostic.
 */

/** Build a one-shot line replacement edit. Convenience for regex-shape fixers. */
function replaceRange(
  finding: FixerContext['finding'],
  newText: string,
): FixEdit[] {
  return [
    {
      line: finding.range.line,
      startCol: finding.range.startCol,
      endCol: finding.range.endCol,
      newText,
    },
  ];
}

/** DOL001: `qs.count() > 0` → `qs.exists()`. */
const FIX_DOL001: Fixer = {
  code: 'DOL001',
  title: 'Rewrite to .exists()',
  build(ctx) {
    const qs = ctx.finding.fixHint;
    if (!qs) return null;
    return replaceRange(ctx.finding, `${qs}.exists()`);
  },
};

/** DOL002: `qs.count() == 0` → `not qs.exists()`. */
const FIX_DOL002: Fixer = {
  code: 'DOL002',
  title: 'Rewrite to not .exists()',
  build(ctx) {
    const qs = ctx.finding.fixHint;
    if (!qs) return null;
    return replaceRange(ctx.finding, `not ${qs}.exists()`);
  },
};

/** DOL003: `qs.first() is None` → `not qs.exists()`. */
const FIX_DOL003: Fixer = {
  code: 'DOL003',
  title: 'Rewrite to not .exists()',
  build(ctx) {
    const qs = ctx.finding.fixHint;
    if (!qs) return null;
    return replaceRange(ctx.finding, `not ${qs}.exists()`);
  },
};

/** DOL004: `qs.first() is not None` → `qs.exists()`. */
const FIX_DOL004: Fixer = {
  code: 'DOL004',
  title: 'Rewrite to .exists()',
  build(ctx) {
    const qs = ctx.finding.fixHint;
    if (!qs) return null;
    return replaceRange(ctx.finding, `${qs}.exists()`);
  },
};

/** DOL006: `for x in list(qs):` → `for x in qs:` by dropping the list() call. */
const FIX_DOL006: Fixer = {
  code: 'DOL006',
  title: 'Drop list() and iterate directly',
  build(ctx) {
    const qs = ctx.finding.fixHint;
    if (!qs) return null;
    return replaceRange(ctx.finding, qs);
  },
};

/**
 * DOL011: replace `null=True` with `blank=True` inside the flagged field call.
 * The finding range covers `models.CharField(...)`; we do a surgical replace
 * of `null=True` within that window.
 */
const FIX_DOL011: Fixer = {
  code: 'DOL011',
  title: 'Replace null=True with blank=True',
  build(ctx) {
    const line = ctx.document.lineAt(ctx.finding.range.line).text;
    const slice = line.slice(
      ctx.finding.range.startCol,
      ctx.finding.range.endCol,
    );
    const replaced = slice.replace(/\bnull\s*=\s*True\b/, 'blank=True');
    if (replaced === slice) return null;
    return replaceRange(ctx.finding, replaced);
  },
};

/**
 * DOL013: insert `on_delete=models.CASCADE` as the first kwarg of the
 * flagged `ForeignKey(...)` call. If there is only positional arg (the
 * to= target), append with a leading comma.
 */
const FIX_DOL013: Fixer = {
  code: 'DOL013',
  title: 'Add on_delete=models.CASCADE (edit to your policy)',
  build(ctx) {
    const line = ctx.document.lineAt(ctx.finding.range.line).text;
    const slice = line.slice(
      ctx.finding.range.startCol,
      ctx.finding.range.endCol,
    );
    // slice looks like `models.ForeignKey(SomeModel)` or `ForeignKey("app.Foo")`
    // Insert `on_delete=models.CASCADE` before the closing `)`.
    const idx = slice.lastIndexOf(')');
    if (idx < 0) return null;
    const before = slice.slice(0, idx);
    const trimmed = before.replace(/\s+$/, '');
    const isEmpty = /\(\s*$/.test(trimmed);
    const sep = isEmpty ? '' : ', ';
    const newSlice = `${trimmed}${sep}on_delete=models.CASCADE)`;
    return replaceRange(ctx.finding, newSlice);
  },
};

/** DOL014: insert `max_length=255` template kwarg into CharField call. */
const FIX_DOL014: Fixer = {
  code: 'DOL014',
  title: 'Add max_length=255 (edit as needed)',
  build(ctx) {
    const line = ctx.document.lineAt(ctx.finding.range.line).text;
    const slice = line.slice(
      ctx.finding.range.startCol,
      ctx.finding.range.endCol,
    );
    const idx = slice.lastIndexOf(')');
    if (idx < 0) return null;
    const before = slice.slice(0, idx);
    const trimmed = before.replace(/\s+$/, '');
    const isEmpty = /\(\s*$/.test(trimmed);
    const sep = isEmpty ? '' : ', ';
    const newSlice = `${trimmed}${sep}max_length=255)`;
    return replaceRange(ctx.finding, newSlice);
  },
};

/** DOL015: strip `, max_length=N` (or leading) from TextField call. */
const FIX_DOL015: Fixer = {
  code: 'DOL015',
  title: 'Remove max_length from TextField',
  build(ctx) {
    const line = ctx.document.lineAt(ctx.finding.range.line).text;
    const slice = line.slice(
      ctx.finding.range.startCol,
      ctx.finding.range.endCol,
    );
    // Remove `, max_length=X` or `max_length=X, ` or bare `max_length=X`.
    const patterns = [
      /,\s*max_length\s*=\s*[^,)\s]+/,
      /max_length\s*=\s*[^,)\s]+\s*,\s*/,
      /max_length\s*=\s*[^,)\s]+/,
    ];
    for (const re of patterns) {
      if (re.test(slice)) {
        return replaceRange(ctx.finding, slice.replace(re, ''));
      }
    }
    return null;
  },
};

/**
 * DOL021: replace `datetime.now()` with `timezone.now()`. The user is
 * responsible for adding `from django.utils import timezone` if missing.
 */
const FIX_DOL021: Fixer = {
  code: 'DOL021',
  title: 'Replace with timezone.now()',
  build(ctx) {
    return replaceRange(ctx.finding, 'timezone.now()');
  },
};

/** DOL022: same substitution as DOL021 for utcnow(). */
const FIX_DOL022: Fixer = {
  code: 'DOL022',
  title: 'Replace with timezone.now()',
  build(ctx) {
    return replaceRange(ctx.finding, 'timezone.now()');
  },
};

/**
 * The complete v0.8 fixer table. Rules without an entry here surface as
 * diagnostics with no lightbulb (correct behaviour for unsafe/hint-only
 * checks like DOL007 N+1 and DOL012 __str__ generation).
 */
export const ALL_FIXERS: Fixer[] = [
  FIX_DOL001,
  FIX_DOL002,
  FIX_DOL003,
  FIX_DOL004,
  FIX_DOL006,
  FIX_DOL011,
  FIX_DOL013,
  FIX_DOL014,
  FIX_DOL015,
  FIX_DOL021,
  FIX_DOL022,
];

/**
 * Lookup helper for the CodeActionProvider. Returns all fixers whose
 * `code` matches, optionally filtered by `fixHint`. Callers surface each
 * returned fixer as a separate lightbulb option.
 */
export function findFixersForCode(code: string, fixHint?: string): Fixer[] {
  return ALL_FIXERS.filter(
    (f) => f.code === code && (f.fixHint === undefined || f.fixHint === fixHint),
  );
}
