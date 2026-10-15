import * as vscode from 'vscode';
import { findUserModel, modelNeighborhoodIds, resolveRelatedTail } from './parser';
import { DjangoTreeProvider } from './treeProvider';
import { isGraphOpen, showGraph } from './graphWebview';
import { maybeAskForStar } from './starPrompt';
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
import { IndexScanner } from './indexScanner';
import { completionsAt, lookupPathLength } from './ormCompletions';

/**
 * How far above the cursor completion looks for `qs = Post.objects.all()`.
 *
 * The backward scan stops at the enclosing `def` on its own, so this only
 * bounds the pathological case — a binding at module level with hundreds of
 * lines under it. Django view and manager bodies are far shorter than this.
 */
const LOOKBACK_LINES = 200;

let treeProvider: DjangoTreeProvider;
let codeLensProvider: DjangoCodeLensProvider | undefined;
let statusItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;
let scanner: IndexScanner;

export async function activate(context: vscode.ExtensionContext) {
  treeProvider = new DjangoTreeProvider(context.workspaceState);
  outputChannel = vscode.window.createOutputChannel('ORM Synapse');
  context.subscriptions.push(outputChannel);
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = 'ormSynapse.showGraph';
  context.subscriptions.push(statusItem);
  scanner = new IndexScanner({
    setIndex: (index) => treeProvider.setIndex(index),
    refreshCodeLens: () => codeLensProvider?.refresh(),
    statusItem,
    outputChannel,
  });

  const treeView = vscode.window.createTreeView('ormSynapse.models', {
    treeDataProvider: treeProvider,
    manageCheckboxStateManually: true,
  });
  context.subscriptions.push(treeView);

  // Unchecking an app or model hides it from the ER diagram, so huge schemas
  // can be narrowed to the part being worked on. VS Code batches the event, so
  // a single change may carry several items; the diagram is refreshed once
  // afterwards rather than per item.
  context.subscriptions.push(
    treeView.onDidChangeCheckboxState((e) => {
      for (const [node, state] of e.items) {
        treeProvider.setHidden(
          node.id,
          state === vscode.TreeItemCheckboxState.Unchecked
        );
      }
      if (isGraphOpen()) {
        // Full re-render rather than a postMessage push. The message channel
        // into the webview is not reliably reachable — measured: a legitimate
        // update arrived with `source` matching neither `window` nor
        // `window.parent`, so the webview's origin check dropped it. Until
        // that is understood, correctness beats smoothness: reassigning the
        // HTML always delivers the new state.
        showGraph(context, treeProvider.applyVisibility(scanner.index));
      }
    })
  );

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
      if (e.visible && scanner.index.apps.length === 0) {
        scanner.refresh().catch((err) =>
          outputChannel.appendLine(
            `[visibility-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
    })
  );

  // Activity-bar badge: passive count of ORM Synapse findings.
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
          tooltip: `${n} ORM Synapse issue${n === 1 ? '' : 's'}`,
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
      scanner.refresh().catch((err) =>
        outputChannel.appendLine(
          `[workspace-folders-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
        )
      );
    })
  );

  context.subscriptions.push(
    vscode.languages.registerHoverProvider(
      { language: 'python' },
      new DjangoHoverProvider(() => scanner.index)
    )
  );

  codeLensProvider = new DjangoCodeLensProvider(() => scanner.index);
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider({ language: 'python' }, codeLensProvider)
  );

  // #3 — field completion inside `Post.objects.filter(...)`. The provider is
  // a shell on purpose: every decision lives in `ormCompletions`, which knows
  // nothing about vscode and is therefore testable without a host.
  //
  // `_` is a trigger character alongside `(` and `,` because a lookup path is
  // written without ever leaving a word — VS Code would not re-query after
  // `author__` on its own, so traversal would appear only for users who
  // remembered to press Ctrl+Space.
  context.subscriptions.push(
    vscode.languages.registerCompletionItemProvider(
      { language: 'python' },
      {
        provideCompletionItems(document, position) {
          // Read per-request rather than captured at activation, so toggling
          // the setting takes effect without a window reload.
          if (
            !vscode.workspace
              .getConfiguration('ormSynapse')
              .get<boolean>('completions.enabled', true)
          ) {
            return [];
          }
          const linePrefix = document
            .lineAt(position.line)
            .text.slice(0, position.character);
          // Lines above the cursor let `qs = Post.objects.all()` on an earlier
          // line resolve `qs.filter(` here (#83). Bounded rather than the
          // whole file: the scan stops at the enclosing `def` anyway, and
          // reading an unbounded prefix on every keystroke in a 5000-line
          // views.py is work with no answer to show for it.
          const from = Math.max(0, position.line - LOOKBACK_LINES);
          const precedingLines: string[] = [];
          for (let i = from; i < position.line; i++) {
            precedingLines.push(document.lineAt(i).text);
          }
          const pathLength = lookupPathLength(linePrefix);
          return completionsAt(linePrefix, scanner.index, precedingLines).map((s) => {
            const item = new vscode.CompletionItem(
              s.label,
              s.kind === 'relation'
                ? vscode.CompletionItemKind.Reference
                : s.kind === 'lookup'
                  ? vscode.CompletionItemKind.Operator
                  : vscode.CompletionItemKind.Field
            );
            item.detail = s.detail;
            // The label carries the whole traversal path, so the range being
            // replaced has to start where that path starts. Left to its own
            // word-boundary logic VS Code replaces only the segment after the
            // last `__`, and `author__name` lands as `author__author__name`.
            item.range = new vscode.Range(
              position.with({ character: position.character - pathLength }),
              position
            );
            item.sortText = `${s.sortGroup}${s.label}`;
            return item;
          });
        },
      },
      '(',
      ',',
      '_'
    )
  );

  // v0.8 · WOW-feature #3 from Discussion #27 — static-analysis QuickFixes:
  // `.count() > 0` -> `.exists()`, `.first() is None` -> `not .exists()`,
  // and N+1 attribute-access-in-loop diagnostics. Feature-flagged via
  // ormSynapse.codeFixes.enabled (default true).
  context.subscriptions.push(scanner.emitter);
  for (const d of registerCodeFixes(context, () => scanner.index, scanner.onDidChange)) {
    context.subscriptions.push(d);
  }

  context.subscriptions.push(
    vscode.commands.registerCommand('ormSynapse.refresh', async () => {
      await scanner.refresh();
      vscode.window.setStatusBarMessage('$(check) ORM Synapse refreshed', 2000);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('ormSynapse.filter', async () => {
      const value = await vscode.window.showInputBox({
        prompt: 'Filter models and fields',
        placeHolder: 'e.g. User, order.status, ForeignKey',
        value: treeProvider.getFilter(),
      });
      if (value !== undefined) treeProvider.setFilter(value);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('ormSynapse.clearFilter', () => {
      treeProvider.setFilter('');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      'ormSynapse.showGraph',
      async (filePath?: unknown, lineNumber?: unknown) => {
      if (scanner.index.apps.length === 0) await scanner.refresh();
      const fromModel = typeof filePath === 'string' && typeof lineNumber === 'number';
      const focus = fromModel
        ? modelNeighborhoodIds(scanner.index, filePath, lineNumber)
        : undefined;
      // A class lens asks for that model and the models its relations point
      // at. The sidebar and command palette still open whatever is checked.
      showGraph(
        context,
        fromModel ? scanner.index : treeProvider.applyVisibility(scanner.index),
        focus
      );
      // Counted here rather than inside showGraph: this is the user asking
      // for a diagram, whereas showGraph also runs on sidebar refreshes the
      // user did not initiate. Not awaited — the prompt must never sit in
      // front of the panel it is thanking the user for opening.
      void maybeAskForStar(context);
    })
  );

  // v0.8 · WOW-feature #2 from Discussion #27 — interactive query builder.
  // Right-click a field/model in the sidebar → pick a template → snippet
  // is inserted at the cursor (when an editor is active) or opened in a
  // fresh untitled buffer. Grammar-aware: FK gets .select_related,
  // M2M gets .prefetch_related, reverse FK gets Count() annotation.
  context.subscriptions.push(
    vscode.commands.registerCommand(
      'ormSynapse.buildQuery',
      async (arg?: TreeNode) => {
        if (scanner.index.apps.length === 0) await scanner.refresh();
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
          const picks = scanner.index.apps.flatMap((app) =>
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
            title: 'ORM Synapse — Query Builder',
            placeHolder: 'Pick a target field or model',
          });
          if (!chosen) return;
          target = chosen.target;
        }

        const templates = generateQueryTemplates(target, scanner.index);
        if (templates.length === 0) {
          vscode.window.showInformationMessage(
            'ORM Synapse: no templates apply to this target.',
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
          `# ORM Synapse — Query Builder scratch`,
          `# from ${
            scanner.index.apps.find((a) =>
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
      'ormSynapse.findImpact',
      async (arg?: TreeNode | string) => {
        if (scanner.index.apps.length === 0) await scanner.refresh();
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
          const picks = scanner.index.apps.flatMap((app) =>
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
            title: 'ORM Synapse — Impact Analysis',
            placeHolder: 'Pick a field or model to trace',
          });
          if (!chosen) return;
          needle = chosen.needle;
          if (chosen.filePath) skipFiles = [chosen.filePath];
        }

        await vscode.window.withProgress(
          {
            location: vscode.ProgressLocation.Notification,
            title: `ORM Synapse: scanning references to '${needle}'…`,
            cancellable: true,
          },
          async (_progress, token) => {
            const findings = await scanImpact(needle!, { skipFiles, token });
            if (findings.length === 0) {
              vscode.window.showInformationMessage(
                `ORM Synapse: no references to '${needle}' found across the workspace.`,
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
    vscode.commands.registerCommand('ormSynapse.showDiff', async () => {
      if (scanner.index.apps.length === 0) await scanner.refresh();
      const modelsFiles = [
        ...new Set(
          scanner.index.apps.flatMap((a) => a.models.map((m) => m.filePath)),
        ),
      ];
      if (modelsFiles.length === 0) {
        vscode.window.showInformationMessage(
          'ORM Synapse: no models.py found — scan a Django project first.',
        );
        return;
      }
      let target = modelsFiles[0];
      if (modelsFiles.length > 1) {
        const pick = await vscode.window.showQuickPick(
          modelsFiles.map((p) => ({ label: p, description: 'models.py' })),
          { title: 'ORM Synapse — schema diff', placeHolder: 'Pick a models.py' },
        );
        if (!pick) return;
        target = pick.label;
      }
      const wsFolder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(target));
      if (!wsFolder) {
        vscode.window.showWarningMessage(
          'ORM Synapse: file is outside the current workspace.',
        );
        return;
      }
      const cwd = wsFolder.uri.fsPath;

      let commits;
      try {
        commits = await gitLogFollow(cwd, target, 200);
      } catch (err) {
        vscode.window.showWarningMessage(
          `ORM Synapse: git log failed — is this a git repo? (${
            err instanceof Error ? err.message : String(err)
          })`,
        );
        return;
      }
      if (commits.length < 2) {
        vscode.window.showInformationMessage(
          'ORM Synapse: need at least 2 commits touching this file for a diff.',
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
          `ORM Synapse: could not read historical models.py (${
            err instanceof Error ? err.message : String(err)
          })`,
        );
        return;
      }

      const events = diffSchemas(oldModels, newModels);
      const header = [
        `# ORM Synapse — Schema Diff`,
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
      'ormSynapse.generateFactory',
      async (arg1?: string | TreeNode, arg2?: number) => {
        if (scanner.index.apps.length === 0) await scanner.refresh();
        let target: { filePath: string; lineNumber?: number; name?: string } | undefined;
        if (typeof arg1 === 'string' && typeof arg2 === 'number') {
          target = { filePath: arg1, lineNumber: arg2 };
        } else if (arg1 && typeof arg1 === 'object' && 'kind' in arg1 && arg1.kind === 'model') {
          target = { filePath: arg1.filePath ?? '', lineNumber: arg1.lineNumber, name: arg1.label };
        } else {
          const picks = scanner.index.apps.flatMap((app) =>
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

        let model = scanner.index.apps
          .flatMap((a) => a.models)
          .find(
            (m) =>
              m.filePath === target!.filePath &&
              (target!.name ? m.name === target!.name : m.lineNumber === target!.lineNumber)
          );
        if (!model) {
          model = scanner.index.apps
            .flatMap((a) => a.models)
            .find((m) => m.filePath === target!.filePath);
        }
        if (!model) {
          vscode.window.showInformationMessage(
            'ORM Synapse: no model matched — try Refresh and retry.'
          );
          return;
        }
        const source = generateFactoryCode(model, scanner.index);
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
      'ormSynapse.jumpToModel',
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
            `ORM Synapse: could not open ${filePath}. It may have been moved, deleted, or is outside the workspace. (${msg})`
          );
          scanner.refresh().catch((refreshErr) =>
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
      'ormSynapse.findReverseRefs',
      async (node?: TreeNode) => {
        if (!node || node.kind !== 'model') {
          vscode.window.showInformationMessage(
            'ORM Synapse: right-click a model in the sidebar to find reverse references.'
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
        for (const app of scanner.index.apps) {
          for (const other of app.models) {
            if (
              other.name === modelName &&
              other.filePath === node.filePath
            ) {
              continue;
            }
            const userModelName = findUserModel(scanner.index)?.name;
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
      if (e.affectsConfiguration('ormSynapse.autoRefresh')) scanner.setupWatcher(context);
      if (e.affectsConfiguration('ormSynapse.excludeGlobs')) {
        scanner.refresh().catch((err) =>
          outputChannel.appendLine(
            `[config-refresh] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
      if (e.affectsConfiguration('ormSynapse.showCodeLens')) {
        codeLensProvider?.refresh();
      }
    })
  );

  scanner.setupWatcher(context);
  await scanner.refresh();

  // Backstop: if the first scan happened before the workspace file index
  // was warm (common with `onStartupFinished` activation), try again once
  // after a short delay. Cheap — early-exits on the second scan if the
  // first one already populated results.
  if (scanner.index.apps.length === 0 && (vscode.workspace.workspaceFolders?.length ?? 0) > 0) {
    setTimeout(() => {
      if (scanner.index.apps.length === 0) {
        scanner.refresh().catch((err) =>
          outputChannel.appendLine(
            `[startup-retry] ${err instanceof Error ? err.stack ?? err.message : String(err)}`
          )
        );
      }
    }, 1500);
  }
}

export function deactivate() {
  scanner?.dispose();
  statusItem?.dispose();
}
