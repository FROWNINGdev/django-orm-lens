/**
 * Edit distance between identifiers.
 *
 * Extracted from `schemaDiff` when a second caller appeared. Two independent
 * Levenshtein implementations in one codebase is how "the rename detector and
 * the typo detector disagree about what counts as close" becomes a bug nobody
 * can reproduce, so there is one and both import it.
 */

/**
 * Levenshtein distance between `a` and `b`.
 *
 * Single-row dynamic programming: O(a·b) time, O(b) space. Identifiers are
 * short enough that an early-exit cap would buy less than it costs in
 * complexity.
 */
export function levenshtein(a: string, b: string): number {
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  const dp = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] = a[i - 1] === b[j - 1] ? prev : 1 + Math.min(prev, dp[j - 1], dp[j]);
      prev = tmp;
    }
  }
  return dp[b.length];
}
