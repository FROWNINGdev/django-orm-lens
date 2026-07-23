import { ParsedField, ParsedModel } from './types';

/**
 * Django ORM Lens — schema-diff engine.
 *
 * Pure, side-effect-free. Given two `ParsedModel[]` snapshots (from two
 * git blobs, replayed through `src/parser.ts`), produce a stream of
 * TYPED events that describe the schema-level change. The engine has
 * no `vscode` dependency so it round-trips through unit tests without
 * a mock, and can later be ported line-for-line to Python for CLI parity.
 *
 * Design distilled from Atlas (ariga/atlas) and Prisma's `migrate diff`:
 *
 *   - Events are structured, not text
 *   - Renames are first-class (never emitted as drop+add)
 *   - Rename detection is heuristic + confidence-tagged so the UI can
 *     ask the user to confirm before the change is treated as canonical
 *   - Field options are whitelisted — noise like `verbose_name` is not
 *     a schema change
 *
 * Callers:
 *   - src/diffWebview.ts (UI overlay on the ER diagram)
 *   - test/schema-diff.test.js (snapshot tests over pair fixtures)
 *   - future CLI parity: `django-orm-lens diff --from <ref> --to <ref>`
 */

/* ------------------------------  types  ------------------------------ */

export type ModelChange =
  | { kind: 'AddModel'; model: string; appName: string }
  | { kind: 'DropModel'; model: string; appName: string }
  | {
      kind: 'RenameModel';
      from: string;
      to: string;
      appName: string;
      confidence: number;
    }
  | {
      kind: 'ModifyModel';
      model: string;
      appName: string;
      changes: FieldChange[];
    };

export type FieldChange =
  | { kind: 'AddField'; name: string; type: string }
  | { kind: 'DropField'; name: string; type: string }
  | {
      // v0.9 — partial UniqueConstraint tracking. Inspired by
      // django-extensions#1813 (BoPeng, 2023) — sqldiff drops `condition=`
      // from UniqueConstraint output. Our schema-diff surfaces it as a
      // first-class event so downstream migration reviewers can see it.
      kind: 'PartialUniqueConstraint';
      name: string; // constraint name if given
      fields: string;
      condition: string;
    }
  | {
      kind: 'RenameField';
      from: string;
      to: string;
      type: string;
      confidence: number;
    }
  | { kind: 'ChangeFieldType'; name: string; from: string; to: string }
  | {
      kind: 'ChangeFieldOption';
      name: string;
      option: string;
      from: string;
      to: string;
    }
  | {
      kind: 'ChangeRelation';
      name: string;
      from: string;
      to: string;
    };

export interface DiffOptions {
  /**
   * Minimum score for a rename to be accepted. 0..1. Prisma-ish defaults:
   * anything below 0.6 is noise; 0.7 catches most real renames.
   */
  renameThreshold?: number;
}

/* -----------------------------  helpers  ----------------------------- */

/** Normalised Levenshtein similarity: 1 - dist / max(len). */
function nameSimilarity(a: string, b: string): number {
  if (a === b) return 1;
  const dist = levenshtein(a.toLowerCase(), b.toLowerCase());
  const maxLen = Math.max(a.length, b.length);
  return maxLen === 0 ? 0 : 1 - dist / maxLen;
}

function levenshtein(a: string, b: string): number {
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  const dp = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j];
      dp[j] =
        a[i - 1] === b[j - 1]
          ? prev
          : 1 + Math.min(prev, dp[j - 1], dp[j]);
      prev = tmp;
    }
  }
  return dp[b.length];
}

function jaccard<T>(a: Iterable<T>, b: Iterable<T>): number {
  const A = new Set(a);
  const B = new Set(b);
  if (A.size === 0 && B.size === 0) return 1;
  let intersect = 0;
  for (const x of A) if (B.has(x)) intersect++;
  const union = A.size + B.size - intersect;
  return union === 0 ? 0 : intersect / union;
}

