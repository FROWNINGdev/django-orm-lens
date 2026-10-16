import { Finding, Rule, RuleContext } from './types';
import { ParsedField, ParsedModel } from '../types';

/**
 * Denormalization smells. Review hints, not a 2NF/3NF proof.
 *
 * Mirrors cli/db_synapse/denormalize.py. A scalar `company_id` with no
 * ForeignKey is a convention, not a copied column, and stays quiet.
 */

const DOCS_BASE = 'https://github.com/nam-tong/db-synapse/blob/main/docs/rules';

const COPIED_SUFFIXES = new Set([
  'name',
  'title',
  'email',
  'slug',
  'code',
  'label',
  'phone',
  'address',
]);

const RE_REPEATED = /^([A-Za-z][A-Za-z0-9]*)_(\d+)$/;
const RE_CLASS_HEAD = /^(\s*)class\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:/;
const RE_FIELD =
  /^(\s*)([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)\s*\(/;
const RE_PROXY = /^\s+proxy\s*=\s*True\b/;

interface SmellField {
  name: string;
  type: string;
  isRelation: boolean;
  relationKind?: string;
  line: number;
  inheritedFrom?: string;
}

function textish(type: string): boolean {
  return /(?:CharField|TextField|JSONField)$/.test(type);
}

function relationKind(type: string): string | undefined {
  if (type === 'GenericForeignKey') return undefined;
  if (type.endsWith('ManyToManyField')) return 'ManyToManyField';
  if (type.endsWith('OneToOneField')) return 'OneToOneField';
  if (type.endsWith('ForeignKey')) return 'ForeignKey';
  return undefined;
}

function idList(model: string, field: SmellField): Finding | undefined {
  if (field.isRelation || !field.name.endsWith('_ids') || !textish(field.type)) return undefined;
  return finding(
    'DOL018',
    'idList',
    field,
    {
      field: field.name,
      type: field.type,
      model,
    },
  );
}

function repeated(model: string, owned: SmellField[]): Finding[] {
  const groups = new Map<string, SmellField[]>();
  for (const field of owned) {
    const match = RE_REPEATED.exec(field.name);
    if (!match || match[1].length < 2) continue;
    const list = groups.get(match[1]) ?? [];
    list.push(field);
    groups.set(match[1], list);
  }
  const out: Finding[] = [];
  for (const [stem, fields] of groups) {
    const numbers = new Set(fields.map((field) => RE_REPEATED.exec(field.name)?.[2]));
    if (numbers.size < 3) continue;
    const first = [...fields].sort((a, b) => a.line - b.line || a.name.localeCompare(b.name))[0];
    const names = [...fields].map((field) => field.name).sort().join(', ');
    out.push(
      finding('DOL019', 'repeated', first, { names, stem, field: first.name, model }),
    );
  }
  return out;
}

function copied(model: string, owned: SmellField[], relations: SmellField[]): Finding[] {
  const names = relations
    .filter((field) => field.relationKind === 'ForeignKey' || field.relationKind === 'OneToOneField')
    .map((field) => field.name);
  const out: Finding[] = [];
  for (const field of owned) {
    if (field.isRelation) continue;
    for (const relation of names) {
      if (!field.name.startsWith(`${relation}_`)) continue;
      const suffix = field.name.slice(relation.length + 1);
      if (!COPIED_SUFFIXES.has(suffix)) continue;
      out.push(finding('DOL020', 'copied', field, { field: field.name, relation, suffix, model }));
      break;
    }
  }
  return out;
}

function finding(
  code: string,
  messageId: string,
  field: SmellField,
  args: Record<string, string>,
): Finding {
  return {
    code,
    messageId,
    args,
    range: {
      line: field.line,
      startCol: 0,
      endCol: field.name.length,
    },
    applicability: 'unsafe',
  };
}

function locate(line: string, name: string, base: Finding): Finding {
  const at = line.indexOf(name);
  if (at < 0) return base;
  return {
    ...base,
    range: { line: base.range.line, startCol: at, endCol: at + name.length },
  };
}

function fromParsed(field: ParsedField): SmellField {
  return {
    name: field.name,
    type: field.type,
    isRelation: field.isRelation,
    relationKind: field.relationKind,
    line: field.lineNumber,
    inheritedFrom: field.inheritedFrom,
  };
}

function isProxy(model: ParsedModel): boolean {
  return ['True', '1', 'true'].includes((model.meta?.proxy ?? '').trim().replace(/,$/, ''));
}

function smellsFor(
  model: string,
  owned: SmellField[],
  relations: SmellField[],
  inherited: SmellField[],
): Finding[] {
  return [
    ...repeated(model, owned),
    ...copied(model, owned, relations),
    ...[...owned, ...inherited].map((field) => idList(model, field)).filter((item): item is Finding => !!item),
  ];
}

function* classBodies(
  ctx: RuleContext,
): Generator<{ name: string; bases: string; headIndent: string; headLine: number }> {
  for (let i = 0; i < ctx.lineCount; i++) {
    const head = RE_CLASS_HEAD.exec(ctx.lineAt(i));
    if (!head) continue;
    if (!/Model/.test(head[3])) continue;
    yield { name: head[2], bases: head[3], headIndent: head[1], headLine: i };
  }
}

function directFields(ctx: RuleContext, headLine: number, headIndent: string): SmellField[] {
  const body: { line: number; text: string; indent: number }[] = [];
  for (let i = headLine + 1; i < ctx.lineCount; i++) {
    const text = ctx.lineAt(i);
    if (text.trim() === '') continue;
    const indent = /^(\s*)/.exec(text)?.[1].length ?? 0;
    if (indent <= headIndent.length) break;
    body.push({ line: i, text, indent });
  }
  if (body.length === 0 || body.some((line) => RE_PROXY.test(line.text))) return [];
  const min = Math.min(...body.map((line) => line.indent));
  const fields: SmellField[] = [];
  for (const line of body) {
    if (line.indent !== min || line.text.trimStart().startsWith('#')) continue;
    const match = RE_FIELD.exec(line.text);
    if (!match) continue;
    const kind = relationKind(match[3]);
    fields.push({
      name: match[2],
      type: match[3],
      isRelation: kind !== undefined,
      relationKind: kind,
      line: line.line,
    });
  }
  return fields;
}

function checkText(ctx: RuleContext): Finding[] {
  const out: Finding[] = [];
  for (const cls of classBodies(ctx)) {
    const fields = directFields(ctx, cls.headLine, cls.headIndent);
    if (fields.length === 0) continue;
    for (const smell of smellsFor(cls.name, fields, fields, [])) {
      out.push(locate(ctx.lineAt(smell.range.line), String(smell.args?.field ?? ''), smell));
    }
  }
  return out;
}

function checkIndex(ctx: RuleContext): Finding[] | undefined {
  const filePath = ctx.document?.uri?.fsPath;
  if (!ctx.index || !filePath) return undefined;
  const want = filePath.replace(/\\/g, '/').toLowerCase();
  const out: Finding[] = [];
  const seenInherited = new Set<string>();
  for (const app of ctx.index.apps) {
    for (const model of app.models) {
      const path = model.filePath.replace(/\\/g, '/').toLowerCase();
      if (path !== want || isProxy(model)) continue;
      const owned = model.fields.filter((field) => !field.inheritedFrom).map(fromParsed);
      const inherited = (model.inheritedFields ?? [])
        .filter((field) => field.inheritedFrom)
        .map(fromParsed);
      const relations = [...owned, ...inherited];
      for (const smell of smellsFor(model.name, owned, relations, inherited)) {
        const line = ctx.lineAt(smell.range.line);
        const name = String(smell.args?.field ?? '');
        if (!line.includes(name)) {
          if (smell.code !== 'DOL018') continue;
          const origin = inherited.find((field) => field.name === name)?.inheritedFrom ?? '';
          const key = `${smell.code}:${origin}:${name}`;
          if (seenInherited.has(key)) continue;
          seenInherited.add(key);
          smell.range = { line: model.lineNumber, startCol: 0, endCol: model.name.length };
          const classLine = ctx.lineAt(model.lineNumber);
          out.push(locate(classLine, model.name, smell));
          continue;
        }
        out.push(locate(line, name, smell));
      }
    }
  }
  return out;
}

function rule(code: string, title: string, messageId: string, template: string): Rule {
  return {
    meta: {
      code,
      title,
      category: 'correctness',
      defaultSeverity: 'warning',
      docsUrl: `${DOCS_BASE}/${code}.md`,
      since: '0.19.4',
      messages: { [messageId]: template },
    },
    check(ctx: RuleContext): Finding[] {
      const fromIndex = checkIndex(ctx);
      const found = fromIndex ?? checkText(ctx);
      return found.filter((item) => item.code === code);
    },
  };
}

export const denormalizeRules: Rule[] = [
  rule(
    'DOL018',
    'Several ids stored in one column',
    'idList',
    '{field} stores several ids in one {type}. A child row per id stays indexable. This is a review hint, not a proof the column is wrong.',
  ),
  rule(
    'DOL019',
    'Repeated column group',
    'repeated',
    '{names} repeat `{stem}`. A child table is the normalized form. Keep the columns when the group is a fixed set of values.',
  ),
  rule(
    'DOL020',
    'Column copies a related row',
    'copied',
    '{field} copies {relation} onto this table ({suffix}). Keep it when it is a snapshot or a cache; otherwise it belongs on {relation}.',
  ),
];
