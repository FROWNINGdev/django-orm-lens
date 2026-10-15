import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { collectDefs, resolveAndFilter } from './modelParse';
import { ParsedApp, ParsedField, ParsedModel, RelationKind, WorkspaceIndex } from './types';

/**
 * App directory for a model file.
 *
 * `models.py` belongs to the directory that contains it (`shop/models.py` →
 * shop). Any other module under a `models/` package belongs to that package's
 * parent, so `shop/models/builders/flow.py` is still the shop app — not
 * `builders`. `root` is the workspace folder so a directory named `models`
 * above the project is not treated as a Django models package.
 * Mirrors `_app_dir_for` in cli/orm_synapse/parser.py.
 */
export function appDirFor(fsPath: string, root?: string): { dir: string; name: string } {
  const directory = path.dirname(fsPath);
  if (path.basename(fsPath) === 'models.py') {
    return { dir: directory, name: path.basename(directory) };
  }
  if (root) {
    const rel = path.relative(root, directory);
    const outside = rel.startsWith('..') || path.isAbsolute(rel);
    if (!outside) {
      const parts = rel === '' ? [] : rel.split(path.sep);
      const idx = parts.lastIndexOf('models');
      if (idx !== -1) {
        const appDir = idx === 0 ? root : path.join(root, ...parts.slice(0, idx));
        return { dir: appDir, name: path.basename(appDir) };
      }
    }
  }
  if (path.basename(directory) === 'models') {
    const grand = path.dirname(directory);
    return { dir: grand, name: path.basename(grand) };
  }
  return { dir: directory, name: path.basename(directory) };
}