/** Whitelisted schema-relevant field options — the rest is noise. */
const SCHEMA_OPTIONS = [
  'null',
  'blank',
  'unique',
  'default',
  'db_index',
  'primary_key',
  'max_length',
  'max_digits',
  'decimal_places',
  'on_delete',
  'related_name',
  'auto_now',
  'auto_now_add',
] as const;

/** Extract a normalized value for an option from a field's args body. */
function extractOption(argBody: string, name: string): string | undefined {
  const re = new RegExp(`\\b${name}\\s*=\\s*([^,)]+?)(?=,|$)`);
  const m = re.exec(argBody);
  return m ? m[1].trim() : undefined;
}

/* --------------------------  field alignment  ------------------------ */

function fieldSignature(f: ParsedField): string {
  // Shape used both by direct comparison and Jaccard field-name sets.
  return `${f.name}:${f.type}`;
}

/** Compute the change list for one field pair. */
function fieldPairChanges(oldF: ParsedField, newF: ParsedField): FieldChange[] {
  const out: FieldChange[] = [];

  if (oldF.type !== newF.type) {
    out.push({
      kind: 'ChangeFieldType',
      name: newF.name,
      from: oldF.type,
      to: newF.type,
    });
  }

  // Relation target / kind change.
  if (oldF.isRelation && newF.isRelation) {
    const oldRel = `${oldF.relationKind ?? '?'} → ${oldF.relatedModel ?? '?'}`;
    const newRel = `${newF.relationKind ?? '?'} → ${newF.relatedModel ?? '?'}`;
    if (oldRel !== newRel) {
      out.push({
        kind: 'ChangeRelation',
        name: newF.name,
        from: oldRel,
        to: newRel,
      });
    }
  }

  for (const opt of SCHEMA_OPTIONS) {
    const oldV = extractOption(oldF.args, opt);
    const newV = extractOption(newF.args, opt);
    if (oldV === newV) continue;
    out.push({
      kind: 'ChangeFieldOption',
      name: newF.name,
      option: opt,
      from: oldV ?? '(unset)',
      to: newV ?? '(unset)',
    });
  }

  return out;
}

/** Diff the field set of a single model (name-matched already). */
/**
 * Extract `UniqueConstraint(fields=[...], condition=Q(...), name=...)` shapes
 * from a `Meta.constraints = [...]` string. Returns one event per constraint
 * that carries a non-empty condition — bare unconditional UniqueConstraints
 * are silently ignored because they're covered by the DB's own indices.
 *
 * v0.9 feature seed. Inspired by django-extensions#1813 (sqldiff drops the
 * predicate from `condition=` and reports wrong SQL).
 */
function extractPartialUniqueConstraints(
  metaConstraintsRaw: string | undefined,
): { name: string; fields: string; condition: string }[] {
  if (!metaConstraintsRaw) return [];
  const out: { name: string; fields: string; condition: string }[] = [];
  const re =
    /UniqueConstraint\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(metaConstraintsRaw)) !== null) {
    const args = m[1];
    const cond = args.match(/condition\s*=\s*(Q\s*\([^)]*\))/);
    if (!cond) continue;
    const fields = args.match(/fields\s*=\s*\[([^\]]*)\]/);
    const name = args.match(/name\s*=\s*['"]([^'"]+)['"]/);
    out.push({
      name: name ? name[1] : '',
      fields: fields ? fields[1].trim() : '',
      condition: cond[1].trim(),
    });
  }
  return out;
}

