import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import {
  ParsedApp,
  ParsedField,
  ParsedModel,
  RelationKind,
  WorkspaceIndex,
} from './types';

const RELATION_TYPES: RelationKind[] = [
  'ForeignKey',
  'ManyToManyField',
  'OneToOneField',
];

// django-mptt's Tree* fields are thin subclasses of Django's own relation
// fields — same `to`, same `on_delete`, same `related_name`. Mapping the name
// to its Django counterpart is the whole fix: every extractor below keeps
// working unchanged. Mirrors TREE_FIELD_ALIASES in cli/django_orm_lens/parser.py;
// the two must stay in step or the sidebar and the CLI disagree about a schema.
const TREE_FIELD_ALIASES: Record<string, RelationKind> = {
  TreeForeignKey: 'ForeignKey',
  TreeOneToOneField: 'OneToOneField',
  TreeManyToManyField: 'ManyToManyField',
};

const USER_BASE_MARKERS = new Set(['AbstractUser', 'AbstractBaseUser']);

/**
 * Return the workspace's Django User model, or ``undefined``.
 *
 * Heuristic mirrors the Python CLI's ``models.find_user_model``:
 * (1) first model whose bases include ``AbstractUser`` / ``AbstractBaseUser``,
 * (2) fall back to any model named ``User``, (3) otherwise ``undefined``.
 * Used to resolve ``settings.AUTH_USER_MODEL`` references so hover, ER
 * diagram, and inbound-relation lookups all land on the same target.
 */
export function findUserModel(index: WorkspaceIndex): ParsedModel | undefined {
  for (const app of index.apps) {
    for (const m of app.models) {
      for (const b of m.baseClasses) {
        const tail = b.split('.').pop() ?? '';
        if (USER_BASE_MARKERS.has(tail)) return m;
      }
    }
  }
  for (const app of index.apps) {
    for (const m of app.models) {
      if (m.name === 'User') return m;
    }
  }
  return undefined;
}

/**
 * Substitute ``settings.AUTH_USER_MODEL`` / bare ``AUTH_USER_MODEL`` with
 * the workspace's actual User model name; otherwise return the last dotted
 * segment (``"orders.Order"`` → ``"Order"``). Passes through ``undefined``.
 */
export function resolveRelatedTail(
  related: string | undefined,
  userModelName: string | undefined
): string | undefined {
  if (!related) return related;
  const tail = related.split('.').pop() ?? '';
  if (tail === 'AUTH_USER_MODEL' && userModelName) return userModelName;
  return tail;
}

// `(?:\s*\[[^\]]*\])?` — optional PEP-695 generic type parameter list
// introduced in Python 3.12, e.g. `class Container[T](models.Model):`.
// Only handles a single-line, non-nested bracket group.
/**
 * Bases that mark a class as a Django model on their name alone.
 *
 * This is only the seed. `resolveAndFilter` grows the set transitively, so a
 * project-local base under any other name — `TimeStamped`, `BaseModel`,
 * `Auditable` — still makes its subclasses models once the base itself is
 * recognised. Mirrors `_looks_like_model` in cli/django_orm_lens/parser.py.
 */
const NON_MODEL_TAIL =
  /^(ModelAdmin|ModelForm|ModelSerializer|ModelChoiceField|ModelMultipleChoiceField|Serializer|Form|Admin|View|ViewSet|Manager|QuerySet|Config|AppConfig|Response|Handler|Middleware|Backend|Command)$/;

export function looksLikeModel(baseClasses: string[]): boolean {
  for (const b of baseClasses) {
    const tail = b.split('.').pop() ?? '';
    if (NON_MODEL_TAIL.test(tail)) return false;
    if (
      /models\.Model$/.test(b) ||
      /^(Model|AbstractModel|AbstractBaseModel|TimeStampedModel|PolymorphicModel|MPTTModel)$/.test(tail) ||
      /^Abstract[A-Z]/.test(tail) ||
      /Mixin$/.test(tail)
    ) {
      return true;
    }
  }
  return false;
}

const CLASS_RE =
  /^class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*\(([^)]*)\)\s*:/;
