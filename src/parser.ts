import * as vscode from 'vscode';
import * as path from 'path';
import {
  ParsedApp,
  ParsedField,
  ParsedModel,
  RelationKind,
  WorkspaceIndex,
} from './types';

const RELATION_TYPES: RelationKind[] = [
  'ForeignKey',
  'ManyToManyField',
  'OneToOneField',
];

const CLASS_RE = /^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*:/;

function detectClassIndent(lines: string[], classLineIdx: number): number {
  for (let i = classLineIdx + 1; i < Math.min(classLineIdx + 30, lines.length); i++) {
    const m = lines[i].match(/^([\t ]+)\S/);
    if (m) return m[1].length;
  }
  return 4;
}

function buildBodyRegexes(indent: number) {
  const w = `\\s{${indent}}`;
  const w2 = `\\s{${indent * 2}}`;
  return {
    FIELD_RE: new RegExp(
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)\\s*=\\s*models\\.([A-Za-z_][A-Za-z0-9_]*)\\s*\\(`
    ),
    META_START_RE: new RegExp(`^${w}class\\s+Meta\\s*(?:\\([^)]*\\))?\\s*:`),
    META_ITEM_RE: new RegExp(
      `^${w2}([a-zA-Z_][a-zA-Z0-9_]*)\\s*=\\s*(.+?)\\s*(#.*)?$`
    ),
    META_BODY_RE: new RegExp(`^\\s{${indent * 2},}`),
  };
}

function extractRelated(argsBlock: string): string | undefined {
  const stripped = argsBlock.trim();
  const firstArgMatch = stripped.match(
    /^(?:to\s*=\s*)?(?:'([^']+)'|"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*))/
  );
  if (!firstArgMatch) return undefined;
  const raw = firstArgMatch[1] || firstArgMatch[2] || firstArgMatch[3];
  if (!raw) return undefined;
  if (raw === 'self') return 'self';
  const clean = raw.replace(/^['"]|['"]$/g, '');
  return clean;
}

function readBalancedArgs(lines: string[], startIdx: number): {
  argsBlock: string;
  endIdx: number;
} {
  const openIdx = lines[startIdx].indexOf('(');
  let depth = 0;
  let buffer = '';
  for (let i = startIdx; i < lines.length; i++) {
    const src = i === startIdx ? lines[i].slice(openIdx) : lines[i];
    for (const ch of src) {
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0) {
          return { argsBlock: (buffer + ')').replace(/^\(/, ''), endIdx: i };
        }
      }
      buffer += ch;
    }
    buffer += '\n';
  }
  return { argsBlock: buffer.replace(/^\(/, ''), endIdx: lines.length - 1 };
}

export function parseModelsFile(filePath: string, content: string): ParsedModel[] {
  const lines = content.split(/\r?\n/);
  const models: ParsedModel[] = [];
  const appName = path.basename(path.dirname(filePath)) || 'app';

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const classMatch = line.match(CLASS_RE);
    if (!classMatch) {
      i++;
      continue;
    }
    const modelName = classMatch[1];
    const baseClasses = classMatch[2]
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const looksLikeModel = baseClasses.some(
      (b) => /models\.Model$/.test(b) || /Model$/.test(b) || /Abstract/.test(b)
    );
    if (!looksLikeModel && !baseClasses.some((b) => b.includes('Model'))) {
      i++;
      continue;
    }

    const model: ParsedModel = {
      name: modelName,
      appName,
      filePath,
      lineNumber: i,
      fields: [],
      meta: {},
      baseClasses,
    };

    const indent = detectClassIndent(lines, i);
    const { FIELD_RE, META_START_RE, META_ITEM_RE, META_BODY_RE } =
      buildBodyRegexes(indent);

    let j = i + 1;
    while (j < lines.length) {
      const innerLine = lines[j];
      if (/^class\s+/.test(innerLine) && !/^\s+class/.test(innerLine)) {
        break;
      }
      if (innerLine.trim().length === 0) {
        j++;
        continue;
      }

      const metaStart = innerLine.match(META_START_RE);
      if (metaStart) {
        let k = j + 1;
        while (k < lines.length) {
          const metaLine = lines[k];
          if (metaLine.length && !META_BODY_RE.test(metaLine) && metaLine.trim().length > 0) break;
          const m = metaLine.match(META_ITEM_RE);
          if (m) {
            model.meta[m[1]] = m[2].trim();
          }
          k++;
        }
        j = k;
        continue;
      }

      const fieldMatch = innerLine.match(FIELD_RE);
      if (fieldMatch) {
        const fieldName = fieldMatch[1];
        const fieldType = fieldMatch[2];
        const { argsBlock, endIdx } = readBalancedArgs(lines, j);
        const isRel = RELATION_TYPES.includes(fieldType as RelationKind);
        const field: ParsedField = {
          name: fieldName,
          type: fieldType,
          args: argsBlock.slice(0, -1).trim(),
          isRelation: isRel,
          lineNumber: j,
        };
        if (isRel) {
          field.relationKind = fieldType as RelationKind;
          field.relatedModel = extractRelated(argsBlock.slice(0, -1));
        }
        model.fields.push(field);
        j = endIdx + 1;
        continue;
      }

      j++;
    }

    models.push(model);
    i = j;
  }

  return models;
}

export async function scanWorkspace(
  excludeGlobs: string[]
): Promise<WorkspaceIndex> {
  const excludePattern = `{${excludeGlobs.join(',')}}`;
  const uris = await vscode.workspace.findFiles('**/models.py', excludePattern);
  const appMap = new Map<string, ParsedApp>();

  for (const uri of uris) {
    try {
      const bytes = await vscode.workspace.fs.readFile(uri);
      const content = Buffer.from(bytes).toString('utf-8');
      const models = parseModelsFile(uri.fsPath, content);
      if (models.length === 0) continue;
      const appDir = path.dirname(uri.fsPath);
      const appName = path.basename(appDir);
      let app = appMap.get(appDir);
      if (!app) {
        app = { name: appName, path: appDir, models: [] };
        appMap.set(appDir, app);
      }
      app.models.push(...models);
    } catch (err) {
      // ignore unreadable files
    }
  }

  const apps = Array.from(appMap.values()).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  return { apps, scannedAt: Date.now() };
}
