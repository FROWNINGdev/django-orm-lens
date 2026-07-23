export type RelationKind = 'ForeignKey' | 'ManyToManyField' | 'OneToOneField';

export interface ParsedField {
  name: string;
  type: string;
  args: string;
  isRelation: boolean;
  relatedModel?: string;
  relationKind?: RelationKind;
  onDelete?: string;
  relatedName?: string;
  throughModel?: string;
  lineNumber: number;
}

export interface ParsedModel {
  name: string;
  appName: string;
  filePath: string;
  lineNumber: number;
  fields: ParsedField[];
  meta: Record<string, string>;
  baseClasses: string[];
}

export interface ParsedApp {
  name: string;
  path: string;
  models: ParsedModel[];
}

export interface WorkspaceIndex {
  apps: ParsedApp[];
  scannedAt: number;
}

export type NodeKind = 'app' | 'model' | 'field' | 'meta' | 'metaItem';

export interface TreeNode {
  /**
   * Stable identity across refreshes. VS Code uses this to preserve which
   * tree items are expanded when the provider fires onDidChangeTreeData.
   * Format: `${appName}[/${modelName}[/${fieldOrMetaName}]]`.
   */
  id: string;
  kind: NodeKind;
  label: string;
  description?: string;
  /** Free-text tooltip. Rendered as MarkdownString when `tooltipMarkdown` is set. */
  tooltip?: string;
  /**
   * Optional richer tooltip rendered as Markdown, with clickable `command:`
   * deep-links. Requires `isTrusted = true` on the MarkdownString.
   */
  tooltipMarkdown?: string;
  filePath?: string;
  lineNumber?: number;
  children?: TreeNode[];
  iconId?: string;
  /** Optional narrower context value — e.g. `field.fk` — for right-click gating. */
  contextValue?: string;
  /**
   * Optional synthetic URI (scheme `djangoOrmLens:`) whose query encodes a
   * decoration flag consumed by `FileDecorationProvider`. Set on nodes we
   * want visually badged (e.g. FK without on_delete → red `!`).
   */
  resourceUriString?: string;
}
