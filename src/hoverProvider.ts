import * as vscode from 'vscode';
import { ParsedModel, WorkspaceIndex } from './types';

function md(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>]/g, (c) => `\\${c}`);
}

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

    const doc = new vscode.MarkdownString();
    doc.isTrusted = { enabledCommands: ['djangoOrmLens.jumpToModel'] };
    doc.supportHtml = false;
    doc.appendMarkdown(`**${md(model.appName)}.${md(model.name)}**\n\n`);
    doc.appendMarkdown(
      `_${md(model.baseClasses.join(', ') || 'models.Model')}_\n\n`
    );

    const scalars = model.fields.filter((f) => !f.isRelation);
    const relations = model.fields.filter((f) => f.isRelation);

    if (scalars.length > 0) {
      doc.appendMarkdown('**Fields**\n');
      for (const f of scalars.slice(0, 12)) {
        doc.appendMarkdown(`- \`${md(f.name)}\` — ${md(f.type)}\n`);
      }
      if (scalars.length > 12) {
        doc.appendMarkdown(`- _…and ${scalars.length - 12} more_\n`);
      }
    }
    if (relations.length > 0) {
      doc.appendMarkdown('\n**Relations**\n');
      for (const f of relations) {
        doc.appendMarkdown(
          `- \`${md(f.name)}\` → **${md(f.relatedModel ?? '?')}** _(${md(
            f.relationKind ?? ''
          )})_\n`
        );
      }
    }

    const jumpArgs = encodeURIComponent(
      JSON.stringify([model.filePath, model.lineNumber])
    );
    doc.appendMarkdown(
      `\n[Jump to ${md(model.name)}](command:djangoOrmLens.jumpToModel?${jumpArgs})`
    );

    return new vscode.Hover(doc, wordRange);
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
