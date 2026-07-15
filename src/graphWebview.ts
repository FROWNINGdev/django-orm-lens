import * as vscode from 'vscode';
import * as path from 'path';
import { randomBytes } from 'crypto';
import { WorkspaceIndex } from './types';

// Kept exported for CLI parity — the Python side still emits Mermaid, and
// downstream tests import this symbol.
function escapeLabel(s: string): string {
  return s.replace(/[^A-Za-z0-9_]/g, '_');
}

export function buildMermaid(index: WorkspaceIndex): string {
  const lines: string[] = ['erDiagram'];
  const modelNames = new Set<string>();
  for (const app of index.apps) {
    for (const model of app.models) {
      modelNames.add(model.name);
    }
  }

  for (const app of index.apps) {
    for (const model of app.models) {
      const safe = escapeLabel(model.name);
      lines.push(`  ${safe} {`);
      for (const f of model.fields) {
        if (f.isRelation) continue;
        const type = f.type.replace(/[^A-Za-z0-9]/g, '');
        const name = f.name.replace(/[^A-Za-z0-9_]/g, '_');
        lines.push(`    ${type} ${name}`);
      }
      lines.push('  }');
    }
  }

  for (const app of index.apps) {
    for (const model of app.models) {
      for (const f of model.fields) {
        if (!f.isRelation || !f.relatedModel) continue;
        const target =
          f.relatedModel === 'self' ? model.name : f.relatedModel.split('.').pop()!;
        if (!modelNames.has(target)) continue;
        const arrow =
          f.relationKind === 'ManyToManyField'
            ? '}o--o{'
            : f.relationKind === 'OneToOneField'
            ? '||--||'
            : '}o--||';
        const sanitizeLabel = (s: string) => s.replace(/[^A-Za-z0-9_.\- ]/g, '_');
        const parts: string[] = [sanitizeLabel(f.name)];
        if (f.onDelete) parts.push(sanitizeLabel(f.onDelete));
        if (f.throughModel) parts.push(`through ${sanitizeLabel(f.throughModel)}`);
        if (f.relatedName) parts.push(`as ${sanitizeLabel(f.relatedName)}`);
        const label = parts.length > 1
          ? `${parts[0]} [${parts.slice(1).join(', ')}]`
          : parts[0];
        lines.push(
          `  ${escapeLabel(model.name)} ${arrow} ${escapeLabel(target)} : "${label}"`
        );
      }
    }
  }

  return lines.join('\n');
}

function resolveTheme(): 'dark' | 'light' {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  const raw = cfg.get<string>('diagramTheme', 'auto');
  if (raw === 'default' || raw === 'forest' || raw === 'neutral') return 'light';
  if (raw === 'dark') return 'dark';
  const kind = vscode.window.activeColorTheme.kind;
  return kind === vscode.ColorThemeKind.Light ||
    kind === vscode.ColorThemeKind.HighContrastLight
    ? 'light'
    : 'dark';
}

function buildIndexPayload(index: WorkspaceIndex): Record<string, unknown> {
  const workspaceName =
    vscode.workspace.workspaceFolders?.[0]?.name ??
    (vscode.workspace.name ? vscode.workspace.name : 'workspace');
  return {
    apps: index.apps.map((app) => ({
      name: app.name,
      path: app.path,
      models: app.models.map((m) => ({
        name: m.name,
        appName: m.appName,
        filePath: m.filePath,
        lineNumber: m.lineNumber,
        fields: m.fields.map((f) => ({
          name: f.name,
          type: f.type,
          isRelation: f.isRelation,
          relatedModel: f.relatedModel,
          relationKind: f.relationKind,
          onDelete: f.onDelete,
          relatedName: f.relatedName,
          throughModel: f.throughModel,
          lineNumber: f.lineNumber,
        })),
      })),
    })),
    scannedAt: index.scannedAt,
    workspaceName,
    theme: resolveTheme(),
  };
}

function html(
  cspSource: string,
  nonce: string,
  scriptUri: string,
  initialPayload: Record<string, unknown>
): string {
  const serialised = JSON.stringify(initialPayload)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src ${cspSource} 'nonce-${nonce}'; font-src ${cspSource} data:; img-src ${cspSource} data:;">
<title>Django ORM Lens — ER Diagram</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); font-family: var(--vscode-font-family); }
  #dol-root { height: 100vh; width: 100vw; }
  #dol-fallback { padding: 24px; font-size: 13px; opacity: 0.75; }