function diffModelFields(
  oldModel: ParsedModel,
  newModel: ParsedModel,
  threshold: number,
): FieldChange[] {
  const out: FieldChange[] = [];

  // v0.9 — surface partial UniqueConstraint changes as first-class events.
  // Simple set-diff on the (name, condition) tuple so a modified predicate
  // shows up as a drop of the old shape and add of the new shape. Rename
  // detection could come later when the community asks.
  const oldPU = extractPartialUniqueConstraints(oldModel.meta?.constraints);
  const newPU = extractPartialUniqueConstraints(newModel.meta?.constraints);
  const oldKey = new Set(oldPU.map((c) => `${c.name}::${c.condition}`));
  const newKey = new Set(newPU.map((c) => `${c.name}::${c.condition}`));
  for (const c of newPU) {
    if (!oldKey.has(`${c.name}::${c.condition}`)) {
      out.push({ kind: 'PartialUniqueConstraint', ...c });
    }
  }

  const oldByName = new Map(oldModel.fields.map((f) => [f.name, f]));
  const newByName = new Map(newModel.fields.map((f) => [f.name, f]));
  // Suppress "unused" for future rename-detection reads — currently unread.
  void newKey;

  const matchedOld = new Set<string>();
  const matchedNew = new Set<string>();

  // Pass A: exact-name matches.
  for (const [name, oldF] of oldByName) {
    const newF = newByName.get(name);
    if (!newF) continue;
    matchedOld.add(name);
    matchedNew.add(name);
    out.push(...fieldPairChanges(oldF, newF));
  }

  const unmatchedOld = [...oldByName.values()].filter(
    (f) => !matchedOld.has(f.name),
  );
  const unmatchedNew = [...newByName.values()].filter(
    (f) => !matchedNew.has(f.name),
  );

  // Pass B: rename candidates — same type + high name similarity.
  const used = new Set<string>();
  for (const oldF of unmatchedOld) {
    let best: { newF: ParsedField; score: number } | undefined;
    for (const newF of unmatchedNew) {
      if (used.has(newF.name)) continue;
      if (oldF.type !== newF.type) continue;
      const s = nameSimilarity(oldF.name, newF.name);
      if (!best || s > best.score) best = { newF, score: s };
    }
    if (best && best.score >= threshold) {
      out.push({
        kind: 'RenameField',
        from: oldF.name,
        to: best.newF.name,
        type: oldF.type,
        confidence: Number(best.score.toFixed(3)),
      });
      // Also emit any option changes between the renamed pair.
      out.push(...fieldPairChanges(oldF, best.newF));
      used.add(best.newF.name);
      matchedOld.add(oldF.name);
      matchedNew.add(best.newF.name);
    }
  }

  // Pass C: remaining unmatched are true adds/drops.
  for (const f of oldByName.values()) {
    if (matchedOld.has(f.name)) continue;
    out.push({ kind: 'DropField', name: f.name, type: f.type });
  }
  for (const f of newByName.values()) {
    if (matchedNew.has(f.name)) continue;
    out.push({ kind: 'AddField', name: f.name, type: f.type });
  }

  return out;
}

/* --------------------------  model alignment  ------------------------ */

interface ModelIndex {
  byQualifiedName: Map<string, ParsedModel>;
  all: ParsedModel[];
}

function indexModels(models: ParsedModel[]): ModelIndex {
  const byQualifiedName = new Map<string, ParsedModel>();
  for (const m of models) {
    byQualifiedName.set(`${m.appName}.${m.name}`, m);
  }
  return { byQualifiedName, all: models };
}

/** Score two models for rename-likelihood (0..1). */
function modelSimilarity(a: ParsedModel, b: ParsedModel): number {
  const nameSim = nameSimilarity(a.name, b.name);
  const fieldNames = jaccard(
    a.fields.map((f) => f.name),
    b.fields.map((f) => f.name),
  );
  const fieldShapes = jaccard(
    a.fields.map(fieldSignature),
    b.fields.map(fieldSignature),
  );
  // Weights: shape > name-set > name-string. Shape carries most signal.
  return 0.5 * fieldShapes + 0.35 * fieldNames + 0.15 * nameSim;
}

/* ---------------------------  public API  ---------------------------- */

/**
 * Diff two model catalogues. Returns a list of typed change events in
 * a stable order: AddModel < DropModel < RenameModel < ModifyModel,
 * and within Modify, changes ordered by field name for deterministic
 * snapshot tests.
 */
