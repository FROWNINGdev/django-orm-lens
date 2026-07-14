import * as vscode from 'vscode';
import { ParsedModel, WorkspaceIndex } from './types';

export class DjangoHoverProvider implements vscode.HoverProvider {
  constructor(private getIndex: () => WorkspaceIndex) {}

  provideHover(
    document: vscode.TextDocument,
    position: vscode.Position
  ): vscode.ProviderResult<vscode.Hover> {
    const wordRange = document.getWordRangeAtPosition(position, /['"][A-Za-z0-9_.]+['"]/);
    if (!wordRange) return undefined;

    const line = document.lineAt(position.line).text;
    if (!/ForeignKey|OneToOneField|ManyToManyField/.test(line)) return undefined;

    const raw = document.getText(wordRange).replace(/^['"]|['"]$/g, '');
    if (raw === 'self') return undefined;

    const targetName = raw.split('.').pop();
    if (!targetName) return undefined;

    const index = this.getIndex();
    const model = this.findModel(index, raw, targetName);
    if (!model) return undefined;

    const md = new vscode.MarkdownString();
    md.isTrusted = true;
    md.supportHtml = false;
    md.appendMarkdown(`**${model.appName}.${model.name}**  \n`);
    md.appendMarkdown(`_${model.baseClasses.join(', ') || 'models.Model'}_\n\n`);

    const scalars = model.fields.filter((f) => !f.isRelation);
    const relations = model.fields.filter((f) => f.isRelation);

    if (scalars.length > 0) {
      md.appendMarkdown('**Fields**\n');
      for (const f of scalars.slice(0, 12)) {
        md.appendMarkdown(`- \`${f.name}\` — ${f.type}\n`);
      }
      if (scalars.length > 12) {
        md.appendMarkdown(`- _...and ${scalars.length - 12} more_\n`);
      }
    }
    if (relations.length > 0) {
      md.appendMarkdown('\n**Relations**\n');
      for (const f of relations) {
        md.appendMarkdown(
          `- \`${f.name}\` → **${f.relatedModel ?? '?'}** _(${f.relationKind})_\n`
        );
      }
    }

    const jumpArgs = encodeURIComponent(
      JSON.stringify([model.filePath, model.lineNumber])
    );
    md.appendMarkdown(
      `\n[Jump to \`${model.name}\` definition](command:djangoOrmLens.jumpToModel?${jumpArgs})`
    );

    return new vscode.Hover(md, wordRange);
  }

  private findModel(
    index: WorkspaceIndex,
    fullRef: string,
    tail: string
  ): ParsedModel | undefined {
    if (fullRef.includes('.')) {
      const [appName, modelName] = fullRef.split('.');
      for (const app of index.apps) {
        if (app.name === appName) {
          const m = app.models.find((mm) => mm.name === modelName);
          if (m) return m;
        }
      }
    }
    for (const app of index.apps) {
      const m = app.models.find((mm) => mm.name === tail);
      if (m) return m;
    }
    return undefined;
  }
}