</style>
</head>
<body>
  <div id="dol-root">
    <div id="dol-fallback">Loading ER diagram…</div>
  </div>
  <script nonce="${nonce}">
    window.__INITIAL_INDEX__ = ${serialised};
  </script>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
}

function makeNonce(): string {
  return randomBytes(24).toString('base64').replace(/[^A-Za-z0-9]/g, '');
}

async function saveExport(
  format: 'png' | 'svg',
  dataUrl: string
): Promise<void> {
  const defaultUri = vscode.workspace.workspaceFolders?.[0]?.uri;
  const target = await vscode.window.showSaveDialog({
    title: `Export ER Diagram as ${format.toUpperCase()}`,
    defaultUri: defaultUri
      ? vscode.Uri.joinPath(defaultUri, `django-orm-diagram.${format}`)
      : undefined,
    filters:
      format === 'png'
        ? { 'PNG Image': ['png'] }
        : { 'SVG Image': ['svg'] },
  });
  if (!target) return;
  const comma = dataUrl.indexOf(',');
  const bytes =
    comma >= 0 && dataUrl.startsWith('data:')
      ? Buffer.from(dataUrl.slice(comma + 1), 'base64')
      : Buffer.from(dataUrl, 'utf-8');
  await vscode.workspace.fs.writeFile(target, bytes);
  const open = 'Open File';
  const choice = await vscode.window.showInformationMessage(
    `Saved to ${target.fsPath}`,
    open
  );
  if (choice === open) {
    await vscode.commands.executeCommand('vscode.open', target);
  }
}

let panel: vscode.WebviewPanel | undefined;
let currentIndex: WorkspaceIndex | undefined;

function renderInto(context: vscode.ExtensionContext, target: vscode.WebviewPanel) {
  const scriptFileUri = vscode.Uri.joinPath(
    context.extensionUri,
    'media',
    'webview',
    'graph.js'
  );
  const scriptUri = target.webview.asWebviewUri(scriptFileUri).toString();
  const payload = currentIndex
    ? buildIndexPayload(currentIndex)
    : { apps: [], scannedAt: 0, theme: resolveTheme() };
  target.webview.html = html(target.webview.cspSource, makeNonce(), scriptUri, payload);
}

export function showGraph(context: vscode.ExtensionContext, index: WorkspaceIndex) {
  currentIndex = index;
  if (panel) {
    renderInto(context, panel);
    panel.reveal(vscode.ViewColumn.Beside);
    // Also push over messaging so an already-open panel updates without a full reload.
    panel.webview.postMessage({ type: 'index', payload: buildIndexPayload(index) });
    return;
  }
  panel = vscode.window.createWebviewPanel(
    'djangoOrmLensGraph',
    'Django ORM Lens — ER Diagram',
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')],
    }
  );
  renderInto(context, panel);

  const msgHandler = panel.webview.onDidReceiveMessage(
    async (msg: {
      type: string;
      filePath?: string;
      lineNumber?: number;
      format?: 'png' | 'svg';
      payload?: string;
    }) => {
      if (!panel) return;
      if (msg.type === 'ready') {
        if (currentIndex) {
          panel.webview.postMessage({
            type: 'index',
            payload: buildIndexPayload(currentIndex),
          });
        }
        return;
      }
      if (
        msg.type === 'jumpToModel' &&
        typeof msg.filePath === 'string' &&
        typeof msg.lineNumber === 'number'
      ) {
        try {
          const uri = vscode.Uri.file(msg.filePath);
          if (!vscode.workspace.getWorkspaceFolder(uri)) {
            throw new Error('target path is outside the current workspace');
          }
          const doc = await vscode.workspace.openTextDocument(uri);
          const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
          const pos = new vscode.Position(Math.max(0, msg.lineNumber | 0), 0);
          editor.selection = new vscode.Selection(pos, pos);
          editor.revealRange(
            new vscode.Range(pos, pos),
            vscode.TextEditorRevealType.InCenter
          );
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          vscode.window.showWarningMessage(
            `Django ORM Lens: could not open ${path.basename(msg.filePath)}: ${message}`
          );
        }
        return;
      }
      if (
        msg.type === 'export' &&
        (msg.format === 'png' || msg.format === 'svg') &&
        typeof msg.payload === 'string'
      ) {
        try {
          await saveExport(msg.format, msg.payload);
        } catch (err) {
          vscode.window.showErrorMessage(
            `Could not save ${msg.format.toUpperCase()}: ${err instanceof Error ? err.message : String(err)}`
          );
        }
        return;
      }
    }
  );

  panel.onDidDispose(() => {
    msgHandler.dispose();
    panel = undefined;
  });
}
