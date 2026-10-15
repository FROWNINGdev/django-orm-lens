import * as vscode from 'vscode';
import { childRelationCounts, concreteFields, isProxyModel, tableModel } from './parser';
import { WorkspaceIndex } from './types';

export class DjangoCodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  constructor(private getIndex: () => WorkspaceIndex) {}

  refresh(): void {
    this._onDidChangeCodeLenses.fire();
  }

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (document.languageId !== 'python') return [];
    const cfg = vscode.workspace.getConfiguration('ormSynapse');
    if (!cfg.get<boolean>('showCodeLens', true)) return [];
    const index = this.getIndex();
    const docPath = document.uri.fsPath.replace(/\\/g, '/').toLowerCase();
    const lenses: vscode.CodeLens[] = [];
    // The same class can be indexed twice (a models package re-export, or a
    // second extension host pass). One lens pair per line, or the editor
    // prints "3 fields · Open ER diagram | Generate factory" twice.
    const seenLines = new Set<number>();
    const relationCounts = childRelationCounts(index);

    for (const app of index.apps) {
      for (const model of app.models) {
        const modelPath = model.filePath.replace(/\\/g, '/').toLowerCase();
        if (modelPath !== docPath) continue;
        const line = Math.max(0, model.lineNumber);
        if (line >= document.lineCount || seenLines.has(line)) continue;
        seenLines.add(line);
        const range = new vscode.Range(line, 0, line, 0);
        if (isProxyModel(model)) {
          const table = tableModel(index, model);
          lenses.push(
            new vscode.CodeLens(range, {
              title: `$(references) proxy of ${table.name} · Open ER diagram`,
              command: 'ormSynapse.showGraph',
              arguments: [model.filePath, model.lineNumber],
              tooltip: `${model.appName}.${model.name} has no table of its own. The diagram shows ${table.appName}.${table.name}.`,
            })
          );
          lenses.push(
            new vscode.CodeLens(range, {
              title: '$(beaker) Generate factory',
              command: 'ormSynapse.generateFactory',
              arguments: [model.filePath, model.lineNumber],
              tooltip: `Scaffold a factory_boy DjangoModelFactory for ${model.name}`,
            })
          );
          continue;
        }
        const scalars = concreteFields(model).filter((f) => !f.isRelation).length;
        const relations = relationCounts.get(model) ?? 0;

        const parts: string[] = [];
        parts.push(`$(database) ${scalars} field${scalars === 1 ? '' : 's'}`);
        parts.push(`$(references) ${relations} child relation${relations === 1 ? '' : 's'}`);
        const title = parts.join(' · ') + ' · Open ER diagram';

        lenses.push(
          new vscode.CodeLens(range, {
            title,
            command: 'ormSynapse.showGraph',
            arguments: [model.filePath, model.lineNumber],
            tooltip: `${model.appName}.${model.name} — ${relations} relation field${relations === 1 ? '' : 's'} point here. Click to diagram this model, every descendant, and the parents of those descendants`,
          })
        );
        lenses.push(
          new vscode.CodeLens(range, {
            title: '$(beaker) Generate factory',
            command: 'ormSynapse.generateFactory',
            arguments: [model.filePath, model.lineNumber],
            tooltip: `Scaffold a factory_boy DjangoModelFactory for ${model.name}`,
          })
        );
      }
    }

    return lenses;
  }
}
