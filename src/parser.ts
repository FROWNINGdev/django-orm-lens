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

// django-mptt's Tree* fields are thin subclasses of Django's own relation
// fields — same `to`, same `on_delete`, same `related_name`. Mapping the name
// to its Django counterpart is the whole fix: every extractor below keeps
// working unchanged. Mirrors TREE_FIELD_ALIASES in cli/orm_synapse/parser.py;
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

interface NeighborhoodNode {
  id: string;
  app: string;
  model: ParsedModel;
}

interface RelationGraph {
  nodes: NeighborhoodNode[];
  byId: Map<string, NeighborhoodNode>;
  resolve(related: string, self: NeighborhoodNode): string[];
  /** `resolve`, with a proxy target replaced by the concrete model that owns its table. */
  tableIds(related: string, self: NeighborhoodNode): string[];
  concreteNode(node: NeighborhoodNode): NeighborhoodNode;
}

function metaToken(model: ParsedModel, key: string): string {
  return (model.meta?.[key] ?? '').trim().replace(/,$/, '').trim();
}

/** `Meta.proxy = True`. A proxy has no table of its own. */
export function isProxyModel(model: ParsedModel): boolean {
  return ['True', '1', 'true'].includes(metaToken(model, 'proxy'));
}

/** `Meta.managed = False`. The table exists; Django does not create it. */
export function isUnmanagedModel(model: ParsedModel): boolean {
  return ['False', '0', 'false'].includes(metaToken(model, 'managed'));
}

function buildRelationGraph(index: WorkspaceIndex): RelationGraph {
  const nodes: NeighborhoodNode[] = [];
  const byName = new Map<string, NeighborhoodNode[]>();
  const byId = new Map<string, NeighborhoodNode>();
  for (const app of index.apps) {
    for (const model of app.models) {
      const node: NeighborhoodNode = { id: `${app.name}/${model.name}`, app: app.name, model };
      nodes.push(node);
      byId.set(node.id, node);
      const list = byName.get(model.name) ?? [];
      list.push(node);
      byName.set(model.name, list);
    }
  }
  const userModelName = findUserModel(index)?.name;
  const resolve = (related: string, self: NeighborhoodNode): string[] => {
    if (related === 'self') return [self.id];
    const tail = resolveRelatedTail(related, userModelName);
    if (!tail || tail === 'Model' || tail === 'object') return [];
    const candidates = byName.get(tail) ?? [];
    const parts = related.split('.');
    if (parts.length >= 2) {
      const label = parts[parts.length - 2];
      const labeled = candidates.filter(
        (node) =>
          node.app === label ||
          node.model.appName === label ||
          node.model.filePath.replace(/\\/g, '/').split('/').includes(label)
      );
      if (labeled.length > 0) return labeled.map((node) => node.id);
    }
    return candidates.map((node) => node.id);
  };
  const concreteNode = (node: NeighborhoodNode): NeighborhoodNode => {
    const seen = new Set<string>();
    let current = node;
    while (isProxyModel(current.model) && !seen.has(current.id)) {
      seen.add(current.id);
      let next: NeighborhoodNode | undefined;
      for (const base of current.model.baseClasses ?? []) {
        const tail = base.split('.').pop() ?? '';
        if (!tail || /Mixin$/.test(tail)) continue;
        const candidates = byName.get(tail) ?? [];
        const label = base.split('.').length >= 2 ? base.split('.').at(-2) : undefined;
        const labeled = label
          ? candidates.filter((candidate) => candidate.app === label || candidate.model.appName === label)
          : [];
        const pick =
          labeled[0] ??
          candidates.find((candidate) => candidate.app === current.app || candidate.model.appName === current.app) ??
          candidates[0];
        if (pick && pick.id !== current.id) {
          next = pick;
          break;
        }
      }
      if (!next) break;
      current = next;
    }
    return current;
  };
  const tableIds = (related: string, self: NeighborhoodNode): string[] => {
    const out: string[] = [];
    const seen = new Set<string>();
    for (const id of resolve(related, self)) {
      const node = byId.get(id);
      const table = node ? concreteNode(node).id : id;
      if (seen.has(table)) continue;
      seen.add(table);
      out.push(table);
    }
    return out;
  };
  return { nodes, byId, resolve, tableIds, concreteNode };
}

