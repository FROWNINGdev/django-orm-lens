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
const CLASS_START_RE = /^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/;

function readMultilineClass(
  lines: string[],
  startIdx: number
): { match: RegExpMatchArray; endIdx: number } | null {
  let buffer = lines[startIdx];
  let depth = 0;
  let sawOpen = false;
  for (let i = startIdx; i < lines.length; i++) {
    const src = i === startIdx ? lines[i] : lines[i].trimStart();
    for (const ch of src) {
      if (ch === '(') {
        depth++;
        sawOpen = true;
      } else if (ch === ')') depth--;
    }
    if (i > startIdx) buffer += ' ' + src;
    if (sawOpen && depth === 0) {
      const m = buffer.match(CLASS_RE);
      if (m) return { match: m, endIdx: i };
      break;
    }
  }
  return null;
}

function detectClassIndent(lines: string[], classLineIdx: number): number {
  for (let i = classLineIdx + 1; i < Math.min(classLineIdx + 30, lines.length); i++) {
    const m = lines[i].match(/^([\t ]+)\S/);
    if (m) return m[1].length;
  }
  return 4;
}

const BARE_FIELD_TYPES = [
  'CharField', 'TextField', 'SlugField', 'EmailField', 'URLField', 'UUIDField',
  'IntegerField', 'BigIntegerField', 'SmallIntegerField',
  'PositiveIntegerField', 'PositiveSmallIntegerField', 'PositiveBigIntegerField',
  'FloatField', 'DecimalField',
  'BooleanField', 'NullBooleanField',
  'DateTimeField', 'DateField', 'TimeField', 'DurationField',
  'JSONField', 'BinaryField',
  'FileField', 'ImageField', 'FilePathField',
  'GenericIPAddressField',
  'AutoField', 'BigAutoField', 'SmallAutoField',
  'ForeignKey', 'OneToOneField', 'ManyToManyField',
].join('|');

function buildBodyRegexes(indent: number) {
  const w = `\\s{${indent}}`;
  const w2 = `\\s{${indent * 2}}`;
  return {
    FIELD_RE: new RegExp(
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)\\s*=\\s*models\\.([A-Za-z_][A-Za-z0-9_]*)\\s*\\(`
    ),
    BARE_FIELD_RE: new RegExp(
      `^${w}([a-zA-Z_][a-zA-Z0-9_]*)\\s*=\\s*(${BARE_FIELD_TYPES})\\s*\\(`
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

function extractOnDelete(argsBlock: string): string | undefined {
  const m = argsBlock.match(
    /on_delete\s*=\s*(?:models\.)?([A-Z][A-Z_]+)/
  );
  return m?.[1];
}

function extractRelatedName(argsBlock: string): string | undefined {
  const m = argsBlock.match(
    /related_name\s*=\s*(?:'([^']+)'|"([^"]+)")/
  );
  return m ? m[1] || m[2] : undefined;
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
  const parent = path.basename(path.dirname(filePath));
  const appName =
    parent === 'models' ? path.basename(path.dirname(path.dirname(filePath))) : parent || 'app';

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let classMatch = line.match(CLASS_RE);
    let classHeaderEnd = i;
    if (!classMatch && CLASS_START_RE.test(line)) {
      const joined = readMultilineClass(lines, i);
      if (joined) {
        classMatch = joined.match;
        classHeaderEnd = joined.endIdx;
      }
    }
    if (!classMatch) {
      i++;
      continue;
    }
    const modelName = classMatch[1];
    const baseClasses = classMatch[2]
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const NON_MODEL_TAIL =
      /^(ModelAdmin|ModelForm|ModelSerializer|ModelChoiceField|ModelMultipleChoiceField|Serializer|Form|Admin|View|ViewSet|Manager|QuerySet|Config|AppConfig|Response|Handler|Middleware|Backend|Command)$/;
    const looksLikeModel = baseClasses.some((b) => {
      const tail = b.split('.').pop() ?? '';
      if (NON_MODEL_TAIL.test(tail)) return false;
      return (
        /models\.Model$/.test(b) ||
        /^(Model|AbstractModel|AbstractBaseModel|TimeStampedModel|PolymorphicModel)$/.test(tail) ||
        /^Abstract[A-Z]/.test(tail) ||
        /Mixin$/.test(tail)
      );
    });
    if (!looksLikeModel) {
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

    const indent = detectClassIndent(lines, classHeaderEnd);
    const { FIELD_RE, BARE_FIELD_RE, META_START_RE, META_ITEM_RE, META_BODY_RE } =
      buildBodyRegexes(indent);

    let j = classHeaderEnd + 1;
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

      const fieldMatch = innerLine.match(FIELD_RE) ?? innerLine.match(BARE_FIELD_RE);
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
          const argsInner = argsBlock.slice(0, -1);
          field.relatedModel = extractRelated(argsInner);
          const onDelete = extractOnDelete(argsInner);
          if (onDelete) field.onDelete = onDelete;
          const relatedName = extractRelatedName(argsInner);
          if (relatedName) field.relatedName = relatedName;
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

function appDirFor(fsPath: string): { dir: string; name: string } {
  const parent = path.dirname(fsPath);
  const parentName = path.basename(parent);
  if (parentName === 'models') {
    const grand = path.dirname(parent);
    return { dir: grand, name: path.basename(grand) };
  }
  return { dir: parent, name: parentName };
}

export async function scanWorkspace(
  excludeGlobs: string[]
): Promise<WorkspaceIndex> {
  const excludePattern = `{${excludeGlobs.join(',')}}`;
  const [flat, split] = await Promise.all([
    vscode.workspace.findFiles('**/models.py', excludePattern),
    vscode.workspace.findFiles('**/models/*.py', excludePattern),
  ]);
  const uris = [...flat, ...split.filter((u) => !u.fsPath.endsWith('__init__.py'))];
  const appMap = new Map<string, ParsedApp>();

  for (const uri of uris) {
    try {
      const bytes = await vscode.workspace.fs.readFile(uri);
      const content = Buffer.from(bytes).toString('utf-8');
      const models = parseModelsFile(uri.fsPath, content);
      if (models.length === 0) continue;
      const { dir: appDir, name: appName } = appDirFor(uri.fsPath);
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
