import * as vscode from 'vscode';
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
    const cfg = vscode.workspace.getConfiguration('djangoOrmLens');
    if (!cfg.get<boolean>('showCodeLens', true)) return [];
    const index = this.getIndex();
    const docPath = document.uri.fsPath.replace(/\\/g, '/').toLowerCase();
    const lenses: vscode.CodeLens[] = [];

    for (const app of index.apps) {
      for (const model of app.models) {
        const modelPath = model.filePath.replace(/\\/g, '/').toLowerCase();
        if (modelPath !== docPath) continue;
        const line = Math.max(0, model.lineNumber);
        if (line >= document.lineCount) continue;
        const range = new vscode.Range(line, 0, line, 0);
        const scalars = model.fields.filter((f) => !f.isRelation).length;
        const relations = model.fields.filter((f) => f.isRelation).length;

        const parts: string[] = [];
        parts.push(`$(database) ${scalars} field${scalars === 1 ? '' : 's'}`);
        parts.push(`$(references) ${relations} relation${relations === 1 ? '' : 's'}`);
        const title = parts.join(' · ') + ' · Open ER diagram';

        lenses.push(
          new vscode.CodeLens(range, {
            title,
            command: 'djangoOrmLens.showGraph',
            tooltip: `${model.appName}.${model.name} — click to open the ER diagram`,
          })
        );
      }
    }

    return lenses;
  }
}
