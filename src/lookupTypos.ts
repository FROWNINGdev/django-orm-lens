/**
 * Misspelled field names inside `Post.objects.filter(...)`.
 *
 * Point 4 of the original #3 sketch, held back until now on purpose. The bar
 * is much higher than for completion: a completion that stays silent when
 * unsure costs the user nothing, while an error squiggle that is wrong when
 * unsure puts a red underline on correct code and teaches people to ignore the
 * extension. Three sources of false positives had to close first — reverse
 * accessors (v0.15.0), inherited fields (v0.16.0) and cross-file bases
 * (v0.17.0) — because each of them is a legal lookup absent from
 * `ParsedModel.fields`.
 *
 * Two properties keep precision up, and both are structural rather than tuned:
 *
 * 1. **It can only fire on something completion would not have offered.** The
 *    check asks `completionsAt` for the labels valid at that point and reports
 *    only names missing from that list. Anything completion learns to resolve,
 *    this stops flagging — automatically, and without a second copy of the
 *    resolution logic to keep in step.
 *
 * 2. **It only fires when there is a near match to name.** "I do not recognise
 *    this" is a low-precision claim: annotations, custom lookups and unparsed
 *    mixins all land there. "This looks like a misspelling of that" is a
 *    high-precision one, and it arrives with something actionable to suggest.
 *    A name close to nothing is left alone.
 */

import { completionsAt } from './ormCompletions';
import { levenshtein } from './textDistance';
import type { WorkspaceIndex } from './types';

export interface LookupTypo {
  /** The segment as written. */
  typed: string;
  /** The name it is most likely meant to be. */
  suggestion: string;
  /** Zero-based column of `typed` within the line. */
  startCol: number;
  /** Zero-based column just past `typed`. */
  endCol: number;
}

/**
 * How far off a name may be and still be called a misspelling of `target`.
 *
 * Short names get no slack: at four characters, distance 2 reaches a large
 * share of the identifiers in any schema and "did you mean" stops meaning
 * anything.
 */
function allowedDistance(target: string): number {
  return target.length <= 4 ? 1 : 2;
}

/**
 * The best near match for `typed` among `candidates`, or `null`.
 *
 * Requiring the first character to agree does real work: it is the letter
 * people get right even when they fumble the rest, and without it short names
 * pair off with each other across an entire model.
 */
export function nearestName(typed: string, candidates: readonly string[]): string | null {
  const limit = allowedDistance(typed);
  let best: string | null = null;
  let bestDist = limit + 1;
  for (const candidate of candidates) {
    if (candidate === typed) return null;
    if (candidate[0] !== typed[0]) continue;
    const d = levenshtein(typed, candidate);
    if (d < bestDist) {
      bestDist = d;
      best = candidate;
    }
  }
  return bestDist <= limit ? best : null;
}

/** Manager calls whose keyword arguments name fields. */
const CALL_RE =
  /\.(filter|exclude|get|get_or_create|update_or_create|order_by|values|values_list|only|defer)\s*\(/g;

/** `title__icontains=` — a keyword argument naming a lookup path. */
const KWARG_RE = /(^|[,\s])([A-Za-z_]\w*)\s*=/g;

/** Index of the `)` closing the `(` at `open`, or -1. */
function matchingParen(line: string, open: number): number {
  let depth = 0;
  let quote: string | null = null;
  for (let i = open; i < line.length; i++) {
    const ch = line[i];
    if (quote) {
      if (ch === quote && line[i - 1] !== '\\') quote = null;
      continue;
    }
    if (ch === "'" || ch === '"') quote = ch;
    else if (ch === '(') depth++;
    else if (ch === ')') {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** Walk one `a__b__c` path, reporting the first segment that is off. */
function checkPath(
  line: string,
  path: string,
  pathStart: number,
  openParen: number,
  index: WorkspaceIndex,
  out: LookupTypo[]
): void {
  let offset = pathStart;
  let prefix = '';
  for (const segment of path.split('__')) {
    const valid = completionsAt(line.slice(0, openParen + 1) + prefix, index).map((s) =>
      s.label.slice(prefix.length)
    );
    // Nothing resolved here, so there is nothing to be confident about.
    if (valid.length === 0) return;
    if (!valid.includes(segment)) {
      const suggestion = nearestName(segment, valid);
      if (suggestion) {
        out.push({
          typed: segment,
          suggestion,
          startCol: offset,
          endCol: offset + segment.length,
        });
      }
      // Suggestion or not, everything after this hangs off a segment that did
      // not resolve, so nothing further down the path can be judged.
      return;
    }
    offset += segment.length + 2; // segment + `__`
    prefix += segment + '__';
  }
}

/**
 * Find misspelled lookup segments on one line.
 *
 * :param line: the whole source line.
 * :param index: the parsed workspace.
 * :returns: one entry per segment that is both unrecognised and close to a
 *   name that is recognised. Empty whenever anything is uncertain.
 */
export function lookupTypos(line: string, index: WorkspaceIndex): LookupTypo[] {
  // An annotation introduces a name that is valid downstream and exists
  // nowhere in the schema, so a line carrying one is not a line to judge.
  if (/\.(annotate|alias|extra)\s*\(/.test(line)) return [];
  const out: LookupTypo[] = [];
  CALL_RE.lastIndex = 0;
  for (let call = CALL_RE.exec(line); call; call = CALL_RE.exec(line)) {
    const openParen = call.index + call[0].length - 1;
    // The call has to be one completion itself resolves. Asking it with the
    // prefix up to the paren reuses every part of model resolution — literal
    // receiver, inherited fields, reverse accessors — instead of keeping a
    // weaker copy here that would drift.
    if (completionsAt(line.slice(0, openParen + 1), index).length === 0) continue;

    const close = matchingParen(line, openParen);
    if (close < 0) continue;
    const args = line.slice(openParen + 1, close);
    // A nested call among the arguments means `Q(...)`, `F(...)` or a
    // subquery, where a bare name need not be a field at all.
    if (args.includes('(')) continue;

    KWARG_RE.lastIndex = 0;
    for (let kw = KWARG_RE.exec(args); kw; kw = KWARG_RE.exec(args)) {
      checkPath(
        line,
        kw[2],
        openParen + 1 + kw.index + kw[1].length,
        openParen,
        index,
        out
      );
    }
  }
  return out;
}
