import * as vscode from 'vscode';
import { scanWorkspace } from './parser';
import { DjangoTreeProvider } from './treeProvider';
import { showGraph } from './graphWebview';
import { DjangoHoverProvider } from './hoverProvider';
import { DjangoCodeLensProvider } from './codeLensProvider';
import { WorkspaceIndex } from './types';

let currentIndex: WorkspaceIndex = { apps: [], scannedAt: 0 };
let treeProvider: DjangoTreeProvider;
let codeLensProvider: DjangoCodeLensProvider;
let statusItem: vscode.StatusBarItem;
let watcher: vscode.FileSystemWatcher | undefined;
let outputChannel: vscode.OutputChannel;

let scanGeneration = 0;
let scanInFlight: Promise<void> | null = null;
let scanQueued = false;

function getExcludeGlobs(): string[] {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  return cfg.get<string[]>('excludeGlobs', [
    '**/migrations/**',
    '**/node_modules/**',
    '**/venv/**',
    '**/.venv/**',
    '**/env/**',
  ]);
}

async function doScan(): Promise<void> {
  const myGen = ++scanGeneration;
  const globs = getExcludeGlobs();
  const before = Date.now();
  try {
    const next = await scanWorkspace(globs);
    if (myGen !== scanGeneration) return;
    currentIndex = next;
    treeProvider.setIndex(currentIndex);
    codeLensProvider?.refresh();
    const total = currentIndex.apps.reduce((n, a) => n + a.models.length, 0);
    const took = Date.now() - before;
    statusItem.text = `$(database) ${total} model${total === 1 ? '' : 's'}`;
    statusItem.tooltip = `Django ORM Lens — scanned in ${took}ms`;
    statusItem.show();
  } catch (err) {
    outputChannel.appendLine(
      `[scan #${myGen}] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
    );
    statusItem.text = '$(warning) Django ORM Lens';
    statusItem.tooltip = 'Scan failed — see the Django ORM Lens output channel';
    statusItem.show();
  }
}

async function refresh(): Promise<void> {
  if (scanInFlight) {
    scanQueued = true;
    return scanInFlight;
  }
  scanInFlight = (async () => {
    try {
      await doScan();
      while (scanQueued) {
        scanQueued = false;
        await doScan();
      }
    } finally {
      scanInFlight = null;
    }
  })();
  return scanInFlight;
}

function setupWatcher(context: vscode.ExtensionContext) {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  const autoRefresh = cfg.get<boolean>('autoRefresh', true);
  watcher?.dispose();
  if (!autoRefresh) return;
  watcher = vscode.workspace.createFileSystemWatcher('**/models.py');
  const trigger = () => {
    refresh().catch((err) =>
      outputChannel.appendLine(
        `[watcher-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
      )
    );
  };
  watcher.onDidChange(trigger, null, context.subscriptions);
  watcher.onDidCreate(trigger, null, context.subscriptions);
  watcher.onDidDelete(trigger, null, context.subscriptions);
  context.subscriptions.push(watcher);
}

export async function activate(context: vscode.ExtensionContext) {
  treeProvider = new DjangoTreeProvider();
  outputChannel = vscode.window.createOutputChannel('Django ORM Lens');
  context.subscriptions.push(outputChannel);
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = 'djangoOrmLens.showGraph';
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('djangoOrmLens.models', treeProvider)
  );

  context.subscriptions.push(
    vscode.languages.registerHoverProvider(
      { language: 'python' },
      new DjangoHoverProvider(() => currentIndex)
    )
  );

  codeLensProvider = new DjangoCodeLensProvider(() => currentIndex);
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider({ language: 'python' }, codeLensProvider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('djangoOrmLens.refresh', async () => {
      await refresh();
      vscode.window.setStatusBarMessage('$(check) Django ORM Lens refreshed', 2000);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('djangoOrmLens.filter', async () => {
      const value = await vscode.window.showInputBox({
        prompt: 'Filter models and fields',
        placeHolder: 'e.g. User, order.status, ForeignKey',
        value: treeProvider.getFilter(),
      });
      if (value !== undefined) treeProvider.setFilter(value);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('djangoOrmLens.clearFilter', () => {
      treeProvider.setFilter('');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('djangoOrmLens.showGraph', async () => {
      if (currentIndex.apps.length === 0) await refresh();
      showGraph(context, currentIndex);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      'djangoOrmLens.jumpToModel',
      async (filePath: string, lineNumber: number) => {
        try {
          if (typeof filePath !== 'string' || typeof lineNumber !== 'number') {
            throw new Error('Invalid jump arguments');
          }
          const uri = vscode.Uri.file(filePath);
          if (!vscode.workspace.getWorkspaceFolder(uri)) {
            throw new Error('target path is outside the current workspace');
          }
          const doc = await vscode.workspace.openTextDocument(uri);
          const editor = await vscode.window.showTextDocument(doc);
          const pos = new vscode.Position(Math.max(0, lineNumber | 0), 0);
          editor.selection = new vscode.Selection(pos, pos);
          editor.revealRange(
            new vscode.Range(pos, pos),
            vscode.TextEditorRevealType.InCenter
          );
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          vscode.window.showWarningMessage(
            `Django ORM Lens: could not open ${filePath}. It may have been moved, deleted, or is outside the workspace. (${msg})`
          );
          refresh().catch((refreshErr) =>
            outputChannel.appendLine(
              `[jump-refresh] ${refreshErr instanceof Error ? refreshErr.stack ?? refreshErr.message : String(refreshErr)}`
            )
          );
        }
      }
    )
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('djangoOrmLens.autoRefresh')) setupWatcher(context);
      if (e.affectsConfiguration('djangoOrmLens.excludeGlobs')) {
        refresh().catch((err) =>
          outputChannel.appendLine(
            `[config-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
      if (e.affectsConfiguration('djangoOrmLens.showCodeLens')) {
        codeLensProvider?.refresh();
      }
    })
  );

  setupWatcher(context);
  await refresh();
}

export function deactivate() {
  watcher?.dispose();
  statusItem?.dispose();
}
