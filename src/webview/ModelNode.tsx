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
  [key: string]: unknown;
}

function fieldGlyph(field: WireField): { text: string; color: string } {
  if (!field.isRelation) return { text: 'F', color: 'var(--dol-field-plain)' };
  switch (field.relationKind) {
    case 'ForeignKey':
      return { text: 'FK', color: 'var(--dol-color-fk)' };
    case 'OneToOneField':
      return { text: '1:1', color: 'var(--dol-color-o2o)' };
    case 'ManyToManyField':
      return { text: 'M2M', color: 'var(--dol-color-m2m)' };
    default:
      return { text: 'R', color: 'var(--dol-color-fk)' };
  }
}

function ModelNodeInner({ data }: NodeProps) {
  const d = data as ModelNodeData;
  const style: React.CSSProperties = {
    opacity: d.dimmed ? 0.35 : 1,
    boxShadow: d.highlighted
      ? '0 0 0 2px var(--dol-accent), 0 8px 24px rgba(0,0,0,0.25)'
      : '0 4px 14px rgba(0,0,0,0.18)',
    transition: 'opacity 120ms, box-shadow 120ms',
  };
  return (
    <div className="dol-node" style={style}>
      <Handle type="target" position={Position.Left} className="dol-handle" />
      <div className="dol-node-header" title={`${d.app}.${d.model}`}>
        <span className="dol-node-app">{d.app}</span>
        <span className="dol-node-dot">·</span>
        <span className="dol-node-name">{d.model}</span>
      </div>
      <div className="dol-node-body">
        {d.fields.length === 0 ? (
          <div className="dol-node-empty">no fields</div>
        ) : (
          d.fields.map((f) => {
            const g = fieldGlyph(f);
            return (
              <div className="dol-node-field" key={`${f.name}-${f.lineNumber}`}>
                <span
                  className="dol-field-badge"
                  style={{ background: g.color }}
                  title={f.isRelation ? f.relationKind ?? 'Relation' : 'Field'}
                >
                  {g.text}
                </span>
                <span className="dol-field-name">{f.name}</span>
                <span className="dol-field-type">{f.type}</span>
              </div>
            );
          })
        )}
      </div>
      <Handle type="source" position={Position.Right} className="dol-handle" />
    </div>
  );
}

export const ModelNode = memo(ModelNodeInner);
