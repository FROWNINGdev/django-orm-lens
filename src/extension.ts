import * as vscode from 'vscode';
import { findUserModel, resolveRelatedTail, scanWorkspace } from './parser';
import { DjangoTreeProvider } from './treeProvider';
import { showGraph } from './graphWebview';
import { DjangoHoverProvider } from './hoverProvider';
import { DjangoCodeLensProvider } from './codeLensProvider';
import { registerCodeFixes } from './codeActionProvider';
import { DjangoTreeDecorationProvider } from './decorations';
import { generateFactoryCode } from './factoryGenerator';
import { BlobCache, blobShaFor, gitLogFollow, gitShowFile } from './git';
import { Finding, scanImpact } from './impactAnalysis';
import { generateQueryTemplates } from './queryGen';
import { DIAGNOSTIC_SOURCE } from './rules';
import { diffSchemas, diffToMarkdown } from './schemaDiff';
import { TreeNode, WorkspaceIndex } from './types';
import { parseModelsFile } from './parser';

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
    // Signal viewsWelcome: the initial scan has completed. From now on the
    // "empty state" reads "no Django models found" instead of "scanning…".
    vscode.commands.executeCommand(
      'setContext',
      'djangoOrmLens.scanCompleted',
      true,
    );
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

let watcherDisposables: vscode.Disposable[] = [];

