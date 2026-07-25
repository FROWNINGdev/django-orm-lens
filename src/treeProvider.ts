import * as vscode from 'vscode';
import { ParsedField, ParsedModel, TreeNode, WorkspaceIndex } from './types';
import {
  FLAG_MISSING_MAX_LENGTH,
  FLAG_MISSING_ON_DELETE,
  FLAG_NULL_ON_STRING,
  FLAG_TEXTFIELD_MAX_LENGTH,
  makeDecorationUri,
} from './decorations';

/**
 * Django ORM Lens — sidebar tree.
 *
 * v0.8 UX overhaul distilled from the top-tier extensions (GitLens,
 * Todo Tree, Docker, GitHub PRs) and community forum feedback:
 *
 *   1. Stable `TreeItem.id` — refresh no longer collapses the tree.
 *   2. Rich `TreeItem.description` — Apps show model count, Models show
 *      "N fields · pk BigAuto", Fields show "CharField · null, blank".
 *   3. Rich MarkdownString tooltips with `command:` deep-links (isTrusted).
 *   4. Narrower `contextValue`s (`app`, `model`, `field.fk`, `field.plain`,
 *      `meta`, `metaItem`) so right-click menus are type-appropriate.
 *   5. `getParent()` — required for `TreeView.reveal(...)`, used later by
 *      the "follow active editor" wiring.
 *   6. Filter query persists in `workspaceState` and survives reload.
 *
 * The provider does NOT decide when to refresh — that stays with
 * `src/extension.ts` scan orchestration. This module is a pure adapter:
 * WorkspaceIndex → TreeNode[] → vscode.TreeItem.
 */

const FILTER_STATE_KEY = 'djangoOrmLens.filter';

/* -----------------------------  helpers  ----------------------------- */

function iconForField(field: ParsedField): string {
  if (field.isRelation) {
    switch (field.relationKind) {
      case 'ForeignKey':
        return 'references';
      case 'ManyToManyField':
        return 'organization';
      case 'OneToOneField':
        return 'link';
    }
  }
  const t = field.type;
  if (/Char|Text|Slug|Email|URL|UUID/.test(t)) return 'symbol-string';
  if (/Integer|Float|Decimal|BigInteger|SmallInteger|Positive/.test(t))
    return 'symbol-numeric';
  if (/Bool/.test(t)) return 'symbol-boolean';
  if (/DateTime|Date|Time|Duration/.test(t)) return 'calendar';
  if (/JSON|Binary|File|Image/.test(t)) return 'file';
  return 'symbol-field';
}

/** Parse notable kwargs from the raw args body: null, blank, unique, pk. */
function fieldFlags(f: ParsedField): string[] {
  const flags: string[] = [];
  if (/\bnull\s*=\s*True\b/.test(f.args)) flags.push('null');
  if (/\bblank\s*=\s*True\b/.test(f.args)) flags.push('blank');
  if (/\bunique\s*=\s*True\b/.test(f.args)) flags.push('unique');
  if (/\bprimary_key\s*=\s*True\b/.test(f.args)) flags.push('pk');
  if (/\bdb_index\s*=\s*True\b/.test(f.args)) flags.push('indexed');
  return flags;
}

/** Best-effort primary-key type — falls back to Django's default. */
function pkTypeOf(model: ParsedModel): string {
  for (const f of model.fields) {
    if (/\bprimary_key\s*=\s*True\b/.test(f.args)) return f.type;
  }
  return 'BigAutoField';
}

function contextValueForField(f: ParsedField): string {
  if (/\bprimary_key\s*=\s*True\b/.test(f.args)) return 'field.pk';
  if (f.isRelation) return 'field.fk';
  return 'field.plain';
}

/**
 * Pick the highest-severity decoration flag for a field based on the same
 * regexes the DOL### rules use. Returns undefined when no decoration
 * applies. Order matters — the first matching flag wins.
 */
