// Mirror of src/types.ts shape used inside the webview bundle.
// Duplicated (rather than imported) so the webview build stays self-contained
// and doesn't pull the extension's vscode-typed modules.

export type RelationKind = 'ForeignKey' | 'ManyToManyField' | 'OneToOneField';

export interface WireField {
  name: string;
  type: string;
  isRelation: boolean;
  relatedModel?: string;
  relationKind?: RelationKind;
  onDelete?: string;
  relatedName?: string;
  throughModel?: string;
  lineNumber: number;
}

export interface WireModel {
  name: string;
  appName: string;
  filePath: string;
  lineNumber: number;
  fields: WireField[];
}

export interface WireApp {
  name: string;
  path: string;
  models: WireModel[];
}

export interface WireIndex {
  apps: WireApp[];
  scannedAt: number;
  workspaceName?: string;
  theme: 'dark' | 'light';
}

export type ExtensionMessage =
  | { type: 'index'; payload: WireIndex }
  | { type: 'theme'; payload: 'dark' | 'light' };

export type WebviewMessage =
  | { type: 'jumpToModel'; filePath: string; lineNumber: number }
  | { type: 'export'; format: 'png' | 'svg'; payload: string }
  | { type: 'ready' };

// Minimal shape for VS Code's webview API surface we rely on.
export interface VsCodeApi {
  postMessage(msg: WebviewMessage): void;
  getState<T>(): T | undefined;
  setState<T>(state: T): void;
}

declare global {
  interface Window {
    acquireVsCodeApi: () => VsCodeApi;
    __INITIAL_INDEX__?: WireIndex;
  }
}