export function diffSchemas(
  oldModels: ParsedModel[],
  newModels: ParsedModel[],
  options: DiffOptions = {},
): ModelChange[] {
  const threshold = options.renameThreshold ?? 0.7;
  const oldIx = indexModels(oldModels);
  const newIx = indexModels(newModels);

  const matchedOld = new Set<string>();
  const matchedNew = new Set<string>();

  const events: ModelChange[] = [];

  // Pass 1: exact-qualified-name matches → ModifyModel or no-op.
  for (const [qn, oldM] of oldIx.byQualifiedName) {
    const newM = newIx.byQualifiedName.get(qn);
    if (!newM) continue;
    matchedOld.add(qn);
    matchedNew.add(qn);
    const changes = diffModelFields(oldM, newM, threshold);
    if (changes.length > 0) {
      events.push({
        kind: 'ModifyModel',
        model: newM.name,
        appName: newM.appName,
        changes: changes.sort((a, b) => cmpFieldChange(a, b)),
      });
    }
  }

  const unmatchedOld = oldIx.all.filter(
    (m) => !matchedOld.has(`${m.appName}.${m.name}`),
  );
  const unmatchedNew = newIx.all.filter(
    (m) => !matchedNew.has(`${m.appName}.${m.name}`),
  );

  // Pass 2: rename candidates. Match must be top-of-both.
  const takenNew = new Set<string>();
  const takenOld = new Set<string>();
  for (const oldM of unmatchedOld) {
    let best: { newM: ParsedModel; score: number } | undefined;
    for (const newM of unmatchedNew) {
      const qn = `${newM.appName}.${newM.name}`;
      if (takenNew.has(qn)) continue;
      if (oldM.appName !== newM.appName) continue; // renames stay per-app
      const s = modelSimilarity(oldM, newM);
      if (!best || s > best.score) best = { newM, score: s };
    }
    if (!best || best.score < threshold) continue;
    // Check reverse: is `oldM` the top match for `best.newM` too?
    let bestBack: { oldM: ParsedModel; score: number } | undefined;
    for (const cand of unmatchedOld) {
      if (takenOld.has(`${cand.appName}.${cand.name}`)) continue;
      if (cand.appName !== best.newM.appName) continue;
      const s = modelSimilarity(cand, best.newM);
      if (!bestBack || s > bestBack.score) bestBack = { oldM: cand, score: s };
    }
    if (!bestBack || bestBack.oldM !== oldM) continue;
    events.push({
      kind: 'RenameModel',
      from: oldM.name,
      to: best.newM.name,
      appName: oldM.appName,
      confidence: Number(best.score.toFixed(3)),
    });
    // Emit any inner changes between the renamed pair.
    const inner = diffModelFields(oldM, best.newM, threshold);
    if (inner.length > 0) {
      events.push({
        kind: 'ModifyModel',
        model: best.newM.name,
        appName: best.newM.appName,
        changes: inner.sort((a, b) => cmpFieldChange(a, b)),
      });
    }
    takenNew.add(`${best.newM.appName}.${best.newM.name}`);
    takenOld.add(`${oldM.appName}.${oldM.name}`);
  }

  // Pass 3: unmatched leftovers are true adds/drops.
  for (const m of oldIx.all) {
    const qn = `${m.appName}.${m.name}`;
    if (matchedOld.has(qn) || takenOld.has(qn)) continue;
    events.push({ kind: 'DropModel', model: m.name, appName: m.appName });
  }
  for (const m of newIx.all) {
    const qn = `${m.appName}.${m.name}`;
    if (matchedNew.has(qn) || takenNew.has(qn)) continue;
    events.push({ kind: 'AddModel', model: m.name, appName: m.appName });
  }

  return events.sort((a, b) => cmpModelChange(a, b));
}

/* ---------------------------  ordering  ------------------------------ */

const MODEL_KIND_ORDER: Record<ModelChange['kind'], number> = {
  AddModel: 0,
  DropModel: 1,
  RenameModel: 2,
  ModifyModel: 3,
};

