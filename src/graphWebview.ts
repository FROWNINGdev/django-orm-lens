import * as vscode from 'vscode';
import { randomBytes } from 'crypto';
import { WorkspaceIndex } from './types';

const MERMAID_VERSION = '10.9.4';

function escapeLabel(s: string): string {
  return s.replace(/[^A-Za-z0-9_]/g, '_');
}

function buildMermaid(index: WorkspaceIndex): string {
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
        lines.push(
          `  ${escapeLabel(model.name)} ${arrow} ${escapeLabel(target)} : "${f.name}"`
        );
      }
    }
  }

  return lines.join('\n');
}

function html(mermaidSource: string, cspSource: string, nonce: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src ${cspSource} 'nonce-${nonce}' https://cdn.jsdelivr.net; font-src ${cspSource} https:; img-src ${cspSource} data:;">
<title>Django ORM Lens — ER Diagram</title>
<style>
  html, body { margin: 0; padding: 0; background: var(--vscode-editor-background); color: var(--vscode-editor-foreground); font-family: var(--vscode-font-family); }
  header { padding: 12px 16px; border-bottom: 1px solid var(--vscode-panel-border); display:flex; justify-content: space-between; align-items:center; gap: 12px; }
  header h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: 0.02em; }
  header .stats { font-size: 12px; opacity: 0.7; margin-left: auto; }
  header button {
    background: var(--vscode-button-background); color: var(--vscode-button-foreground);
    border: none; padding: 6px 12px; border-radius: 4px; font-size: 12px;
    cursor: pointer; font-family: inherit;
  }
  header button:hover { background: var(--vscode-button-hoverBackground); }
  .diagram-wrap { padding: 16px; overflow: auto; }
  pre.mermaid { background: transparent; }
</style>
</head>
<body>
  <header>
    <h1>Django ORM Lens — ER Diagram</h1>
    <button id="export-svg" title="Save the diagram as an SVG file">Export SVG</button>
    <span class="stats" id="stats"></span>
  </header>
  <div class="diagram-wrap">
    <pre class="mermaid" id="d">${mermaidSource.replace(/</g, '&lt;')}</pre>
  </div>
  <script nonce="${nonce}" src="https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js"></script>
  <script nonce="${nonce}">
    (function(){
      const vscode = acquireVsCodeApi();
      try {
        mermaid.initialize({ startOnLoad: true, theme: 'dark', securityLevel: 'strict' });
      } catch (e) {
        document.getElementById('d').textContent = 'Mermaid failed to load: ' + e.message;
        return;
      }
      document.getElementById('export-svg').addEventListener('click', () => {
        const svg = document.querySelector('#d svg');
        if (!svg) {
          vscode.postMessage({ type: 'export-error', message: 'Diagram has not rendered yet.' });
          return;
        }
        const clone = svg.cloneNode(true);
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        const serializer = new XMLSerializer();
        const source = '<?xml version="1.0" encoding="UTF-8"?>\\n' + serializer.serializeToString(clone);
        vscode.postMessage({ type: 'export-svg', payload: source });
      });
    })();
  </script>
</body>
</html>`;
}

function makeNonce(): string {
  return randomBytes(24).toString('base64').replace(/[^A-Za-z0-9]/g, '');
}

async function saveSvg(svg: string): Promise<void> {
  const defaultUri = vscode.workspace.workspaceFolders?.[0]?.uri;
  const target = await vscode.window.showSaveDialog({
    title: 'Export ER Diagram as SVG',
    defaultUri: defaultUri
      ? vscode.Uri.joinPath(defaultUri, 'django-orm-diagram.svg')
      : undefined,
    filters: { 'SVG Image': ['svg'] },
  });
  if (!target) return;
  await vscode.workspace.fs.writeFile(target, Buffer.from(svg, 'utf-8'));
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

export function showGraph(context: vscode.ExtensionContext, index: WorkspaceIndex) {
  const mermaidSource = buildMermaid(index);
  if (panel) {
    panel.webview.html = html(mermaidSource, panel.webview.cspSource, makeNonce());
    panel.reveal(vscode.ViewColumn.Beside);
    return;
  }
  panel = vscode.window.createWebviewPanel(
    'djangoOrmLensGraph',
    'Django ORM Lens — ER Diagram',
    vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  panel.webview.html = html(mermaidSource, panel.webview.cspSource, makeNonce());
  panel.webview.onDidReceiveMessage(
    async (msg: { type: string; payload?: string; message?: string }) => {
      if (msg.type === 'export-svg' && typeof msg.payload === 'string') {
        try {
          await saveSvg(msg.payload);
        } catch (err) {
          vscode.window.showErrorMessage(
            `Could not save SVG: ${err instanceof Error ? err.message : String(err)}`
          );
        }
      } else if (msg.type === 'export-error') {
        vscode.window.showWarningMessage(`Export failed: ${msg.message ?? 'unknown'}`);
      }
    },
    null,
    context.subscriptions
  );
  panel.onDidDispose(() => {
    panel = undefined;
  }, null, context.subscriptions);
}
