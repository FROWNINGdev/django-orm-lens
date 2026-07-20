import { StrictMode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type NodeTypes,
} from '@xyflow/react';
import reactFlowStyles from '@xyflow/react/dist/style.css';
import styles from './styles.css';
import { toPng, toSvg } from 'html-to-image';
import { ModelNode, type ModelNodeData } from './ModelNode';
import { autoLayout } from './layout';
import type { WireField, WireIndex, WireModel, ExtensionMessage, VsCodeApi } from './types';

// Inject bundled stylesheets. Esbuild loads .css as text via the build script
// (--loader:.css=text) so we get raw CSS strings we can push into <style> tags.
// Ordering matters: React Flow's base styles first, then our overrides.
if (typeof document !== 'undefined' && !document.getElementById('dol-inline-styles')) {
  const rfEl = document.createElement('style');
  rfEl.id = 'dol-rf-styles';
  rfEl.textContent = reactFlowStyles;
  document.head.appendChild(rfEl);
  const el = document.createElement('style');
  el.id = 'dol-inline-styles';
  el.textContent = styles;
  document.head.appendChild(el);
}

const NODE_TYPES: NodeTypes = { model: ModelNode };

// Deterministic HSL color per app name — used to tint minimap nodes so users
// can eyeball which cluster belongs to which app at a glance.
function hashString(input: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

function colorForApp(app: string): string {
  const hue = hashString(app) % 360;
  return `hsl(${hue}, 55%, 55%)`;
}

interface EdgeStyleSpec {
  color: string;
  dashed?: boolean;
  label?: string;
}

function edgeStyle(field: WireField): EdgeStyleSpec {
  if (field.relationKind === 'ManyToManyField') {
    return {
      color: 'var(--dol-color-m2m)',
      label: field.throughModel ? `through=${field.throughModel}` : 'M2M',
    };
  }
  if (field.relationKind === 'OneToOneField') {
    return { color: 'var(--dol-color-o2o)', label: '1:1' };
  }
  // ForeignKey — colour by on_delete
  const od = (field.onDelete ?? '').toUpperCase();
  if (od === 'SET_NULL' || od === 'SET_DEFAULT' || od === 'SET') {
    return { color: 'var(--dol-color-fk-setnull)', dashed: true, label: od };
  }
  if (od === 'PROTECT' || od === 'RESTRICT' || od === 'DO_NOTHING') {
    return { color: 'var(--dol-color-fk-protect)', label: od };
  }
  return { color: 'var(--dol-color-fk-cascade)', label: od || 'CASCADE' };
}

interface BuiltGraph {
  nodes: Node[];
  edges: Edge[];
}

function buildGraph(index: WireIndex): BuiltGraph {
  const nodeIdFor = (app: string, model: string) => `${app}::${model}`;
  const modelByName = new Map<string, { app: string; model: WireModel }>();
  for (const app of index.apps) {
    for (const m of app.models) {
      modelByName.set(m.name, { app: app.name, model: m });
    }
  }

  const nodes: Node[] = [];
  for (const app of index.apps) {
    for (const model of app.models) {
      const nodeData: ModelNodeData = {
        app: app.name,
        model: model.name,
        fields: model.fields,
        filePath: model.filePath,
        lineNumber: model.lineNumber,
        fieldCount: model.fields.length,
        highlighted: false,
        dimmed: false,
      };
      nodes.push({
        id: nodeIdFor(app.name, model.name),
        type: 'model',
        position: { x: 0, y: 0 },
        data: nodeData as unknown as Record<string, unknown>,
      });
    }
  }

  const edges: Edge[] = [];
  const seenEdgeIds = new Set<string>();
  for (const app of index.apps) {
    for (const model of app.models) {
      const sourceId = nodeIdFor(app.name, model.name);
      for (const f of model.fields) {
        if (!f.isRelation || !f.relatedModel) continue;
        // Resolve settings.AUTH_USER_MODEL → workspace User model name so
        // edges land on the real User node instead of vanishing.
        const rawTail = f.relatedModel.split('.').pop() ?? '';
        const targetShort =
          f.relatedModel === 'self'
            ? model.name
            : rawTail === 'AUTH_USER_MODEL' && index.userModelName
              ? index.userModelName
              : rawTail;
        const targetInfo = modelByName.get(targetShort);
        if (!targetInfo) continue;
        const targetId = nodeIdFor(targetInfo.app, targetInfo.model.name);
        const style = edgeStyle(f);
        const baseId = `${sourceId}--${f.name}--${targetId}`;
        let edgeId = baseId;
        let n = 1;
        while (seenEdgeIds.has(edgeId)) edgeId = `${baseId}#${++n}`;
        seenEdgeIds.add(edgeId);
        edges.push({
          id: edgeId,
          source: sourceId,
          target: targetId,
          animated: false,
          label: `${f.name}${style.label ? ` · ${style.label}` : ''}`,
          labelStyle: { fill: 'var(--dol-node-text)', fontSize: 10 },
          labelBgPadding: [4, 3],
          labelBgBorderRadius: 3,
          labelBgStyle: { fill: 'var(--dol-node-bg)', fillOpacity: 0.85 },
          style: {
            stroke: style.color,
            strokeDasharray: style.dashed ? '5 4' : undefined,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: style.color,
            width: 18,
            height: 18,
          },
        });
      }
    }
  }
  return { nodes, edges };
}

interface GraphAppProps {
  vscode: VsCodeApi;
  initialIndex: WireIndex | null;
}

function GraphApp({ vscode, initialIndex }: GraphAppProps) {
  const [index, setIndex] = useState<WireIndex | null>(initialIndex);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onMsg = (event: MessageEvent<ExtensionMessage>) => {
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type === 'index') {
        setIndex(data.payload);
      } else if (data.type === 'theme') {
        document.body.classList.toggle('dol-light', data.payload === 'light');
      }
    };
    window.addEventListener('message', onMsg);
    vscode.postMessage({ type: 'ready' });
    return () => window.removeEventListener('message', onMsg);
  }, [vscode]);

  useEffect(() => {
    if (!index) return;
    document.body.classList.toggle('dol-light', index.theme === 'light');
    const { nodes: builtNodes, edges: builtEdges } = buildGraph(index);
    if (builtNodes.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }
    let cancelled = false;
    autoLayout(builtNodes, builtEdges)
      .then((laid) => {
        if (cancelled) return;
        setNodes(laid.nodes);
        setEdges(laid.edges);
      })
      .catch(() => {
        if (cancelled) return;
        // Fallback: grid layout if elk fails.
        const cols = Math.max(1, Math.ceil(Math.sqrt(builtNodes.length)));
        setNodes(
          builtNodes.map((n, i) => ({
            ...n,
            position: { x: (i % cols) * 320, y: Math.floor(i / cols) * 280 },
          }))
        );
        setEdges(builtEdges);
      });
    return () => {
      cancelled = true;
    };
  }, [index, setNodes, setEdges]);

  // Apply highlight state to node/edge data whenever selection changes.
  useEffect(() => {
    setNodes((curr) =>
      curr.map((n) => {
        const connected =
          selectedId === null ||
          n.id === selectedId ||
          edges.some(
            (e) =>
              (e.source === selectedId && e.target === n.id) ||
              (e.target === selectedId && e.source === n.id)
          );
        const nd = n.data as ModelNodeData;
        return {
          ...n,
          data: {
            ...nd,
            highlighted: n.id === selectedId,
            dimmed: selectedId !== null && !connected,
          } as unknown as Record<string, unknown>,
        };
      })
    );
    setEdges((curr) =>
      curr.map((e) => {
        const active =
          selectedId === null || e.source === selectedId || e.target === selectedId;
        return {
          ...e,
          animated: active && selectedId !== null,
          style: {
            ...(e.style ?? {}),
            opacity: active ? 1 : 0.15,
          },
        };
      })
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
    setSelectedId((prev) => (prev === node.id ? null : node.id));
  }, []);

  const onNodeDoubleClick = useCallback<NodeMouseHandler>(
    (_, node) => {
      const d = node.data as ModelNodeData;
      vscode.postMessage({
        type: 'jumpToModel',
        filePath: d.filePath,
        lineNumber: d.lineNumber,
      });
    },
    [vscode]
  );

  const onPaneClick = useCallback(() => setSelectedId(null), []);

  const runExport = useCallback(
    async (format: 'png' | 'svg') => {
      setExportOpen(false);
      const el = canvasRef.current?.querySelector<HTMLElement>('.react-flow__viewport');
      const wrap = canvasRef.current?.querySelector<HTMLElement>('.react-flow');
      const target = wrap ?? el;
      if (!target) return;
      try {
        const bg =
          getComputedStyle(document.documentElement).getPropertyValue('--dol-bg').trim() ||
          '#0f172a';
        const data =
          format === 'png'
            ? await toPng(target, { pixelRatio: 2, backgroundColor: bg, cacheBust: true })
            : await toSvg(target, { backgroundColor: bg, cacheBust: true });
        vscode.postMessage({ type: 'export', format, payload: data });
      } catch (err) {
        // Silently ignore — extension side will show its own message if user
        // triggers download and it fails to write.
        console.warn('export failed', err);
      }
    },
    [vscode]
  );

  const stats = useMemo(() => {
    if (!index) return { apps: 0, models: 0 };
    let models = 0;
    for (const a of index.apps) models += a.models.length;
    return { apps: index.apps.length, models };
  }, [index]);

  const workspaceName = index?.workspaceName ?? 'workspace';
  const hasModels = nodes.length > 0;

  return (
    <div className="dol-app">
      <header className="dol-header">
        <div className="dol-header-title">
          Django ORM Lens<span className="dol-title-sep">·</span>
          {workspaceName}
        </div>
        <div className="dol-header-actions">
          <span className="dol-badge">
            {stats.apps} app{stats.apps === 1 ? '' : 's'} · {stats.models} model
            {stats.models === 1 ? '' : 's'}
          </span>
          <button
            className="dol-btn"
            type="button"
            onClick={() => vscode.postMessage({ type: 'ready' })}
            title="Ask the extension to rescan"
          >
            Refresh
          </button>
          <div className="dol-export">
            <button
              className="dol-btn"
              type="button"
              onClick={() => setExportOpen((v) => !v)}
              aria-haspopup="menu"
              aria-expanded={exportOpen}
            >
              Export ▾
            </button>
            {exportOpen && (
              <div className="dol-export-menu" role="menu">
                <button type="button" onClick={() => runExport('png')}>
                  Export as PNG
                </button>
                <button type="button" onClick={() => runExport('svg')}>
                  Export as SVG
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <div className="dol-canvas" ref={canvasRef}>
        {hasModels ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onPaneClick={onPaneClick}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="rgba(148,163,184,0.15)" />
            <Controls
              showInteractive={false}
              showZoom
              showFitView
            />
            <MiniMap
              pannable
              zoomable
              position="bottom-right"
              style={{ width: 160, height: 110 }}
              nodeColor={(n) => {
                const d = n.data as ModelNodeData | undefined;
                if (d?.highlighted) return 'var(--dol-accent)';
                return d?.app ? colorForApp(d.app) : 'var(--dol-node-border)';
              }}
              nodeStrokeColor={(n) => {
                const d = n.data as ModelNodeData | undefined;
                return d?.app ? colorForApp(d.app) : 'var(--dol-node-border)';
              }}
              nodeStrokeWidth={2}
              maskColor="rgba(15, 23, 42, 0.55)"
            />
            <div className="dol-legend">
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ background: 'var(--dol-color-fk)' }} />
                FK / CASCADE
              </span>
              <span className="dol-legend-item">
                <span
                  className="dol-legend-swatch"
                  style={{ background: 'var(--dol-color-fk-setnull)' }}
                />
                SET_NULL
              </span>
              <span className="dol-legend-item">
                <span
                  className="dol-legend-swatch"
                  style={{ background: 'var(--dol-color-fk-protect)' }}
                />
                PROTECT
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ background: 'var(--dol-color-o2o)' }} />
                1:1
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ background: 'var(--dol-color-m2m)' }} />
                M2M
              </span>
            </div>
          </ReactFlow>
        ) : (
          <div className="dol-empty-state">
            No models to diagram yet — open a Django project with a{' '}
            <code>models.py</code> file.
          </div>
        )}
      </div>
    </div>
  );
}

function mount() {
  const rootEl = document.getElementById('dol-root');
  if (!rootEl) return;
  const vscode = window.acquireVsCodeApi();
  const initial = window.__INITIAL_INDEX__ ?? null;
  createRoot(rootEl).render(
    <StrictMode>
      <ReactFlowProvider>
        <GraphApp vscode={vscode} initialIndex={initial} />
      </ReactFlowProvider>
    </StrictMode>
  );
}

mount();