function setupWatcher(context: vscode.ExtensionContext) {
  const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
  const autoRefresh = cfg.get<boolean>('autoRefresh', true);
  watcherDisposables.forEach((d) => d.dispose());
  watcherDisposables = [];
  watcher?.dispose();
  watcher = undefined;
  if (!autoRefresh) return;
  watcher = vscode.workspace.createFileSystemWatcher('**/models.py');
  const watcherSplit = vscode.workspace.createFileSystemWatcher('**/models/*.py');
  const trigger = () => {
    refresh().catch((err) =>
      outputChannel.appendLine(
        `[watcher-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
      )
    );
  };
  watcherDisposables.push(
    watcher.onDidChange(trigger),
    watcher.onDidCreate(trigger),
    watcher.onDidDelete(trigger),
    watcherSplit.onDidChange(trigger),
    watcherSplit.onDidCreate(trigger),
    watcherSplit.onDidDelete(trigger),
  );
  context.subscriptions.push(watcher, watcherSplit);
}

export async function activate(context: vscode.ExtensionContext) {
  treeProvider = new DjangoTreeProvider(context.workspaceState);
  outputChannel = vscode.window.createOutputChannel('Django ORM Lens');
  context.subscriptions.push(outputChannel);
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = 'djangoOrmLens.showGraph';
  context.subscriptions.push(statusItem);

  const treeView = vscode.window.createTreeView('djangoOrmLens.models', {
    treeDataProvider: treeProvider,
  });
  context.subscriptions.push(treeView);

  // File decorations — badge letters `!` / `~` on field rows whose Django
  // kwargs trip DOL011/013/014/015 patterns. Matches how the built-in Git
  // integration surfaces `M` / `U` / `D` on Explorer files.
  const decorationProvider = new DjangoTreeDecorationProvider();
  context.subscriptions.push(
    vscode.window.registerFileDecorationProvider(decorationProvider)
  );

  // Re-scan when the sidebar becomes visible. Covers the case where the
  // extension activated via `onStartupFinished` before the workspace file
  // index was ready (findFiles returns empty), and the tree only pops
  // open later when the user clicks the icon.
  context.subscriptions.push(
    treeView.onDidChangeVisibility((e) => {
      if (e.visible && currentIndex.apps.length === 0) {
        refresh().catch((err) =>
          outputChannel.appendLine(
            `[visibility-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
    })
  );

  // Activity-bar badge: passive count of Django ORM Lens findings.
  // GitHub PRs / Docker style — user glances at the icon and knows what's
  // outstanding without opening the view. Dot when unknown, number when > 0.
  const updateBadge = () => {
    let n = 0;
    for (const [, diags] of vscode.languages.getDiagnostics()) {
      for (const d of diags) {
        if (d.source === DIAGNOSTIC_SOURCE) n++;
      }
    }
    treeView.badge = n === 0
      ? undefined
      : {
          value: n,
          tooltip: `${n} Django ORM Lens issue${n === 1 ? '' : 's'}`,
        };
  };
  updateBadge();
  context.subscriptions.push(
    vscode.languages.onDidChangeDiagnostics(() => updateBadge())
  );

  // Reveal the matching model node when the user activates a models.py file.
  // Mirrors GitLens' "sidebar follows the editor" pattern — praised by
  // reviewers as "it always knows where I am." Guarded on visibility so we
  // never fight the user when they've focused a different view.
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor || !treeView.visible) return;
      const path = editor.document.uri.fsPath;
      const node = treeProvider.findModelNodeByPath(path);
      if (!node) return;
      treeView
        .reveal(node, { select: false, focus: false, expand: 1 })
        .then(undefined, () => {
          /* reveal can reject if the node was refreshed away; ignore */
        });
    })
  );

  // Re-scan when workspace folders change (folder add/remove/open).
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      refresh().catch((err) =>
        outputChannel.appendLine(
          `[workspace-folders-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
        )
      );
    })
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

  // v0.8 · WOW-feature #3 from Discussion #27 — static-analysis QuickFixes:
  // `.count() > 0` -> `.exists()`, `.first() is None` -> `not .exists()`,
  // and N+1 attribute-access-in-loop diagnostics. Feature-flagged via
  // djangoOrmLens.codeFixes.enabled (default true).
  for (const d of registerCodeFixes(context)) {
    context.subscriptions.push(d);
  }

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

  // v0.8 · WOW-feature #2 from Discussion #27 — interactive query builder.
  // Right-click a field/model in the sidebar → pick a template → snippet
  // is inserted at the cursor (when an editor is active) or opened in a
  // fresh untitled buffer. Grammar-aware: FK gets .select_related,
  // M2M gets .prefetch_related, reverse FK gets Count() annotation.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'djangoOrmLens.buildQuery',
      async (arg?: TreeNode) => {
        if (currentIndex.apps.length === 0) await refresh();
        let target: Parameters<typeof generateQueryTemplates>[0] | undefined;
        if (arg && typeof arg === 'object' && 'kind' in arg) {
          if (arg.kind === 'model') {
            const [appName, modelName] = arg.id.split('/');
            if (appName && modelName)
              target = { kind: 'model', appName, modelName };
          } else if (arg.kind === 'field') {
            const [appName, modelName, fieldName] = arg.id.split('/');
            if (appName && modelName && fieldName)
              target = { kind: 'field', appName, modelName, fieldName };
          }
        }
        if (!target) {
          const picks = currentIndex.apps.flatMap((app) =>
            app.models.flatMap((m) => [
              {
                label: `$(symbol-class) ${app.name}.${m.name}`,
                description: 'model',
                target: { kind: 'model' as const, appName: app.name, modelName: m.name },
              },
              ...m.fields.map((f) => ({
                label: `$(symbol-field) ${app.name}.${m.name}.${f.name}`,
                description: f.type,
                target: {
                  kind: 'field' as const,
                  appName: app.name,
                  modelName: m.name,
                  fieldName: f.name,
                },
              })),
            ])
          );
          const chosen = await vscode.window.showQuickPick(picks, {
            title: 'Django ORM Lens — Query Builder',
            placeHolder: 'Pick a target field or model',
          });
          if (!chosen) return;
          target = chosen.target;
        }

        const templates = generateQueryTemplates(target, currentIndex);
        if (templates.length === 0) {
          vscode.window.showInformationMessage(
            'Django ORM Lens: no templates apply to this target.',
          );
          return;
        }
        const chosen = await vscode.window.showQuickPick(
          templates.map((t) => ({
            label: t.title,
            description: t.description,
            detail: t.category,
            template: t,
          })),
          {
            title: 'Pick a Query Template',
            placeHolder: 'Filter → perf → aggregate → projection',
            matchOnDescription: true,
          },
        );
        if (!chosen) return;

        const editor = vscode.window.activeTextEditor;
        const snippetString = new vscode.SnippetString(chosen.template.snippet);
        if (editor && editor.document.languageId === 'python') {
          await editor.insertSnippet(snippetString);
          return;
        }
        // No active Python editor — open a fresh untitled buffer.
        const modelName =
          target.kind === 'model' ? target.modelName : target.modelName;
        const boiler = [
          `# Django ORM Lens — Query Builder scratch`,
          `# from ${
            currentIndex.apps.find((a) =>
              a.models.some((m) => m.name === modelName),
            )?.name ?? 'app'
          }.models import ${modelName}`,
          '',
          '',
        ].join('\n');
        const doc = await vscode.workspace.openTextDocument({
          content: boiler,
          language: 'python',
        });
        const openedEditor = await vscode.window.showTextDocument(doc, {
          preview: false,
        });
        await openedEditor.insertSnippet(snippetString);
      },
    ),
  );

  // v0.8 · WOW-feature #1 from Discussion #27 — impact analysis.
  // Right-click a field or model in the sidebar → "What breaks if I remove
  // this?" scan across models/serializers/forms/admin/views/urls/templates/
  // tests/migrations. Findings surface as a QuickPick grouped by layer with
  // Certain/Likely/Possibly confidence badges; picking one jumps there.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'djangoOrmLens.findImpact',
      async (arg?: TreeNode | string) => {
        if (currentIndex.apps.length === 0) await refresh();
        let needle: string | undefined;
        let skipFiles: string[] = [];
        if (typeof arg === 'string') {
          needle = arg;
        } else if (arg && typeof arg === 'object' && 'kind' in arg) {
          if (arg.kind === 'model' || arg.kind === 'field') {
            needle = arg.label;
            if (arg.filePath) skipFiles = [arg.filePath];
          }
        }
        if (!needle) {
          const picks = currentIndex.apps.flatMap((app) =>
            app.models.flatMap((m) => [
              {
                label: `$(symbol-class) ${app.name}.${m.name}`,
                description: 'model',
                needle: m.name,
                filePath: m.filePath,
              },
              ...m.fields.map((f) => ({
                label: `$(symbol-field) ${app.name}.${m.name}.${f.name}`,
                description: f.type,
                needle: f.name,
                filePath: m.filePath,
              })),
            ])
          );
          const chosen = await vscode.window.showQuickPick(picks, {
            title: 'Django ORM Lens — Impact Analysis',
            placeHolder: 'Pick a field or model to trace',
          });
          if (!chosen) return;
          needle = chosen.needle;
          if (chosen.filePath) skipFiles = [chosen.filePath];
        }

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `Django ORM Lens: scanning references to '${needle}'…`,
            cancellable: true,
          },
          async (_progress, token) => {
            const findings = await scanImpact(needle!, { skipFiles, token });
            if (findings.length === 0) {
              vscode.window.showInformationMessage(
                `Django ORM Lens: no references to '${needle}' found across the workspace.`,
              );
              return;
            }
            const badge: Record<Finding['confidence'], string> = {
              certain: '$(check)',
              likely: '$(circle-filled)',
              possibly: '$(circle-outline)',
            };
            const items = findings.map((f) => ({
              label: `${badge[f.confidence]} ${f.snippet}`,
              description: `${f.layer} · ${f.confidence}`,
              detail: `${vscode.workspace.asRelativePath(f.filePath)}:${f.line + 1} — ${f.reason}`,
              finding: f,
            }));
            const chosen = await vscode.window.showQuickPick(items, {
              title: `Impact of '${needle}' — ${findings.length} reference${
                findings.length === 1 ? '' : 's'
              }`,
              placeHolder: 'Pick a reference to jump to',
              matchOnDescription: true,
              matchOnDetail: true,
            });
            if (!chosen) return;
            const uri = vscode.Uri.file(chosen.finding.filePath);
            const doc = await vscode.workspace.openTextDocument(uri);
            const editor = await vscode.window.showTextDocument(doc);
            const pos = new vscode.Position(chosen.finding.line, chosen.finding.column);
            editor.selection = new vscode.Selection(pos, pos);
            editor.revealRange(
              new vscode.Range(pos, pos),
              vscode.TextEditorRevealType.InCenter,
            );
          },
        );
      },
    ),
  );

  // v0.8 · WOW-feature #5 from Discussion #27 — time-travel schema diff.
  // Pick a `models.py`, pick two commits, get a typed diff rendered as
  // markdown into an untitled buffer. Blueprint cited to Atlas + Prisma
  // migrate diff; caching keyed on blob SHA (not commit SHA) so history
  // walks with no models.py churn are effectively free.
  const blobCache = new BlobCache<
    Awaited<ReturnType<typeof parseModelsFile>>
  >(50);
  context.subscriptions.push(
    vscode.commands.registerCommand('djangoOrmLens.showDiff', async () => {
      if (currentIndex.apps.length === 0) await refresh();
      const modelsFiles = [
        ...new Set(
          currentIndex.apps.flatMap((a) => a.models.map((m) => m.filePath)),
        ),
      ];
      if (modelsFiles.length === 0) {
        vscode.window.showInformationMessage(
          'Django ORM Lens: no models.py found — scan a Django project first.',
        );
        return;
      }
      let target = modelsFiles[0];
      if (modelsFiles.length > 1) {
        const pick = await vscode.window.showQuickPick(
          modelsFiles.map((p) => ({ label: p, description: 'models.py' })),
          { title: 'Django ORM Lens — schema diff', placeHolder: 'Pick a models.py' },
        );
        if (!pick) return;
        target = pick.label;
      }
      const wsFolder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(target));
      if (!wsFolder) {
        vscode.window.showWarningMessage(
          'Django ORM Lens: file is outside the current workspace.',
        );
        return;
      }
      const cwd = wsFolder.uri.fsPath;

      let commits;
      try {
        commits = await gitLogFollow(cwd, target, 200);
      } catch (err) {
        vscode.window.showWarningMessage(
          `Django ORM Lens: git log failed — is this a git repo? (${
            err instanceof Error ? err.message : String(err)
          })`,
        );
        return;
      }
      if (commits.length < 2) {
        vscode.window.showInformationMessage(
          'Django ORM Lens: need at least 2 commits touching this file for a diff.',
        );
        return;
      }
      const items = commits.map((c) => ({
        label: `$(git-commit) ${c.sha.slice(0, 8)}  ${c.subject.slice(0, 60)}`,
        description: new Date(c.ct * 1000).toISOString(),
        sha: c.sha,
      }));
      const fromPick = await vscode.window.showQuickPick(items, {
        title: 'From commit (older)',
        placeHolder: 'Base of the comparison',
      });
      if (!fromPick) return;
      const toPick = await vscode.window.showQuickPick(items, {
        title: 'To commit (newer)',
        placeHolder: 'Head of the comparison',
      });
      if (!toPick) return;

      const parseCommit = async (sha: string) => {
        const blobSha = await blobShaFor(cwd, sha, target);
        if (blobSha) {
          const cached = blobCache.get(blobSha);
          if (cached) return cached;
        }
        const source = await gitShowFile(cwd, sha, target);
        const models = parseModelsFile(target, source);
        if (blobSha) blobCache.set(blobSha, models);
        return models;
      };

      let oldModels, newModels;
      try {
        [oldModels, newModels] = await Promise.all([
          parseCommit(fromPick.sha),
          parseCommit(toPick.sha),
        ]);
      } catch (err) {
        vscode.window.showWarningMessage(
          `Django ORM Lens: could not read historical models.py (${
            err instanceof Error ? err.message : String(err)
          })`,
        );
        return;
      }

      const events = diffSchemas(oldModels, newModels);
      const header = [
        `# Django ORM Lens — Schema Diff`,
        '',
        `**From:** \`${fromPick.sha.slice(0, 8)}\` — ${new Date(
          commits.find((c) => c.sha === fromPick.sha)!.ct * 1000,
        ).toISOString()}  `,
        `**To:** \`${toPick.sha.slice(0, 8)}\` — ${new Date(
          commits.find((c) => c.sha === toPick.sha)!.ct * 1000,
        ).toISOString()}  `,
        `**File:** \`${target}\``,
        '',
        `Copy the section below into your PR description.`,
        '',
      ].join('\n');
      const md = header + diffToMarkdown(events);
      const doc = await vscode.workspace.openTextDocument({
        content: md,
        language: 'markdown',
      });
      await vscode.window.showTextDocument(doc, { preview: false });
    }),
  );

  // v0.8 · WOW-feature #4 from Discussion #27 — factory_boy scaffolding.
  // The command accepts three shapes depending on where it's triggered:
  //   (a) from the CodeLens above a model class: (filePath, lineNumber)
  //   (b) from the sidebar right-click menu:    (TreeNode)
  //   (c) from the command palette (no args):   pick model via QuickPick
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'djangoOrmLens.generateFactory',
      async (arg1?: string | TreeNode, arg2?: number) => {
        if (currentIndex.apps.length === 0) await refresh();
        let target: { filePath: string; lineNumber?: number; name?: string } | undefined;
        if (typeof arg1 === 'string' && typeof arg2 === 'number') {
          target = { filePath: arg1, lineNumber: arg2 };
        } else if (arg1 && typeof arg1 === 'object' && 'kind' in arg1 && arg1.kind === 'model') {
          target = { filePath: arg1.filePath ?? '', lineNumber: arg1.lineNumber, name: arg1.label };
        } else {
          const picks = currentIndex.apps.flatMap((app) =>
            app.models.map((m) => ({
              label: `$(symbol-class) ${app.name}.${m.name}`,
              description: `${m.fields.length} fields`,
              model: m,
            }))
          );
          const chosen = await vscode.window.showQuickPick(picks, {
            title: 'Generate factory_boy factory',
            placeHolder: 'Pick a Django model',
          });
          if (!chosen) return;
          target = {
            filePath: chosen.model.filePath,
            lineNumber: chosen.model.lineNumber,
            name: chosen.model.name,
          };
        }

        let model = currentIndex.apps
          .flatMap((a) => a.models)
          .find(
            (m) =>
              m.filePath === target!.filePath &&
              (target!.name ? m.name === target!.name : m.lineNumber === target!.lineNumber)
          );
        if (!model) {
          model = currentIndex.apps
            .flatMap((a) => a.models)
            .find((m) => m.filePath === target!.filePath);
        }
        if (!model) {
          vscode.window.showInformationMessage(
            'Django ORM Lens: no model matched — try Refresh and retry.'
          );
          return;
        }
        const source = generateFactoryCode(model, currentIndex);
        const doc = await vscode.workspace.openTextDocument({
          content: source,
          language: 'python',
        });
        await vscode.window.showTextDocument(doc, { preview: false });
      }
    )
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
    vscode.commands.registerCommand(
      'djangoOrmLens.findReverseRefs',
      async (node?: TreeNode) => {
        if (!node || node.kind !== 'model') {
          vscode.window.showInformationMessage(
            'Django ORM Lens: right-click a model in the sidebar to find reverse references.'
          );
          return;
        }
        const modelName = node.label;
        const inbound: {
          from: string;
          field: string;
          kind: string;
          onDelete: string;
        }[] = [];
        for (const app of currentIndex.apps) {
          for (const other of app.models) {
            if (
              other.name === modelName &&
              other.filePath === node.filePath
            ) {
              continue;
            }
            const userModelName = findUserModel(currentIndex)?.name;
            for (const f of other.fields) {
              if (!f.isRelation || !f.relatedModel) continue;
              // Resolve settings.AUTH_USER_MODEL so inbound edges to the
              // User model don't disappear from the reference panel.
              const tail = resolveRelatedTail(f.relatedModel, userModelName);
              if (tail === modelName) {
                inbound.push({
                  from: `${app.name}.${other.name}`,
                  field: f.name,
                  kind: f.relationKind ?? 'ForeignKey',
                  onDelete: f.onDelete ?? 'unknown',
                });
              }
            }
          }
        }
        if (inbound.length === 0) {
          vscode.window.showInformationMessage(
            `No models reference ${modelName}.`
          );
          return;
        }
        const items = inbound.map((r) => ({
          label: `${r.from}.${r.field}`,
          description: `${r.kind} · on_delete=${r.onDelete}`,
        }));
        await vscode.window.showQuickPick(items, {
          title: `Reverse references to ${modelName} (${inbound.length})`,
          placeHolder: 'Models that point at this one',
        });
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

  // Backstop: if the first scan happened before the workspace file index
  // was warm (common with `onStartupFinished` activation), try again once
  // after a short delay. Cheap — early-exits on the second scan if the
  // first one already populated results.
  if (currentIndex.apps.length === 0 && (vscode.workspace.workspaceFolders?.length ?? 0) > 0) {
    setTimeout(() => {
      if (currentIndex.apps.length === 0) {
        refresh().catch((err) =>
          outputChannel.appendLine(
            `[startup-retry] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
    }, 1500);
  }
}

export function deactivate() {
  watcher?.dispose();
  watcherDisposables.forEach((d) => d.dispose());
  watcherDisposables = [];
  statusItem?.dispose();
}