// Convert a "**/name/**" style glob prefix/segment into a simple test.
// We only need enough coverage for the default exclude patterns
// (**/migrations/**, **/venv/**, **/node_modules/**, etc.) — anything more
// exotic falls back to matching the raw pattern as a substring.
export function excludeMatcher(patterns: string[]): (relPosix: string) => boolean {
  const segments = patterns
    .map((p) => {
      const m = p.match(/^\*\*\/([^/*]+)\/\*\*$/);
      return m ? m[1] : null;
    })
    .filter((s): s is string => !!s);
  const raw = patterns.filter((p) => !/^\*\*\/([^/*]+)\/\*\*$/.test(p));
  // Wildcard patterns match like Python's fnmatch, which the CLI applies to
  // the same setting, so `**/*_test.py` excludes the same files on both sides.
  const globs = raw.filter((p) => /[*?[]/.test(p)).map(fnmatchRegex);
  const plain = raw.filter((p) => !/[*?[]/.test(p));
  return (rel: string) => {
    const parts = rel.split('/');
    for (const seg of segments) if (parts.includes(seg)) return true;
    for (const g of globs) if (g.test(rel)) return true;
    for (const r of plain) if (rel.includes(r)) return true;
    return false;
  };
}

/** Python `fnmatch.translate`: `*` spans `/`, `[!x]` negates a class. */
function fnmatchRegex(pattern: string): RegExp {
  let out = '';
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === '*') out += '.*';
    else if (c === '?') out += '.';
    else if (c === '[') {
      const end = pattern.indexOf(']', i + 2);
      if (end === -1) {
        out += '\\[';
        continue;
      }
      let body = pattern.slice(i + 1, end).replace(/\\/g, '\\\\');
      if (body.startsWith('!')) body = '^' + body.slice(1);
      else if (body.startsWith('^')) body = '\\' + body;
      out += `[${body}]`;
      i = end;
    } else out += c.replace(/[.+^${}()|\\\]]/g, '\\$&');
  }
  return new RegExp(`^${out}$`, 's');
}

/**
 * Files that declare models but are not named `models.py`.
 *
 * Pluggable Django frameworks keep their abstract bases in
 * `abstract_models.py` and leave `models.py` holding only the concrete
 * subclasses — django-oscar does this in all 14 of its apps. Without reading
 * these, oscar's models parse as classes with no fields between them: found,
 * but empty, which reads as a schema that lost its columns. Mirrors
 * MODEL_SOURCE_FILES in cli/orm_synapse/parser.py.
 */
const MODEL_SOURCE_FILES = new Set(['models.py', 'abstract_models.py']);

/**
 * Workspace-relative path of a Django model module.
 *
 * Matches `models.py`, `abstract_models.py`, and any other `.py` under a
 * `models/` package, including nested modules (`models/builders/flow.py`)
 * and package `__init__.py` files, which can define models themselves
 * (`models/lead/__init__.py`). Mirrors `_is_model_source` in
 * cli/orm_synapse/parser.py.
 */
export function isModelSourceRelPath(relPosix: string): boolean {
  const norm = relPosix.replace(/\\/g, '/').replace(/^\.\//, '');
  const name = norm.split('/').pop() ?? '';
  if (!name.endsWith('.py')) return false;
  if (MODEL_SOURCE_FILES.has(name)) return true;
  return norm.split('/').slice(0, -1).includes('models');
}

function workspaceRootFor(fsPath: string, roots: string[]): string | undefined {
  const resolved = path.resolve(fsPath);
  const matches = roots
    .map((r) => path.resolve(r))
    .filter((r) => resolved === r || resolved.startsWith(r + path.sep));
  matches.sort((a, b) => b.length - a.length);
  return matches[0];
}

// Walk a directory synchronously collecting model modules: models.py,
// abstract_models.py, and every .py under a models/ package (nested
// subpackages included). Used as a fallback when vscode.workspace.findFiles
// returns no results (workspace file index cold, or platform-specific glob
// quirks that silently drop root-level models.py).
export function walkForModels(root: string, isExcluded: (rel: string) => boolean): string[] {
  const results: string[] = [];
  const stack: string[] = [root];
  while (stack.length) {
    const dir = stack.pop()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(root, full).split(path.sep).join('/');
      if (isExcluded(rel)) continue;
      if (entry.isDirectory()) {
        if (entry.name.startsWith('.')) continue;
        stack.push(full);
        continue;
      }
      if (!entry.isFile()) continue;
      if (isModelSourceRelPath(rel)) results.push(full);
    }
  }
  return results;
}

const FROM_IMPORT_RE =
  /^[ \t]*from[ \t]+(\.+[\w.]*|[\w.]+)[ \t]+import[ \t]+(?:\(([^)]*)\)|([^\n]*))/gm;
const IMPORT_RE = /^[ \t]*import[ \t]+([^\n]+)/gm;

// How many re-exports a base may sit behind (`core/db/__init__.py` doing
// `from .bases import SoftDeletable` is one). Bounds a malformed import cycle
// rather than any real project.
const MAX_IMPORT_HOPS = 5;

type ImportTarget = { module: string; name: string | null };

/**
 * Map each name a module binds by import to the module (and name) it came
 * from. Mirrors `_parse_imports` in cli/orm_synapse/parser.py.
 */
export function parseImports(content: string): Map<string, ImportTarget> {
  const out = new Map<string, ImportTarget>();
  const put = (alias: string, t: ImportTarget) => {
    if (!out.has(alias)) out.set(alias, t);
  };
  for (const m of content.matchAll(FROM_IMPORT_RE)) {
    const names = m[2] ?? m[3] ?? '';
    for (const raw of names.split(',')) {
      const item = raw.split('#')[0].trim().replace(/\\$/, '').trim();
      const parts = item.split(/\s+/).filter(Boolean);
      if (!parts.length || parts[0] === '*') continue;
      const alias = parts.length === 3 && parts[1] === 'as' ? parts[2] : parts[0];
      put(alias, { module: m[1], name: parts[0] });
    }
  }
  for (const m of content.matchAll(IMPORT_RE)) {
    for (const raw of m[1].split('#')[0].split(',')) {
      const parts = raw.trim().split(/\s+/).filter(Boolean);
      if (!parts.length) continue;
      if (parts.length === 3 && parts[1] === 'as') {
        put(parts[2], { module: parts[0], name: null });
      } else {
        const head = parts[0].split('.')[0];
        put(head, { module: head, name: null });
      }
    }
  }
  return out;
}

function joinModule(module: string, name: string): string {
  return module.endsWith('.') ? module + name : `${module}.${name}`;
}

function isInside(dir: string, root: string): boolean {
  const rel = path.relative(root, dir);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/** Candidate files for `module` imported from `fromFile`. Mirrors `_module_files`. */
function moduleFiles(module: string, fromFile: string, root: string): string[] {
  const dots = module.length - module.replace(/^\.+/, '').length;
  const parts = module.slice(dots).split('.').filter(Boolean);
  const here = path.dirname(path.resolve(fromFile));
  const bases: string[] = [];
  if (dots) {
    let b = here;
    for (let k = 1; k < dots; k++) b = path.dirname(b);
    bases.push(b);
  } else {
    for (let b = here; ; b = path.dirname(b)) {
      bases.push(b);
      if (path.dirname(b) === b) break;
    }
  }
  const out: string[] = [];
  for (const b of bases) {
    if (!isInside(b, root)) break;
    const target = path.join(b, ...parts);
    if (parts.length) out.push(target + '.py');
    out.push(path.join(target, '__init__.py'));
  }
  return out;
}

/**
 * Definitions of base classes that live outside the scanned model files.
 *
 * The scan reads `models.py`-style files only, so `class Person(MyBase)` with
 * `MyBase` in `core/base.py` had nothing to resolve against and `Person`
 * vanished (issue #135). This follows the subclass's own imports to the file
 * defining each unknown base — through re-exports and relative imports — and
 * returns those classes so `resolveAndFilter` sees the whole chain. Only
 * classes something inherits from are pulled. Mirrors `_pull_imported_bases`
 * in cli/orm_synapse/parser.py.
 */
export function pullImportedBases(
  allDefs: ParsedModel[],
  roots: string[],
  isExcluded: (relPosix: string) => boolean = () => false
): ParsedModel[] {
  const resolvedRoots = roots.map((r) => path.resolve(r));
  const rootOf = (file: string) =>
    resolvedRoots
      .filter((r) => isInside(path.dirname(file), r))
      .sort((a, b) => b.length - a.length)[0];
  type Entry = { defs: Map<string, ParsedModel>; imports: Map<string, ImportTarget> };
  const loaded = new Map<string, Entry | null>();

  const load = (file: string, root: string): Entry | null => {
    if (loaded.has(file)) return loaded.get(file)!;
    loaded.set(file, null);
    const rel = path.relative(root, file).split(path.sep).join('/');
    if (rel.startsWith('..') || isExcluded(rel)) return null;
    let content: string;
    try {
      // A directory or a missing file throws here (EISDIR / ENOENT).
      content = fs.readFileSync(file, 'utf-8');
    } catch {
      return null;
    }
    const defs = new Map<string, ParsedModel>();
    try {
      for (const d of collectDefs(file, content)) if (!defs.has(d.name)) defs.set(d.name, d);
    } catch {
      return null;
    }
    const entry = { defs, imports: parseImports(content) };
    loaded.set(file, entry);
    return entry;
  };

  const find = (file: string, base: string, root: string, hops: number): ParsedModel | null => {
    const entry = load(file, root);
    if (!entry || hops > MAX_IMPORT_HOPS) return null;
    const qual = base.split('.');
    let name = qual.pop()!;
    let module: string;
    if (!qual.length) {
      const own = entry.defs.get(name);
      if (own) return own;
      const target = entry.imports.get(name);
      if (!target || target.name === null) return null;
      module = target.module;
      name = target.name;
    } else {
      const head = entry.imports.get(qual[0]);
      if (!head) module = qual[0];
      else if (head.name === null) module = head.module;
      else module = joinModule(head.module, head.name);
      for (const part of qual.slice(1)) module = joinModule(module, part);
    }
    for (const candidate of moduleFiles(module, file, root)) {
      const found = find(candidate, name, root, hops + 1);
      if (found) return found;
    }
    return null;
  };

  const known = new Set(allDefs.map((m) => m.name));
  const queue: Array<[string, string]> = [];
  for (const m of allDefs) for (const b of m.baseClasses) queue.push([m.filePath, b]);
  const asked = new Set<string>();
  const pulled: ParsedModel[] = [];
  while (queue.length) {
    const [filePath, base] = queue.pop()!;
    const key = `${filePath}\0${base}`;
    if (known.has(base.split('.').pop() ?? '') || asked.has(key)) continue;
    asked.add(key);
    const file = path.resolve(filePath);
    const root = rootOf(file);
    if (!root) continue;
    const found = find(file, base, root, 0);
    if (!found || known.has(found.name)) continue;
    known.add(found.name);
    pulled.push(found);
    for (const b of found.baseClasses) queue.push([found.filePath, b]);
  }
  return pulled;
}

export async function scanWorkspace(
  excludeGlobs: string[]
): Promise<WorkspaceIndex> {
  const excludePattern = `{${excludeGlobs.join(',')}}`;
  const folders = vscode.workspace.workspaceFolders ?? [];

  // Primary path: ask VS Code's file index. Fast when it's warm, honours
  // user files.exclude, works for multi-root workspaces.
  const results = await Promise.all(
    folders.flatMap((folder) => [
      vscode.workspace.findFiles(
        new vscode.RelativePattern(folder, '**/{models,abstract_models}.py'),
        excludePattern
      ),
      vscode.workspace.findFiles(
        new vscode.RelativePattern(folder, '{models,abstract_models}.py'),
        excludePattern
      ),
      vscode.workspace.findFiles(
        new vscode.RelativePattern(folder, '**/models/*.py'),
        excludePattern
      ),
      // Nested modules under models/, any depth: models/builders/flow.py
      // and models/requests/components/offer.py. `**/models/*.py` is only
      // one level and misses these.
      vscode.workspace.findFiles(
        new vscode.RelativePattern(folder, '**/models/**/*.py'),
        excludePattern
      ),
    ])
  );
  const seen = new Set<string>();
  const uris: vscode.Uri[] = [];
  for (const batch of results) {
    for (const u of batch) {
      if (seen.has(u.fsPath)) continue;
      seen.add(u.fsPath);
      uris.push(u);
    }
  }

  // Fallback: walk each workspace folder directly. Triggered when the file
  // index is empty (cold start via `onStartupFinished`, or the `**/models.py`
  // glob silently missed root-level files on this platform). We only pay the
  // cost when the primary path found nothing, so this is a no-op in the
  // common warm-cache case.
  if (uris.length === 0 && folders.length > 0) {
    const isExcluded = excludeMatcher(excludeGlobs);
    for (const folder of folders) {
      if (folder.uri.scheme !== 'file') continue;
      const found = walkForModels(folder.uri.fsPath, isExcluded);
      for (const p of found) {
        if (seen.has(p)) continue;
        seen.add(p);
        uris.push(vscode.Uri.file(p));
      }
    }
  }
  const appMap = new Map<string, ParsedApp>();

  // Two passes over the workspace, not one per file. Resolving each file in
  // isolation cannot see a base declared in another module, so a project with
  // its abstract bases in `core/models.py` — the usual place to put them —
  // lost every model that inherits from one. Collect every definition first,
  // resolve the union once, then group what survives by app.
  const allDefs: ParsedModel[] = [];
  for (const uri of uris) {
    let content: string;
    try {
      const bytes = await vscode.workspace.fs.readFile(uri);
      content = Buffer.from(bytes).toString('utf-8');
    } catch (err) {
      continue;
    }
    try {
      allDefs.push(...collectDefs(uri.fsPath, content));
    } catch (err) {
      console.error(`orm-synapse: parser error in ${uri.fsPath}`, err);
    }
  }
  allDefs.push(
    ...pullImportedBases(
      allDefs,
      folders.filter((f) => f.uri.scheme === 'file').map((f) => f.uri.fsPath),
      excludeMatcher(excludeGlobs)
    )
  );

  const fileRoots = folders.filter((f) => f.uri.scheme === 'file').map((f) => f.uri.fsPath);

  for (const model of resolveAndFilter(allDefs)) {
    const { dir: appDir, name: appName } = appDirFor(
      model.filePath,
      workspaceRootFor(model.filePath, fileRoots)
    );
    let app = appMap.get(appDir);
    if (!app) {
      app = { name: appName, path: appDir, models: [] };
      appMap.set(appDir, app);
    }
    app.models.push(model);
  }

  const apps = Array.from(appMap.values()).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  return { apps, scannedAt: Date.now() };
}