const CLASS_START_RE =
  /^class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^\]]*\])?\s*\(/;

function readMultilineClass(
  lines: string[],
  startIdx: number
): { match: RegExpMatchArray; endIdx: number } | null {
  let buffer = lines[startIdx];
  let depth = 0;
  let sawOpen = false;
  for (let i = startIdx; i < lines.length; i++) {
    const src = i === startIdx ? lines[i] : lines[i].trimStart();
    for (const ch of src) {
      if (ch === '(') {
        depth++;
        sawOpen = true;
      } else if (ch === ')') depth--;
    }
    if (i > startIdx) buffer += ' ' + src;
    if (sawOpen && depth === 0) {
      const m = buffer.match(CLASS_RE);
      if (m) return { match: m, endIdx: i };
      break;
    }
  }
  return null;
}

function detectClassIndent(lines: string[], classLineIdx: number): number {
  for (let i = classLineIdx + 1; i < Math.min(classLineIdx + 30, lines.length); i++) {
    const m = lines[i].match(/^([\t ]+)\S/);
    if (m) return m[1].length;
  }
  return 4;
}

const BARE_FIELD_TYPES = [
  'CharField', 'TextField', 'SlugField', 'EmailField', 'URLField', 'UUIDField',
  'IntegerField', 'BigIntegerField', 'SmallIntegerField',
  'PositiveIntegerField', 'PositiveSmallIntegerField', 'PositiveBigIntegerField',
  'FloatField', 'DecimalField',
  'BooleanField', 'NullBooleanField',
  'DateTimeField', 'DateField', 'TimeField', 'DurationField',
  'JSONField', 'BinaryField',
  'FileField', 'ImageField', 'FilePathField',
  'GenericIPAddressField',
  'AutoField', 'BigAutoField', 'SmallAutoField',
  'ForeignKey', 'OneToOneField', 'ManyToManyField',
  'TaggableManager',
  'TreeForeignKey', 'TreeOneToOneField', 'TreeManyToManyField',
].join('|');

function buildBodyRegexes(indent: number) {
  const w = `\\s{${indent}}`;
  const w2 = `\\s{${indent * 2}}`;
  // `(?:\\s*:[^=]+)?` — optional PEP-526 type annotation between the field
  // name and `=`, e.g. `jti: CharField[str] = models.CharField(...)`.
  // `[^=]+` is safe because `=` never appears inside a type expression
  // (subscripts, unions, dotted refs, and generics all use other punctuation).
  const ann = `(?:\\s*:[^=]+)?`;
  // `(?:[A-Za-z_][A-Za-z0-9_]*\\.)?` — optional single-identifier prefix on
  // the RHS. Covers aliased models module (`m.CharField`) and third-party
  // field packages (`jsonfield.JSONField`). Safe against false positives
  // because the type name is still restricted to the BARE_FIELD_TYPES
  // whitelist.
  const prefixOpt = `(?:[A-Za-z_][A-Za-z0-9_]*\\.)?`;
  return {
    FIELD_RE: new RegExp(
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)${ann}\\s*=\\s*models\\.([A-Za-z_][A-Za-z0-9_]*)\\s*\\(`
    ),
    BARE_FIELD_RE: new RegExp(
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)${ann}\\s*=\\s*${prefixOpt}(${BARE_FIELD_TYPES})\\s*\\(`
    ),
    META_START_RE: new RegExp(`^${w}class\\s+Meta\\s*(?:\\([^)]*\\))?\\s*:`),
    META_ITEM_RE: new RegExp(
      `^${w2}([a-zA-Z_][a-zA-Z0-9_]*)${ann}\\s*=\\s*(.+?)\\s*(#.*)?$`
    ),
    META_BODY_RE: new RegExp(`^\\s{${indent * 2},}`),
  };
}

function extractRelated(argsBlock: string): string | undefined {
  const stripped = argsBlock.trim();
  // (1) Look for an explicit `to=<value>` anywhere in the arg list so that
  // reordered kwargs like `ForeignKey(on_delete=CASCADE, to='User')` still
  // resolve. The legacy positional-first regex read `on_delete` as the target.
  const toKwarg = stripped.match(
    /\bto\s*=\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*))/
  );
  if (toKwarg) {
    const raw = toKwarg[1] || toKwarg[2] || toKwarg[3];
    if (raw) {
      if (raw === 'self') return 'self';
      return raw.replace(/^['"]|['"]$/g, '');
    }
  }
  // (2) Fallback: first positional arg. Negative lookahead `(?!\s*=)` on the
  // bare-name branch rejects kwargs — otherwise `on_delete=CASCADE, 'User'`
  // would return "on_delete".
  const firstArgMatch = stripped.match(
    /^(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*)(?!\s*=))/
  );
  if (!firstArgMatch) return undefined;
  const raw = firstArgMatch[1] || firstArgMatch[2] || firstArgMatch[3];
  if (!raw) return undefined;
  if (raw === 'self') return 'self';
  return raw.replace(/^['"]|['"]$/g, '');
}

function extractOnDelete(argsBlock: string): string | undefined {
  const m = argsBlock.match(
    /on_delete\s*=\s*(?:models\.)?([A-Z][A-Z_]+)/
  );
  if (m) return m[1];
  if (argsBlock.match(/on_delete\s*=\s*(?:models\.)?SET\s*\(/)) return 'SET';
  return undefined;
}

function extractRelatedName(argsBlock: string): string | undefined {
  const m = argsBlock.match(
    /related_name\s*=\s*(?:'([^']+)'|"([^"]+)")/
  );
  return m ? m[1] || m[2] : undefined;
}

function extractThroughModel(argsBlock: string): string | undefined {
  const m = argsBlock.match(
    /\bthrough\s*=\s*(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*))/
  );
  return m ? m[1] || m[2] || m[3] : undefined;
}

function readBalancedArgs(lines: string[], startIdx: number): {
  argsBlock: string;
  endIdx: number;
} {
  const openIdx = lines[startIdx].indexOf('(');
  let depth = 0;
  let buffer = '';
  for (let i = startIdx; i < lines.length; i++) {
    const src = i === startIdx ? lines[i].slice(openIdx) : lines[i];
    for (const ch of src) {
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0) {
          return { argsBlock: (buffer + ')').replace(/^\(/, ''), endIdx: i };
        }
      }
      buffer += ch;
    }
    buffer += '\n';
  }
  return { argsBlock: buffer.replace(/^\(/, ''), endIdx: lines.length - 1 };
}

/**
 * Pass 1 only: collect every class definition (name, bases, fields, Meta).
 *
 * No model recognition, no abstract filtering, no inheritance. Callers combine
 * the result with definitions from other files before calling
 * `resolveAndFilter`, so a base declared in another module is still found.
 * Mirrors `_collect_defs` in cli/django_orm_lens/parser.py.
 */
export function collectDefs(filePath: string, content: string): ParsedModel[] {
  // Strip leading BOM (U+FEFF) — Windows editors (Notepad, VS Code with
  // certain settings) save UTF-8 files with a byte-order mark. Without this
  // the first line becomes "﻿class Foo..." and CLASS_RE fails to match.
  if (content.charCodeAt(0) === 0xfeff) {
    content = content.slice(1);
  }
  // Expand tab characters to 4 spaces so the `\s{indent}` prefix in
  // FIELD_RE / BARE_FIELD_RE / META_ITEM_RE matches tab-indented code too.
  // A single `\t` is 1 char but visually 4 columns — without expansion,
  // tab-indented models used to have zero fields detected.
  const lines = content
    .split(/\r?\n/)
    .map((l) => l.replace(/\t/g, '    '));
  const models: ParsedModel[] = [];
  const parent = path.basename(path.dirname(filePath));
  const appName =
    parent === 'models' ? path.basename(path.dirname(path.dirname(filePath))) : parent || 'app';

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let classMatch = line.match(CLASS_RE);
    let classHeaderEnd = i;
    if (!classMatch && CLASS_START_RE.test(line)) {
      const joined = readMultilineClass(lines, i);
      if (joined) {
        classMatch = joined.match;
        classHeaderEnd = joined.endIdx;
      }
    }
    if (!classMatch) {
      i++;
      continue;
    }
    const modelName = classMatch[1];
    const baseClasses = classMatch[2]
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const model: ParsedModel = {
      name: modelName,
      appName,
      filePath,
      lineNumber: i,
      fields: [],
      inheritedFields: [],
      meta: {},
      baseClasses,
    };

    const indent = detectClassIndent(lines, classHeaderEnd);
    const { FIELD_RE, BARE_FIELD_RE, META_START_RE, META_ITEM_RE, META_BODY_RE } =
      buildBodyRegexes(indent);

    let j = classHeaderEnd + 1;
    while (j < lines.length) {
      const innerLine = lines[j];
      if (/^class\s+/.test(innerLine) && !/^\s+class/.test(innerLine)) {
        break;
      }
      if (innerLine.trim().length === 0) {
        j++;
        continue;
      }

      const metaStart = innerLine.match(META_START_RE);
      if (metaStart) {
        let k = j + 1;
        while (k < lines.length) {
          const metaLine = lines[k];
          if (metaLine.length && !META_BODY_RE.test(metaLine) && metaLine.trim().length > 0) break;
          const m = metaLine.match(META_ITEM_RE);
          if (m) {
            model.meta[m[1]] = m[2].trim();
          }
          k++;
        }
        j = k;
        continue;
      }

      const fieldMatch = innerLine.match(FIELD_RE) ?? innerLine.match(BARE_FIELD_RE);
      if (fieldMatch) {
        const fieldName = fieldMatch[1];
        const fieldType = fieldMatch[2];
        const { argsBlock, endIdx } = readBalancedArgs(lines, j);
        const relationKind =
          fieldType === 'TaggableManager'
            ? 'ManyToManyField'
            : TREE_FIELD_ALIASES[fieldType] ??
              (RELATION_TYPES.includes(fieldType as RelationKind)
                ? (fieldType as RelationKind)
                : undefined);
        const isRel = relationKind !== undefined;
        const field: ParsedField = {
          name: fieldName,
          type: fieldType,
          args: argsBlock.slice(0, -1).trim(),
          isRelation: isRel,
          lineNumber: j,
        };
        if (isRel) {
          field.relationKind = relationKind;
          const argsInner = argsBlock.slice(0, -1);
          field.relatedModel =
            fieldType === 'TaggableManager'
              ? 'taggit.Tag'
              : extractRelated(argsInner);
          const onDelete = extractOnDelete(argsInner);
          if (onDelete) field.onDelete = onDelete;
          const relatedName = extractRelatedName(argsInner);
          if (relatedName) field.relatedName = relatedName;
          if (relationKind === 'ManyToManyField') {
            const throughModel = extractThroughModel(argsInner);
            if (throughModel) {
              field.throughModel = throughModel;
            } else if (fieldType === 'TaggableManager') {
              field.throughModel = 'taggit.TaggedItem';
            }
          }
        }
        model.fields.push(field);
        j = endIdx + 1;
        continue;
      }

      j++;
    }

    models.push(model);
    i = j;
  }

  return models;
}