/**
 * The model whose table a proxy uses. A concrete model is returned unchanged.
 */
export function tableModel(index: WorkspaceIndex, model: ParsedModel): ParsedModel {
  const graph = buildRelationGraph(index);
  const node = graph.byId.get(`${model.appName}/${model.name}`);
  return node ? graph.concreteNode(node).model : model;
}

/**
 * Index the ER diagram draws.
 *
 * Proxy models are omitted once their concrete table is in the index, and a
 * relation that names a proxy is redrawn onto that table. Unmanaged models
 * stay: they still have a table.
 */
export function diagramIndex(index: WorkspaceIndex): WorkspaceIndex {
  const graph = buildRelationGraph(index);
  const rewrite = (model: ParsedModel, field: ParsedField): ParsedField => {
    if (!field.isRelation || !field.relatedModel || field.relatedModel === 'self') return field;
    const node = graph.byId.get(`${model.appName}/${model.name}`);
    if (!node) return field;
    const raw = graph.resolve(field.relatedModel, node);
    const rawNodes = raw.map((id) => graph.byId.get(id)).filter((item): item is NeighborhoodNode => !!item);
    if (rawNodes.length === 0 || rawNodes.some((item) => !isProxyModel(item.model))) return field;
    const tables = graph.tableIds(field.relatedModel, node);
    if (tables.length !== 1) return field;
    const table = graph.byId.get(tables[0]);
    if (!table) return field;
    const next = `${table.model.appName}.${table.model.name}`;
    return next === field.relatedModel ? field : { ...field, relatedModel: next };
  };
  return {
    ...index,
    apps: index.apps
      .map((app) => ({
        ...app,
        models: app.models
          .filter((model) => {
            const node = graph.byId.get(`${app.name}/${model.name}`);
            return !node || graph.concreteNode(node).id === node.id;
          })
          .map((model) => ({
            ...model,
            fields: model.fields.map((field) => rewrite(model, field)),
            inheritedFields: (model.inheritedFields ?? []).map((field) => rewrite(model, field)),
          })),
      }))
      .filter((app) => app.models.length > 0),
  };
}

/**
 * Columns Django copies onto this model's table: abstract-base fields first,
 * then fields the class declares itself. A concrete parent is not included —
 * those columns stay on the parent's table.
 */
export function concreteFields(model: ParsedModel): ParsedField[] {
  return [...(model.inheritedFields ?? []), ...model.fields];
}

function relationFields(model: ParsedModel): ParsedField[] {
  return concreteFields(model).filter((field) => field.isRelation && !!field.relatedModel);
}

/**
 * How many relation fields point straight at each model: its children.
 *
 * A child is a model holding a ForeignKey, OneToOneField, or ManyToManyField
 * to this one. A self-relation is a child relation too. Fields this model
 * holds toward its own parents are not counted, and neither are grandchildren.
 */
export function childRelationCounts(index: WorkspaceIndex): Map<ParsedModel, number> {
  const graph = buildRelationGraph(index);
  const counts = new Map<ParsedModel, number>();
  for (const node of graph.nodes) counts.set(node.model, 0);
  for (const node of graph.nodes) {
    for (const field of relationFields(node.model)) {
      for (const targetId of graph.tableIds(field.relatedModel!, node)) {
        const target = graph.byId.get(targetId);
        if (target) counts.set(target.model, (counts.get(target.model) ?? 0) + 1);
      }
    }
  }
  return counts;
}

/**
 * Models kept when a class lens opens the ER diagram.
 *
 * Keeps the clicked model, every descendant, and the parents of those
 * descendants. A descendant is reached through a relation field pointing at a
 * model already kept, or a subclass of one (mixins excluded), repeated until
 * no new model appears. Parents of the clicked model itself are left out,
 * even when a descendant also points at one of them. Parents added this way
 * are not expanded further. A proxy model is not drawn: opening one starts
 * from the concrete model that owns its table, and a relation aimed at a
 * proxy is treated as a relation to that table. Ids are `app/model`. Returns
 * undefined when the file and line do not match a model.
 */