function decorationFlagForField(f: ParsedField): string | undefined {
  // DOL013 — FK without on_delete: high severity, red badge.
  if (f.isRelation && f.relationKind === 'ForeignKey' && !/\bon_delete\s*=/.test(f.args)) {
    return FLAG_MISSING_ON_DELETE;
  }
  // DOL014 — CharField without max_length: same severity.
  if (f.type === 'CharField' && !/\bmax_length\s*=/.test(f.args)) {
    return FLAG_MISSING_MAX_LENGTH;
  }
  // DOL011 — null=True on string-based field.
  if (
    (f.type === 'CharField' || f.type === 'TextField') &&
    /\bnull\s*=\s*True\b/.test(f.args)
  ) {
    return FLAG_NULL_ON_STRING;
  }
  // DOL015 — TextField with max_length (no DB effect).
  if (f.type === 'TextField' && /\bmax_length\s*=/.test(f.args)) {
    return FLAG_TEXTFIELD_MAX_LENGTH;
  }
  return undefined;
}

/** Escape a value for safe embedding inside a Markdown table cell. */
function mdCell(v: string): string {
  // Escape backslash first — otherwise CodeQL js/incomplete-sanitization
  // flags us because a raw \ in the input could combine with the following
  // \| escape and defeat it (\ + \| = \\| = literal \|). Even though our
  // inputs (Django model/field names) rarely contain \, escape defensively.
  return v.replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

/**
 * Build a rich MarkdownString-ready description for a model, with a
 * fields table and clickable command deep-links. Requires isTrusted=true
 * on the resulting MarkdownString for command: URIs to fire.
 */
function markdownForModel(app: string, model: ParsedModel): string {
  const bases = model.baseClasses.length
    ? `class ${model.name}(${model.baseClasses.join(', ')})`
    : `class ${model.name}`;
  const rows = model.fields
    .map((f) => {
      const type = f.isRelation
        ? `${f.relationKind} → ${f.relatedModel ?? '?'}`
        : f.type;
      const flags = fieldFlags(f).join(', ');
      return `| \`${mdCell(f.name)}\` | ${mdCell(type)} | ${mdCell(flags)} |`;
    })
    .join('\n');
  const jumpArg = encodeURIComponent(
    JSON.stringify([model.filePath, model.lineNumber]),
  );
  const parts: string[] = [
    `**${app}.${model.name}**  \n\`${bases}\``,
    '',
    `**Fields** (${model.fields.length})`,
    '',
    '| Name | Type | Flags |',
    '|---|---|---|',
    rows || '| _(no fields)_ | | |',
  ];
  if (Object.keys(model.meta).length) {
    parts.push('', '**Meta**', '');
    for (const [k, v] of Object.entries(model.meta)) {
      parts.push(`- \`${mdCell(k)}\`: \`${mdCell(v)}\``);
    }
  }
  parts.push(
    '',
    `[$(go-to-file) Open definition](command:djangoOrmLens.jumpToModel?${jumpArg})`,
    ' · ',
    '[$(type-hierarchy) Show ER diagram](command:djangoOrmLens.showGraph)',
  );
  return parts.join('\n');
}

function markdownForField(model: ParsedModel, field: ParsedField): string {
  const flags = fieldFlags(field);
  const call = `models.${field.type}(${field.args})`;
  const parts: string[] = [
    `**${model.name}.${field.name}**  \n\`${call}\``,
  ];
  if (field.isRelation) {
    parts.push(
      '',
      `Relation: **${field.relationKind}** → \`${field.relatedModel ?? '?'}\``,
    );
    if (field.onDelete) parts.push(`on\\_delete: \`${field.onDelete}\``);
    if (field.relatedName) parts.push(`related\\_name: \`${field.relatedName}\``);
    if (field.throughModel) parts.push(`through: \`${field.throughModel}\``);
  }
  if (flags.length) parts.push('', `Flags: ${flags.map((f) => `\`${f}\``).join(', ')}`);
  return parts.join('\n');
}

/* ------------------------------  build  ------------------------------ */

function buildTree(index: WorkspaceIndex): TreeNode[] {
  return index.apps.map<TreeNode>((app) => ({
    id: app.name,
    kind: 'app',
    label: app.name,
    description: `${app.models.length} model${app.models.length === 1 ? '' : 's'}`,
    tooltip: app.path,
    iconId: 'folder',
    contextValue: 'app',
    children: app.models.map<TreeNode>((model) => {
      const pk = pkTypeOf(model);
      return {
        id: `${app.name}/${model.name}`,
        kind: 'model',
        label: model.name,
        description: `${model.fields.length} field${
          model.fields.length === 1 ? '' : 's'
        } · pk ${pk}`,
        tooltipMarkdown: markdownForModel(app.name, model),
        iconId: 'symbol-class',
        contextValue: 'model',
        filePath: model.filePath,
        lineNumber: model.lineNumber,
        children: [
          ...model.fields.map<TreeNode>((field) => {
            const flags = fieldFlags(field);
            const desc = field.isRelation
              ? `${field.relationKind} → ${field.relatedModel ?? '?'}`
              : field.type;
            const nodeId = `${app.name}/${model.name}/${field.name}`;
            const decorFlag = decorationFlagForField(field);
            return {
              id: nodeId,
              kind: 'field',
              label: field.name,
              description: flags.length ? `${desc} · ${flags.join(', ')}` : desc,
              tooltipMarkdown: markdownForField(model, field),
              iconId: iconForField(field),
              contextValue: contextValueForField(field),
              filePath: model.filePath,
              lineNumber: field.lineNumber,
              resourceUriString: decorFlag
                ? makeDecorationUri(nodeId, decorFlag).toString()
                : undefined,
            };
          }),
          ...(Object.keys(model.meta).length
            ? [
                {
                  id: `${app.name}/${model.name}/__meta__`,
                  kind: 'meta' as const,
                  label: 'Meta',
                  iconId: 'settings-gear',
                  contextValue: 'meta',
                  children: Object.entries(model.meta).map<TreeNode>(([k, v]) => ({
                    id: `${app.name}/${model.name}/__meta__/${k}`,
                    kind: 'metaItem',
                    label: k,
                    description: v,
                    iconId: 'symbol-key',
                    contextValue: 'metaItem',
                  })),
                },
              ]
            : []),
        ],
      };
    }),
  }));
}

function filterTree(nodes: TreeNode[], needle: string): TreeNode[] {
  if (!needle) return nodes;
  const q = needle.toLowerCase();
  const walk = (list: TreeNode[]): TreeNode[] => {
    const out: TreeNode[] = [];
    for (const n of list) {
      const selfHit =
        n.label.toLowerCase().includes(q) ||
        (n.description ?? '').toLowerCase().includes(q);
      const kids = n.children ? walk(n.children) : [];
      if (selfHit || kids.length > 0) {
        out.push({ ...n, children: kids.length > 0 ? kids : n.children });
      }
    }
    return out;
  };
  return walk(nodes);
}

/* -----------------------------  provider  ---------------------------- */

export class DjangoTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private _onDidChangeTreeData = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private roots: TreeNode[] = [];
  private filter = '';
  private totalModels = 0;
  /** Reverse map: node id → parent node. Filled during buildTree(). */
  private parentById = new Map<string, TreeNode>();
  private nodeById = new Map<string, TreeNode>();

  constructor(private readonly memento?: vscode.Memento) {
    if (memento) {
      const persisted = memento.get<string>(FILTER_STATE_KEY, '');
      if (persisted) this.filter = persisted;
    }
  }

  setIndex(index: WorkspaceIndex) {
    this.roots = buildTree(index);
    this.totalModels = index.apps.reduce((n, a) => n + a.models.length, 0);
    this.parentById.clear();
    this.nodeById.clear();
    const walk = (list: TreeNode[], parent?: TreeNode) => {
      for (const n of list) {
        this.nodeById.set(n.id, n);
        if (parent) this.parentById.set(n.id, parent);
        if (n.children) walk(n.children, n);
      }
    };
    walk(this.roots);
    this._onDidChangeTreeData.fire(undefined);
  }

  isEmpty(): boolean {
    return this.roots.length === 0;
  }

  setFilter(needle: string) {
    this.filter = needle.trim();
    this.memento?.update(FILTER_STATE_KEY, this.filter);
    this._onDidChangeTreeData.fire(undefined);
  }

  getFilter(): string {
    return this.filter;
  }

  /** Look up a node by its id — used by extension.ts for reveal-on-editor. */
  findNodeById(id: string): TreeNode | undefined {
    return this.nodeById.get(id);
  }

  /**
   * Find the first `model`-kind node whose filePath matches. Used to
   * reveal the sidebar node for the currently active editor.
   */
  findModelNodeByPath(filePath: string): TreeNode | undefined {
    for (const [, node] of this.nodeById) {
      if (node.kind === 'model' && node.filePath === filePath) return node;
    }
    return undefined;
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    const hasChildren = !!element.children && element.children.length > 0;
    const largeProject = this.totalModels > 40;
    const activeFilter = this.filter.length > 0;
    const collapsible = !hasChildren
      ? vscode.TreeItemCollapsibleState.None
      : element.kind === 'app' && !largeProject && !activeFilter
      ? vscode.TreeItemCollapsibleState.Expanded
      : element.kind === 'app' && activeFilter
      ? vscode.TreeItemCollapsibleState.Expanded
      : vscode.TreeItemCollapsibleState.Collapsed;
    const item = new vscode.TreeItem(element.label, collapsible);
    item.id = element.id;
    item.description = element.description;
    if (element.resourceUriString) {
      item.resourceUri = vscode.Uri.parse(element.resourceUriString);
    }
    if (element.tooltipMarkdown) {
      const md = new vscode.MarkdownString(element.tooltipMarkdown, true);
      // Scope isTrusted to ONLY the commands we intentionally emit in the
      // tooltip markdown. Setting `isTrusted = true` (broad) would allow any
      // `command:xxx` URI in the tooltip to fire — including workbench.action.*
      // — and the tooltip text is built from Django model/field names read
      // from the workspace, which could be adversarial in a supply-chain
      // scenario. Match the hover provider's whitelist.
      md.isTrusted = { enabledCommands: ['djangoOrmLens.jumpToModel', 'djangoOrmLens.showGraph'] };
      md.supportThemeIcons = true;
      item.tooltip = md;
    } else {
      item.tooltip = element.tooltip ?? element.label;
    }
    if (element.iconId) item.iconPath = new vscode.ThemeIcon(element.iconId);
    // Legacy value kept for backwards-compat with existing menu registrations.
    if (element.kind === 'model') {
      item.contextValue = 'djangoOrmLensModel';
    } else if (element.contextValue) {
      item.contextValue = element.contextValue;
    }
    if (element.filePath && typeof element.lineNumber === 'number') {
      item.command = {
        command: 'djangoOrmLens.jumpToModel',
        title: 'Jump to definition',
        arguments: [element.filePath, element.lineNumber],
      };
    }
    return item;
  }

  /** VS Code needs this for `TreeView.reveal(...)` to work. */
  getParent(element: TreeNode): TreeNode | undefined {
    return this.parentById.get(element.id);
  }

  getChildren(element?: TreeNode): TreeNode[] {
    const filtered = filterTree(this.roots, this.filter);
    if (!element) return filtered;
    if (this.filter) {
      // When filtered, find the matching cloned node by its stable id.
      const walk = (list: TreeNode[]): TreeNode | undefined => {
        for (const n of list) {
          if (n.id === element.id) return n;
          if (n.children) {
            const found = walk(n.children);
            if (found) return found;
          }
        }
        return undefined;
      };
      const match = walk(filtered);
      return match?.children ?? element.children ?? [];
    }
    return element.children ?? [];
  }
}