/** Django drops a model with `Meta.abstract = True` — it has no table. */
function isAbstract(model: ParsedModel): boolean {
  return ['True', '1', 'true'].includes((model.meta.abstract ?? '').trim());
}

/**
 * Fields `model` inherits from its **abstract** bases, parent-first.
 *
 * Only abstract bases contribute. A concrete base is multi-table inheritance,
 * where the parent keeps its own table and the child gains a `parent_ptr`
 * rather than copies of the columns — counting those as the child's own would
 * invent columns no migration will ever create.
 *
 * Bases are walked in declaration order and the first declaration of a name
 * wins, which is the direction Python's MRO resolves for the single-
 * inheritance chains this actually matters for. `stack` breaks cycles in
 * malformed source instead of recursing forever.
 *
 * Mirrors `_abstract_bases_fields` in cli/django_orm_lens/parser.py.
 */
function abstractBasesFields(
  model: ParsedModel,
  byName: Map<string, ParsedModel>,
  stack: readonly string[] = []
): ParsedField[] {
  const out: ParsedField[] = [];
  const taken = new Set<string>();
  for (const base of model.baseClasses) {
    const tail = base.split('.').pop() ?? '';
    if (stack.includes(tail)) continue;
    const parent = byName.get(tail);
    if (!parent || parent === model || !isAbstract(parent)) continue;
    const contributed: ParsedField[] = [
      ...abstractBasesFields(parent, byName, [...stack, tail]),
      ...parent.fields.map((f) => ({
        ...f,
        inheritedFrom: f.inheritedFrom ?? parent.name,
      })),
    ];
    for (const f of contributed) {
      if (taken.has(f.name)) continue;
      taken.add(f.name);
      out.push(f);
    }
  }
  return out;
}

