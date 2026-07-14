import * as vscode from 'vscode';
import { ParsedField, TreeNode, WorkspaceIndex } from './types';

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

function buildTree(index: WorkspaceIndex): TreeNode[] {
  return index.apps.map<TreeNode>((app) => ({
    kind: 'app',
    label: app.name,
    description: `${app.models.length} model${app.models.length === 1 ? '' : 's'}`,
    tooltip: app.path,
    iconId: 'folder',
    children: app.models.map<TreeNode>((model) => ({
      kind: 'model',
      label: model.name,
      description: model.baseClasses.join(', '),
      tooltip: model.baseClasses.length
        ? `class ${model.name}(${model.baseClasses.join(', ')})`
        : `class ${model.name}`,
      iconId: 'symbol-class',
      filePath: model.filePath,
      lineNumber: model.lineNumber,
      children: [
        ...model.fields.map<TreeNode>((field) => ({
          kind: 'field',
          label: field.name,
          description: field.isRelation
            ? `${field.relationKind} → ${field.relatedModel ?? '?'}`
            : field.type,
          tooltip: `${field.name} = models.${field.type}(${field.args})`,
          iconId: iconForField(field),
          filePath: model.filePath,
          lineNumber: field.lineNumber,
        })),
        ...(Object.keys(model.meta).length
          ? [
              {
                kind: 'meta' as const,
                label: 'Meta',
                iconId: 'settings-gear',
                children: Object.entries(model.meta).map<TreeNode>(([k, v]) => ({
                  kind: 'metaItem',
                  label: k,
                  description: v,
                  iconId: 'symbol-key',
                })),
              },
            ]
          : []),
      ],
    })),
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

export class DjangoTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private _onDidChangeTreeData = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private roots: TreeNode[] = [];
  private filter = '';
  private totalModels = 0;

  setIndex(index: WorkspaceIndex) {
    this.roots = buildTree(index);
    this.totalModels = index.apps.reduce((n, a) => n + a.models.length, 0);
    this._onDidChangeTreeData.fire(undefined);
  }

  isEmpty(): boolean {
    return this.roots.length === 0;
  }

  setFilter(needle: string) {
    this.filter = needle.trim();
    this._onDidChangeTreeData.fire(undefined);
  }

  getFilter(): string {
    return this.filter;
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
    item.description = element.description;
    item.tooltip = element.tooltip ?? element.label;
    if (element.iconId) item.iconPath = new vscode.ThemeIcon(element.iconId);
    if (element.filePath && typeof element.lineNumber === 'number') {
      item.command = {
        command: 'djangoOrmLens.jumpToModel',
        title: 'Jump to definition',
        arguments: [element.filePath, element.lineNumber],
      };
    }
    return item;
  }

  getChildren(element?: TreeNode): TreeNode[] {
    const filtered = filterTree(this.roots, this.filter);
    if (!element) return filtered;
    if (this.filter) {
      const walk = (list: TreeNode[]): TreeNode | undefined => {
        for (const n of list) {
          if (
            n.label === element.label &&
            n.kind === element.kind &&
            n.filePath === element.filePath
          ) return n;
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
