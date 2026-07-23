import * as cp from 'node:child_process';
import * as path from 'node:path';

/**
 * Thin git wrapper used by the schema-diff feature.
 *
 * All I/O funnels through `child_process.execFile` — no shell parsing,
 * no `-c` interpolation. The wrapper is stateless except for an LRU
 * cache keyed by BLOB SHA (not commit SHA): two commits that don't
 * touch the target file share the same parsed snapshot, and this cache
 * captures that.
 *
 * Callers:
 *   - src/extension.ts (djangoOrmLens.showDiff command)
 *   - src/diffWebview.ts (populates commit-picker dropdowns)
 *   - future CLI parity
 */

const MAX_BUFFER = 32 * 1024 * 1024; // 32 MiB — larger than any sane models.py

/** One entry in the git-log stream. */
export interface GitCommit {
  sha: string;
  /** Unix timestamp in seconds. */
  ct: number;
  subject: string;
}

/**
 * `git log --follow --format=%H%x09%ct%x09%s -- <path>` — one line per
 * commit that touched the file, most-recent first. Respects renames.
 */
export function gitLogFollow(
  cwd: string,
  filePath: string,
  limit = 200,
): Promise<GitCommit[]> {
  return execGit(
    cwd,
    [
      'log',
      `-n${Math.max(1, limit | 0)}`,
      '--follow',
      '--format=%H%x09%ct%x09%s',
      '--',
      relativizeIfInside(cwd, filePath),
    ],
  ).then((stdout) =>
    stdout
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        const [sha, ct, ...rest] = line.split('\t');
        return {
          sha,
          ct: Number(ct),
          subject: rest.join('\t'),
        };
      }),
  );
}

/**
 * Resolve `commitSha:path` to the blob SHA. `git ls-tree` gives a
 * stable key that a `git rev-parse commitSha:path` also produces,
 * but ls-tree is one round trip and cheaper.
 */
export async function blobShaFor(
  cwd: string,
  commitSha: string,
  filePath: string,
): Promise<string | undefined> {
  const rel = relativizeIfInside(cwd, filePath);
  const stdout = await execGit(cwd, ['ls-tree', commitSha, '--', rel]);
  // Format: "<mode> <type> <sha>\t<path>"
  const first = stdout.split(/\r?\n/).find(Boolean);
  if (!first) return undefined;
  const parts = first.split(/\s+/);
  if (parts.length < 3) return undefined;
  return parts[2];
}

/**
 * `git show <sha>:<path>` — return the file content at the given commit.
 * Callers should key their own cache by the returned string identity or
 * use `blobShaFor` first if they want to dedupe across commits.
 */
export function gitShowFile(
  cwd: string,
  commitSha: string,
  filePath: string,
): Promise<string> {
  const rel = relativizeIfInside(cwd, filePath);
  return execGit(cwd, ['show', `${commitSha}:${rel}`]);
}

/**
 * Simple LRU cache. Keyed by blob SHA; value is whatever the caller
 * decides to associate (in practice, the `ParsedModel[]` produced by
 * the parser). Kept generic here — the schema-diff pipeline instantiates
 * one per workspace.
 */
export class BlobCache<T> {
  private map = new Map<string, T>();
  constructor(private readonly max = 50) {}

  get(sha: string): T | undefined {
    const v = this.map.get(sha);
    if (v !== undefined) {
      // Touch — reinsert to bump recency.
      this.map.delete(sha);
      this.map.set(sha, v);
    }
    return v;
  }

  set(sha: string, v: T): void {
    if (this.map.has(sha)) this.map.delete(sha);
    this.map.set(sha, v);
    while (this.map.size > this.max) {
      const oldest = this.map.keys().next().value;
      if (oldest === undefined) break;
      this.map.delete(oldest);
    }
  }

  size(): number {
    return this.map.size;
  }
}

/* -----------------------------  internals  ---------------------------- */

function execGit(cwd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    cp.execFile(
      'git',
      args,
      { cwd, maxBuffer: MAX_BUFFER, windowsHide: true },
      (err, stdout, stderr) => {
        if (err) {
          const msg = stderr?.toString().trim() || err.message;
          reject(new Error(`git ${args.join(' ')} failed: ${msg}`));
          return;
        }
        resolve(stdout.toString());
      },
    );
  });
}

/** Return the shortest form of `filePath` relative to `cwd` when inside. */
function relativizeIfInside(cwd: string, filePath: string): string {
  const rel = path.relative(cwd, filePath);
  if (rel.startsWith('..')) return filePath;
  // Git wants forward slashes even on Windows.
  return rel.split(path.sep).join('/');
}