/**
 * Populate `inheritedFields` on every def, in place.
 *
 * Runs before the abstract classes are dropped — they are the only source of
 * inherited fields, so the merge has to happen while they are still present. A
 * field the class declares itself shadows the inherited one of the same name,
 * exactly as an override does in Django.
 */
function attachInheritedFields(allDefs: ParsedModel[]): void {
  const byName = new Map<string, ParsedModel>();
  for (const m of allDefs) {
    // First definition wins when two files declare the same class name; the
    // parser has no import graph to disambiguate with.
    if (!byName.has(m.name)) byName.set(m.name, m);
  }
  for (const m of allDefs) {
    const own = new Set(m.fields.map((f) => f.name));
    m.inheritedFields = abstractBasesFields(m, byName).filter((f) => !own.has(f.name));
  }
}

/**
 * Pass 2: transitive model recognition, then the abstract drop.
 *
 * `allDefs` may be one file's definitions (`parseModelsFile`) or the union of
 * every file in a scan (`scanWorkspace`). Recognition matches each base's tail
 * name against whatever definitions are present, so a base class defined in
 * another file is found when the union is passed.
 *
 * The loop runs to a **fixed point** rather than in source order. Order-
 * dependent recognition misses `class Post(TimeStamped)` written above its
 * base, which is ordinary once the base is imported rather than declared
 * locally. Mirrors `_resolve_and_filter` in cli/django_orm_lens/parser.py; the
 * two must stay in step or the sidebar and the CLI disagree about a schema.
 */
