import * as vscode from 'vscode';
import { WorkspaceIndex } from './types';

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
  header { padding: 12px 16px; border-bottom: 1px solid var(--vscode-panel-border); display:flex; justify-content: space-between; align-items:center; }
  header h1 { font-size: 14px; margin: 0; font-weight: 600; letter-spacing: 0.02em; }
  header .stats { font-size: 12px; opacity: 0.7; }
  .diagram-wrap { padding: 16px; overflow: auto; }
  pre.mermaid { background: transparent; }
</style>
</head>
<body>
  <header>
    <h1>Django ORM Lens — ER Diagram</h1>
    <span class="stats" id="stats"></span>
  </header>
  <div class="diagram-wrap">
    <pre class="mermaid" id="d">${mermaidSource.replace(/</g, '&lt;')}</pre>
  </div>
  <script nonce="${nonce}" src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script nonce="${nonce}">
    (function(){
      try {
        mermaid.initialize({ startOnLoad: true, theme: 'dark', securityLevel: 'strict' });
      } catch (e) {
        document.getElementById('d').textContent = 'Mermaid failed to load: ' + e.message;
      }
    })();
  </script>
</body>
</html>`;
}

function makeNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let out = '';
  for (let i = 0; i < 32; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
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
  panel.onDidDispose(() => {
    panel = undefined;
  }, null, context.subscriptions);
}