function cmpModelChange(a: ModelChange, b: ModelChange): number {
  const d = MODEL_KIND_ORDER[a.kind] - MODEL_KIND_ORDER[b.kind];
  if (d !== 0) return d;
  const an = 'model' in a ? a.model : a.from;
  const bn = 'model' in b ? b.model : b.from;
  return an.localeCompare(bn);
}

const FIELD_KIND_ORDER: Record<FieldChange['kind'], number> = {
  AddField: 0,
  DropField: 1,
  RenameField: 2,
  ChangeFieldType: 3,
  ChangeRelation: 4,
  ChangeFieldOption: 5,
  PartialUniqueConstraint: 6,
};

function cmpFieldChange(a: FieldChange, b: FieldChange): number {
  const d = FIELD_KIND_ORDER[a.kind] - FIELD_KIND_ORDER[b.kind];
  if (d !== 0) return d;
  const an = 'name' in a ? a.name : a.from;
  const bn = 'name' in b ? b.name : b.from;
  return an.localeCompare(bn);
}

/* --------------------------  markdown export  ------------------------ */

/**
 * Render a diff as a markdown fragment suitable for PR descriptions.
 * Grouped by model, one bullet per event. Includes a legend at the top.
 */
export function diffToMarkdown(events: ModelChange[]): string {
  if (events.length === 0) return '_No schema changes._\n';
  const lines: string[] = [];
  lines.push('### Schema changes');
  lines.push('');
  const emoji: Record<ModelChange['kind'], string> = {
    AddModel: '➕',
    DropModel: '➖',
    RenameModel: '✏️',
    ModifyModel: '📝',
  };
  const fieldEmoji: Record<FieldChange['kind'], string> = {
    AddField: '  ➕',
    DropField: '  ➖',
    RenameField: '  ✏️',
    ChangeFieldType: '  🔄',
    ChangeRelation: '  🔗',
    ChangeFieldOption: '  ⚙️',
    PartialUniqueConstraint: '  🔒',
  };
  for (const ev of events) {
    switch (ev.kind) {
      case 'AddModel':
        lines.push(`- ${emoji.AddModel} **${ev.appName}.${ev.model}** — new model`);
        break;
      case 'DropModel':
        lines.push(`- ${emoji.DropModel} **${ev.appName}.${ev.model}** — dropped`);
        break;
      case 'RenameModel':
        lines.push(
          `- ${emoji.RenameModel} **${ev.appName}.${ev.from}** → **${ev.to}** _(rename, confidence ${ev.confidence})_`,
        );
        break;
      case 'ModifyModel':
        lines.push(`- ${emoji.ModifyModel} **${ev.appName}.${ev.model}**`);
        for (const c of ev.changes) {
          switch (c.kind) {
            case 'AddField':
              lines.push(`${fieldEmoji.AddField} \`${c.name}\` (${c.type})`);
              break;
            case 'DropField':
              lines.push(`${fieldEmoji.DropField} \`${c.name}\` (${c.type})`);
              break;
            case 'RenameField':
              lines.push(
                `${fieldEmoji.RenameField} \`${c.from}\` → \`${c.to}\` _(${c.type}, confidence ${c.confidence})_`,
              );
              break;
            case 'ChangeFieldType':
              lines.push(
                `${fieldEmoji.ChangeFieldType} \`${c.name}\`: ${c.from} → ${c.to}`,
              );
              break;
            case 'ChangeRelation':
              lines.push(
                `${fieldEmoji.ChangeRelation} \`${c.name}\`: ${c.from} → ${c.to}`,
              );
              break;
            case 'ChangeFieldOption':
              lines.push(
                `${fieldEmoji.ChangeFieldOption} \`${c.name}.${c.option}\`: ${c.from} → ${c.to}`,
              );
              break;
            case 'PartialUniqueConstraint':
              lines.push(
                `${fieldEmoji.PartialUniqueConstraint} \`${c.name || '(unnamed)'}\`: UniqueConstraint(fields=[${c.fields}], condition=${c.condition})`,
              );
              break;
          }
        }
        break;
    }
  }
  lines.push('');
  return lines.join('\n');
}
