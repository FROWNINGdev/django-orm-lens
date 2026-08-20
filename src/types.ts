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
  /**
   * Name of the abstract base this field was declared on, when it reached the
   * model through inheritance rather than its own body. Mirrors
   * `ParsedField.inherited_from` in the Python CLI.
   */
  inheritedFrom?: string;
}

export interface ParsedModel {
  name: string;
  appName: string;
  filePath: string;
  lineNumber: number;
  fields: ParsedField[];
  /**
   * Fields reaching this model from its **abstract** bases, parent-first, with
   * anything the model declares itself already removed.
   *
   * Kept separate from `fields` rather than merged into it, matching
   * `ParsedModel.inherited_fields` in the Python CLI: the sidebar and ER
   * diagram want to show where a column came from, and a diff wants to know
   * that an inherited column is not this model's to change.
   *
   * Only abstract bases contribute. A concrete base is multi-table
   * inheritance, where the parent keeps its own table and the child gains a
   * `parent_ptr` instead of copies of the columns — counting those here would
   * invent columns no migration will ever create.
   */
  inheritedFields: ParsedField[];
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
