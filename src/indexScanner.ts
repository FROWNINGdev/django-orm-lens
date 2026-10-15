import * as vscode from 'vscode';
import { scanWorkspace } from './parser';
import { WorkspaceIndex } from './types';

/** What the scanner pushes results into; wired up in `activate`. */
export interface ScanTargets {
  setIndex(index: WorkspaceIndex): void;
  refreshCodeLens(): void;
  statusItem: vscode.StatusBarItem;
  outputChannel: vscode.OutputChannel;
}

const DEFAULT_EXCLUDES = [
  '**/migrations/**',
  '**/node_modules/**',
  '**/venv/**',
  '**/.venv/**',
  '**/env/**',
];

function getExcludeGlobs(): string[] {
  return vscode.workspace
    .getConfiguration('ormSynapse')
    .get<string[]>('excludeGlobs', DEFAULT_EXCLUDES);
}

/**
 * Owns the workspace index: scanning (coalesced, latest-scan-wins) and the
 * file watchers that trigger rescans.
 */
export class IndexScanner {
  index: WorkspaceIndex = { apps: [], scannedAt: 0 };
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange = this.changed.event;

  private generation = 0;
  private inFlight: Promise<void> | null = null;
  private queued = false;
  private modelWatchers: vscode.FileSystemWatcher[] = [];
  private watcherDisposables: vscode.Disposable[] = [];

  constructor(private readonly targets: ScanTargets) {}

  /** Fires `onDidChange`; exposed so callers can dispose the emitter. */
  get emitter(): vscode.EventEmitter<void> {
    return this.changed;
  }

  private async doScan(): Promise<void> {
    const { statusItem, outputChannel } = this.targets;
    const myGen = ++this.generation;
    const before = Date.now();
    try {
      const next = await scanWorkspace(getExcludeGlobs());
      if (myGen !== this.generation) return;
      this.index = next;
      this.targets.setIndex(next);
      this.targets.refreshCodeLens();
      this.changed.fire();
      const total = next.apps.reduce((n, a) => n + a.models.length, 0);
      const took = Date.now() - before;
      statusItem.text = `$(database) ${total} model${total === 1 ? '' : 's'}`;
      statusItem.tooltip = `ORM Synapse — scanned in ${took}ms`;
      statusItem.show();
      // Signal viewsWelcome: the initial scan has completed. From now on the
      // "empty state" reads "no Django models found" instead of "scanning…".
      vscode.commands.executeCommand('setContext', 'ormSynapse.scanCompleted', true);
    } catch (err) {
      outputChannel.appendLine(
        `[scan #${myGen}] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
      );
      statusItem.text = '$(warning) ORM Synapse';
      statusItem.tooltip = 'Scan failed — see the ORM Synapse output channel';
      statusItem.show();
    }
  }

  refresh = async (): Promise<void> => {
    if (this.inFlight) {
      this.queued = true;
      return this.inFlight;
    }
    this.inFlight = (async () => {
      try {
        await this.doScan();
        while (this.queued) {
          this.queued = false;
          await this.doScan();
        }
      } finally {
        this.inFlight = null;
      }
    })();
    return this.inFlight;
  };

  setupWatcher(context: vscode.ExtensionContext): void {
    const autoRefresh = vscode.workspace
      .getConfiguration('ormSynapse')
      .get<boolean>('autoRefresh', true);
    this.dispose();
    if (!autoRefresh) return;
    // `**/models/*.py` is one level deep. `**/models/**/*.py` covers nested
    // packages such as `models/builders/flow.py`.
    const patterns = ['**/models.py', '**/models/*.py', '**/models/**/*.py'];
    this.modelWatchers = patterns.map((pattern) =>
      vscode.workspace.createFileSystemWatcher(pattern)
    );
    const trigger = () => {
      this.refresh().catch((err) =>
        this.targets.outputChannel.appendLine(
          `[watcher-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
        )
      );
    };
    for (const w of this.modelWatchers) {
      this.watcherDisposables.push(
        w.onDidChange(trigger),
        w.onDidCreate(trigger),
        w.onDidDelete(trigger),
      );
      context.subscriptions.push(w);
    }
  }

  dispose(): void {
    this.watcherDisposables.forEach((d) => d.dispose());
    this.watcherDisposables = [];
    for (const w of this.modelWatchers) w.dispose();
    this.modelWatchers = [];
  }
}
