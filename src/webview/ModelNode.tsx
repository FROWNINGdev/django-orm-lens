import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { WireField } from './types';

export interface ModelNodeData {
  app: string;
  model: string;
  fields: WireField[];
  filePath: string;
  lineNumber: number;
  fieldCount: number;
  highlighted: boolean;
  dimmed: boolean;
  /** When true, scalar fields are listed under the keys. */
  expanded?: boolean;
  /** `Meta.managed = False`. */
  unmanaged?: boolean;
  [key: string]: unknown;
}

const IMPLICIT_PK: WireField = {
  name: 'id',
  type: 'AutoField',
  isRelation: false,
  primaryKey: true,
  lineNumber: -1,
};

export function isKeyField(field: WireField): boolean {
  return field.primaryKey === true || field.isRelation;
}

/** Primary key first, then relations. An implicit `id` stands in when the model declares no primary key. */
export function orderedKeyFields(fields: WireField[]): WireField[] {
  const declared = fields.filter(isKeyField);
  const keys = declared.some((field) => field.primaryKey) ? declared : [IMPLICIT_PK, ...declared];
  return [...keys.filter((field) => field.primaryKey), ...keys.filter((field) => !field.primaryKey)];
}

/** Rows reserved while the node is collapsed: keys, plus one row when more fields are hidden. */
export function collapsedFieldCount(fields: WireField[]): number {
  const hidden = fields.filter((field) => !isKeyField(field)).length;
  return orderedKeyFields(fields).length + (hidden > 0 ? 1 : 0);
}

const TYPE_LABELS: Record<string, string> = {
  AutoField: 'serial',
  BigAutoField: 'bigint',
  SmallAutoField: 'smallint',
  IntegerField: 'int',
  BigIntegerField: 'bigint',
  SmallIntegerField: 'smallint',
  PositiveIntegerField: 'int',
  PositiveSmallIntegerField: 'smallint',
  PositiveBigIntegerField: 'bigint',
  TinyIntegerField: 'tinyint',
  PositiveTinyIntegerField: 'tinyint',
  CharField: 'varchar',
  TextField: 'text',
  SlugField: 'slug',
  EmailField: 'email',
  URLField: 'url',
  BooleanField: 'bool',
  DateField: 'date',
  DateTimeField: 'datetime',
  TimeField: 'time',
  DurationField: 'duration',
  DecimalField: 'decimal',
  FloatField: 'float',
  UUIDField: 'uuid',
  JSONField: 'json',
  FileField: 'file',
  ImageField: 'image',
  BinaryField: 'bytes',
  NormalTextField: 'text',
};

function fieldMark(field: WireField): { label: string; kind: string; title: string } {
  if (field.primaryKey) {
    return {
      label: 'PK',
      kind: 'pk',
      title: field.lineNumber < 0 ? 'Implicit primary key' : 'Primary key',
    };
  }
  switch (field.relationKind) {
    case 'ForeignKey':
      return { label: 'FK', kind: 'fk', title: 'ForeignKey' };
    case 'OneToOneField':
      return { label: '1:1', kind: 'o2o', title: 'OneToOneField' };
    case 'ManyToManyField':
      return { label: 'M2M', kind: 'm2m', title: 'ManyToManyField' };
    default:
      return field.isRelation
        ? { label: 'FK', kind: 'fk', title: field.relationKind ?? 'Relation' }
        : { label: '', kind: 'plain', title: field.type };
  }
}

function fieldTypeLabel(field: WireField): string {
  if (field.isRelation) {
    if (!field.relatedModel || field.relatedModel === 'self') return 'self';
    return field.relatedModel.split('.').pop() ?? field.relatedModel;
  }
  return TYPE_LABELS[field.type] ?? field.type.replace(/Field$/, '').toLowerCase();
}

function ModelNodeInner({ data }: NodeProps) {
  const d = data as ModelNodeData;
  const keys = orderedKeyFields(d.fields);
  const rest = d.fields.filter((field) => !isKeyField(field));
  const shown = d.expanded ? [...keys, ...rest] : keys;
  const style: React.CSSProperties = {
    opacity: d.dimmed ? 0.28 : 1,
  };
  return (
    <div
      className={`dol-node${d.expanded ? ' dol-node-expanded' : ''}${d.highlighted ? ' dol-node-selected' : ''}${d.unmanaged ? ' dol-node-unmanaged' : ''}`}
      style={style}
    >
      <Handle type="target" position={Position.Left} className="dol-handle" />
      <div className="dol-node-header" title={`${d.app}.${d.model}`}>
        <span className="dol-node-titles">
          <span className="dol-node-app">
            {d.app}
            {d.unmanaged && <span className="dol-node-flag">unmanaged</span>}
          </span>
          <span className="dol-node-name">{d.model}</span>
        </span>
        {rest.length > 0 && (
          <span className="dol-node-toggle" aria-hidden="true">
            {d.expanded ? '▾' : '▸'}
          </span>
        )}
      </div>
      <div className="dol-node-body">
        {shown.map((f) => {
          const mark = fieldMark(f);
          return (
            <div className={`dol-node-field dol-field-${mark.kind}`} key={`${f.name}-${f.lineNumber}`}>
              <span className="dol-field-key" title={mark.title}>
                {mark.label}
              </span>
              <span className="dol-field-name" title={f.name}>
                {f.name}
              </span>
              <span className="dol-field-type" title={f.isRelation ? f.relatedModel ?? f.type : f.type}>
                {fieldTypeLabel(f)}
              </span>
            </div>
          );
        })}
        {rest.length > 0 && (
          <div className="dol-node-more">
            {d.expanded ? 'Hide fields' : `${rest.length} field${rest.length === 1 ? '' : 's'}`}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="dol-handle" />
    </div>
  );
}

export const ModelNode = memo(ModelNodeInner);