export function resolveAndFilter(allDefs: ParsedModel[]): ParsedModel[] {
  attachInheritedFields(allDefs);
  const isModelName = new Set(
    allDefs.filter((m) => looksLikeModel(m.baseClasses)).map((m) => m.name)
  );
  let changed = true;
  while (changed) {
    changed = false;
    for (const m of allDefs) {
      if (isModelName.has(m.name)) continue;
      for (const b of m.baseClasses) {
        if (isModelName.has(b.split('.').pop() ?? '')) {
          isModelName.add(m.name);
          changed = true;
          break;
        }
      }
    }
  }
  return allDefs.filter((m) => isModelName.has(m.name) && !isAbstract(m));
}

/**
 * Parse a single models.py-style file. Returns 0..N Django model classes.
 *
 * Resolution here is scoped to this one file's definitions. Use
 * `scanWorkspace` when bases may live in another parsed module (a shared
 * abstract base imported from elsewhere in the project) — it collects
 * definitions across every file first and resolves the union once.
 */
export function parseModelsFile(filePath: string, content: string): ParsedModel[] {
  return resolveAndFilter(collectDefs(filePath, content));
}

function appDirFor(fsPath: string): { dir: string; name: string } {
  const parent = path.dirname(fsPath);
  const parentName = path.basename(parent);
  if (parentName === 'models') {
    const grand = path.dirname(parent);
    return { dir: grand, name: path.basename(grand) };
  }
  return { dir: parent, name: parentName };
}

// Convert a "**/name/**" style glob prefix/segment into a simple test.
// We only need enough coverage for the default exclude patterns
// (**/migrations/**, **/venv/**, **/node_modules/**, etc.) — anything more
// exotic falls back to matching the raw pattern as a substring.
function excludeMatcher(patterns: string[]): (relPosix: string) => boolean {
  const segments = patterns
    .map((p) => {
      const m = p.match(/^\*\*\/([^/*]+)\/\*\*$/);
      return m ? m[1] : null;
    })
    .filter((s): s is string => !!s);
  const raw = patterns.filter((p) => !/^\*\*\/([^/*]+)\/\*\*$/.test(p));
  return (rel: string) => {
    const parts = rel.split('/');
    for (const seg of segments) if (parts.includes(seg)) return true;
    for (const r of raw) if (rel.includes(r)) return true;
    return false;
  };
}

/**
 * Files that declare models but are not named `models.py`.
 *
 * Pluggable Django frameworks keep their abstract bases in
 * `abstract_models.py` and leave `models.py` holding only the concrete
 * subclasses — django-oscar does this in all 14 of its apps. Without reading
 * these, oscar's models parse as classes with no fields between them: found,
 * but empty, which reads as a schema that lost its columns. Mirrors
 * MODEL_SOURCE_FILES in cli/django_orm_lens/parser.py.
 */
const MODEL_SOURCE_FILES = new Set(['models.py', 'abstract_models.py']);

// Walk a directory synchronously collecting every models.py and models/*.py.
// Used as a fallback when vscode.workspace.findFiles returns no results
// (workspace file index cold, or platform-specific glob quirks that
// silently drop root-level models.py — the recurring "opened the Django
// app folder as the workspace root, extension shows empty" report).
function walkForModels(root: string, isExcluded: (rel: string) => boolean): string[] {
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
      if (entry.name === '__init__.py') continue;
      if (MODEL_SOURCE_FILES.has(entry.name)) {
        results.push(full);
        continue;
      }
      // models/<something>.py — the split-package layout.
      if (path.basename(dir) === 'models' && entry.name.endsWith('.py')) {
        results.push(full);
      }
    }
  }
  return results;
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
    ])
  );
  const seen = new Set<string>();
  const uris: vscode.Uri[] = [];
  for (const batch of results) {
    for (const u of batch) {
      if (u.fsPath.endsWith('__init__.py')) continue;
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
      console.error(`django-orm-lens: parser error in ${uri.fsPath}`, err);
    }
  }

  for (const model of resolveAndFilter(allDefs)) {
    const { dir: appDir, name: appName } = appDirFor(model.filePath);
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
