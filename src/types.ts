export type RelationKind = 'ForeignKey' | 'ManyToManyField' | 'OneToOneField';

export interface ParsedField {
  name: string;
  type: string;
  args: string;
  isRelation: boolean;
  relatedModel?: string;
  relationKind?: RelationKind;
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
  kind: NodeKind;
  label: string;
  description?: string;
  tooltip?: string;
  filePath?: string;
  lineNumber?: number;
  children?: TreeNode[];
  iconId?: string;
}
