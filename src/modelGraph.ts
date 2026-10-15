import { ParsedApp, ParsedField, ParsedModel, RelationKind, WorkspaceIndex } from './types';

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