export function modelNeighborhoodIds(
  index: WorkspaceIndex,
  filePath: string,
  lineNumber: number
): string[] | undefined {
  const want = filePath.replace(/\\/g, '/').toLowerCase();
  const graph = buildRelationGraph(index);
  const source = graph.nodes.find((node) => {
    const path = node.model.filePath.replace(/\\/g, '/').toLowerCase();
    return path === want && node.model.lineNumber === lineNumber;
  });
  if (!source) return undefined;
  const root = graph.concreteNode(source);

  const parentIdsOf = (node: NeighborhoodNode): string[] => {
    const ids: string[] = [];
    for (const field of relationFields(node.model)) {
      ids.push(...graph.tableIds(field.relatedModel!, node));
    }
    for (const base of node.model.baseClasses ?? []) {
      // A mixin shared by dozens of models is not a parent.
      if (/Mixin$/.test(base.split('.').pop() ?? '')) continue;
      ids.push(...graph.tableIds(base, node));
    }
    return ids;
  };

  const children = new Map<string, Set<string>>();
  const addChild = (parentId: string, childId: string) => {
    if (parentId === childId) return;
    const set = children.get(parentId) ?? new Set<string>();
    set.add(childId);
    children.set(parentId, set);
  };
  for (const node of graph.nodes) {
    for (const parentId of parentIdsOf(node)) addChild(parentId, node.id);
  }

  const rootParents = new Set(parentIdsOf(root));
  const seen = new Set<string>();
  const queue = [root.id];
  while (queue.length > 0) {
    const id = queue.pop()!;
    if (seen.has(id)) continue;
    const node = graph.byId.get(id);
    if (node && isProxyModel(node.model) && graph.concreteNode(node).id !== id) continue;
    seen.add(id);
    for (const next of children.get(id) ?? []) {
      if (!seen.has(next)) queue.push(next);
    }
  }
  const descendants = [...seen];
  for (const id of descendants) {
    if (id === root.id) continue;
    const node = graph.byId.get(id);
    if (!node) continue;
    for (const parentId of parentIdsOf(node)) {
      if (!rootParents.has(parentId)) seen.add(parentId);
    }
  }
  return [...seen];
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
 * recognised. Mirrors `_looks_like_model` in cli/orm_synapse/parser.py.
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
  // Project-local subclasses: `TinyIntegerField`, `BaseForeignKey`, ...
  '[A-Z][A-Za-z0-9_]*Field', '[A-Z][A-Za-z0-9_]*ForeignKey',
].join('|');
// GenericForeignKey is a descriptor over two columns, not a column itself.
const BARE_FIELD_PATTERN = `(?!GenericForeignKey\\b)(?:${BARE_FIELD_TYPES})`;

/**
 * Relation kind for a field class name. Subclasses keep Django's suffix
 * (`BaseForeignKey`, `BaseOneToOneField`), so the suffix decides.
 * Mirrors `_relation_kind` in cli/orm_synapse/parser.py.
 */
function relationKindOf(fieldType: string): RelationKind | undefined {
  if (fieldType === 'TaggableManager') return 'ManyToManyField';
  const alias = TREE_FIELD_ALIASES[fieldType];
  if (alias) return alias;
  if (fieldType === 'GenericForeignKey') return undefined;
  if (fieldType.endsWith('ManyToManyField')) return 'ManyToManyField';
  if (fieldType.endsWith('OneToOneField')) return 'OneToOneField';
  if (fieldType.endsWith('ForeignKey')) return 'ForeignKey';
  return undefined;
}

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
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)${ann}\\s*=\\s*${prefixOpt}(${BARE_FIELD_PATTERN})\\s*\\(`
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
 * Mirrors `_collect_defs` in cli/orm_synapse/parser.py.
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
        const relationKind = relationKindOf(fieldType);
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
 * Mirrors `_abstract_bases_fields` in cli/orm_synapse/parser.py.
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
 * locally. Mirrors `_resolve_and_filter` in cli/orm_synapse/parser.py; the
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
