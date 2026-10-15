/**
 * Index and constraint names from aicore's MySQL schema editor.
 *
 * Mirrors `FieldIndexNaming` in
 * `aicore/db_backend/mysql/schema/naming.py`: drop a leading `ai_`, drop a
 * trailing `_id` on each column, then `prefix_table_columns`. Tables longer
 * than 25 characters compress, and the result stays within 64 characters.
 * `NamingSuggestionEngine` uses the same `assemble` for Meta indexes (`idx`)
 * and unique constraints (`uniq`). A unique constraint on `uuid` alone keeps
 * the full table name: `idx_uniq_<table>`.
 */

const TABLE_PREFIX = 'ai_';
const TABLE_NAME_THRESHOLD = 25;
const MAX_IDENTIFIER_LENGTH = 64;
const SHORT_WORD_THRESHOLD = 4;
const VOWELS = new Set(['a', 'e', 'i', 'o', 'u']);

export interface AssembledName {
  name: string;
  /** True when columns were dropped or sliced to fit 64 characters. */
  truncated: boolean;
}

export function tablePart(tableName: string): string {
  const stripped = tableName.startsWith(TABLE_PREFIX)
    ? tableName.slice(TABLE_PREFIX.length)
    : tableName;
  if (stripped.length <= TABLE_NAME_THRESHOLD) return stripped;
  return compressTableName(stripped);
}

function compressTableName(name: string): string {
  const parts = name.split('_').filter((part) => part.length > 0);
  if (parts.length > 1) return parts.map((part) => part[0]).join('');
  const word = parts[0] ?? name;
  if (word.length <= SHORT_WORD_THRESHOLD) return word;
  let skeleton = word[0];
  for (const char of word.slice(1)) {
    if (!VOWELS.has(char)) skeleton += char;
  }
  return skeleton.slice(0, SHORT_WORD_THRESHOLD);
}

function stripIdSuffix(column: string): string {
  return column.endsWith('_id') && column.length > 3 ? column.slice(0, -3) : column;
}

export function assembleName(
  prefix: string,
  tableName: string,
  columns: string[],
): AssembledName {
  const table = tablePart(tableName);
  let cols = columns.map(stripIdSuffix);
  const originalCount = cols.length;
  while (true) {
    const candidate = `${prefix}_${table}_${cols.join('_')}`;
    if (candidate.length <= MAX_IDENTIFIER_LENGTH) {
      return { name: candidate, truncated: cols.length < originalCount };
    }
    if (cols.length > 1) {
      cols = cols.slice(0, -1);
      continue;
    }
    const budget = MAX_IDENTIFIER_LENGTH - prefix.length - table.length - 2;
    return {
      name: `${prefix}_${table}_${cols[0].slice(0, Math.max(1, budget))}`,
      truncated: true,
    };
  }
}

/** `idx_uniq_<table>`, including a leading `ai_`. */
export function uuidUniqueName(tableName: string): string {
  return `idx_uniq_${tableName}`;
}

export function recommendedMetaName(
  kind: 'index' | 'unique',
  tableName: string,
  columns: string[],
): AssembledName {
  if (kind === 'unique' && columns.length === 1 && columns[0] === 'uuid') {
    return { name: uuidUniqueName(tableName), truncated: false };
  }
  return assembleName(kind === 'unique' ? 'uniq' : 'idx', tableName, columns);
}
