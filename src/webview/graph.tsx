import { Fragment, StrictMode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { ModelNode, collapsedFieldCount, type ModelNodeData } from './ModelNode';
import { autoLayout } from './layout';
import type { WireField, WireIndex, WireModel, ExtensionMessage, VsCodeApi } from './types';
import { acceptsMessage } from '../webviewMessages';

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

function stampExpanded(nodes: Node[], expanded: Set<string>): Node[] {
  return nodes.map((node) => {
    const open = expanded.has(node.id);
    const data = node.data as ModelNodeData;
    return {
      ...node,
      zIndex: open ? 10 : 0,
      data: { ...data, expanded: open } as unknown as Record<string, unknown>,
    };
  });
}

function buildGraph(index: WireIndex): BuiltGraph {
  const nodeIdFor = (app: string, model: string) => `${app}::${model}`;
  const modelsByName = new Map<string, { app: string; model: WireModel }[]>();
  for (const app of index.apps) {
    for (const m of app.models) {
      const list = modelsByName.get(m.name) ?? [];
      list.push({ app: app.name, model: m });
      modelsByName.set(m.name, list);
    }
  }
  const targetFor = (related: string, short: string, fromApp: string) => {
    const candidates = modelsByName.get(short) ?? [];
    if (candidates.length < 2) return candidates[0];
    const parts = related.split('.');
    const label = parts.length >= 2 ? parts[parts.length - 2] : fromApp;
    return (
      candidates.find((c) => c.app === label || c.model.appName === label) ??
      candidates.find((c) => c.app === fromApp) ??
      candidates[0]
    );
  };

  const nodes: Node[] = [];
  for (const app of index.apps) {
    for (const model of app.models) {
      const nodeData: ModelNodeData = {
        app: app.name,
        model: model.name,
        fields: model.fields,
        filePath: model.filePath,
        lineNumber: model.lineNumber,
        fieldCount: collapsedFieldCount(model.fields),
        highlighted: false,
        dimmed: false,
        unmanaged: model.unmanaged,
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
        const targetInfo = targetFor(f.relatedModel, targetShort, app.name);
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
          data: { caption: `${f.name}${style.label ? ` · ${style.label}` : ''}` },
          interactionWidth: 16,
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

interface PersistedGraphState {
  apps?: string[] | null;
  models?: string[] | null;
}

/** Field name and on_delete appear on hover, or on every line touching the selected model. */
function presentEdge(edge: Edge, selectedId: string | null, hoveredEdgeId: string | null): Edge {
  const caption = (edge.data as { caption?: string } | undefined)?.caption;
  const connected = selectedId !== null && (edge.source === selectedId || edge.target === selectedId);
  const hovered = edge.id === hoveredEdgeId;
  const active = selectedId === null || connected || hovered;
  const show = Boolean(caption) && (connected || hovered);
  return {
    ...edge,
    label: show ? caption : undefined,
    animated: active && selectedId !== null,
    labelStyle: {
      fill: 'var(--dol-node-text)',
      fontSize: 10,
      opacity: active ? 1 : 0.35,
    },
    labelBgStyle: { fill: 'var(--dol-node-bg)', fillOpacity: active ? 0.92 : 0.35 },
    style: {
      ...(edge.style ?? {}),
      opacity: active ? 1 : 0.15,
    },
  };
}

interface PickOption {
  id: string;
  label: string;
  detail?: string;
  group?: string;
}

/** `null` means every id. An array is an explicit subset, including none. */
export function filterIndex(
  index: WireIndex,
  apps: string[] | null,
  models: string[] | null
): WireIndex {
  const appSet = apps === null ? null : new Set(apps);
  const modelSet = models === null ? null : new Set(models);
  return {
    ...index,
    apps: index.apps
      .filter((app) => appSet === null || appSet.has(app.name))
      .map((app) => ({
        ...app,
        models:
          modelSet === null
            ? app.models
            : app.models.filter((model) => modelSet.has(`${app.name}/${model.name}`)),
      }))
      .filter((app) => app.models.length > 0),
  };
}

function selectionForFocus(ids: string[]): { apps: string[]; models: string[] } {
  return {
    apps: [...new Set(ids.map((id) => id.slice(0, id.indexOf('/'))).filter(Boolean))],
    models: ids,
  };
}

function toggleSelection(current: string[] | null, id: string, allIds: string[]): string[] | null {
  const selected = new Set(current ?? allIds);
  if (selected.has(id)) selected.delete(id);
  else selected.add(id);
  if (selected.size === 0 || selected.size === allIds.length) {
    return selected.size === 0 ? [] : null;
  }
  return allIds.filter((item) => selected.has(item));
}

function MultiSelect({
  label,
  allLabel,
  noun,
  options,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  noun: string;
  options: PickOption[];
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const allIds = options.map((option) => option.id);
  const selected = new Set(value ?? allIds);
  const allChecked = allIds.length > 0 && (value === null || selected.size === allIds.length);
  const summary =
    options.length === 0 || selected.size === 0
      ? `No ${noun}`
      : allChecked
        ? label
        : selected.size === 1
          ? (options.find((option) => selected.has(option.id))?.label ?? label)
          : `${selected.size} ${noun}`;
  const needle = query.trim().toLocaleLowerCase();
  const visible = needle
    ? options.filter(
        (option) =>
          option.label.toLocaleLowerCase().includes(needle) ||
          (option.group ?? '').toLocaleLowerCase().includes(needle)
      )
    : options;
  const showGroups = new Set(visible.map((option) => option.group).filter(Boolean)).size > 1;

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as globalThis.Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="dol-picker" ref={rootRef}>
      <button
        type="button"
        className={allChecked ? 'dol-picker-btn' : 'dol-picker-btn dol-picker-on'}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${summary}`}
        title={summary}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="dol-picker-v">{summary}</span>
        <span className="dol-picker-caret" aria-hidden="true" />
      </button>
      {open && (
        <div className="dol-picker-menu" role="listbox" aria-multiselectable="true">
          {options.length > 8 && (
            <input
              type="search"
              value={query}
              placeholder="Filter…"
              aria-label={`Filter ${noun}`}
              onChange={(event) => setQuery(event.target.value)}
              autoFocus
            />
          )}
          <label className="dol-picker-row dol-picker-all">
            <input
              type="checkbox"
              checked={allChecked}
              ref={(element) => {
                if (element) element.indeterminate = !allChecked && selected.size > 0;
              }}
              onChange={() => onChange(allChecked ? [] : null)}
            />
            <span>{allLabel}</span>
            <em>{options.length}</em>
          </label>
          <div className="dol-picker-list">
            {visible.map((option, i) => (
              <Fragment key={option.id}>
                {showGroups && option.group && option.group !== visible[i - 1]?.group && (
                  <div className="dol-picker-group">{option.group}</div>
                )}
                <label className="dol-picker-row">
                  <input
                    type="checkbox"
                    checked={selected.has(option.id)}
                    onChange={() => onChange(toggleSelection(value, option.id, allIds))}
                  />
                  <span>{option.label}</span>
                  {option.detail && <em>{option.detail}</em>}
                </label>
              </Fragment>
            ))}
            {visible.length === 0 && <div className="dol-picker-empty">No matches</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function GraphApp({ vscode, initialIndex }: GraphAppProps) {
  const persisted = vscode.getState<PersistedGraphState>() ?? {};
  const openedOn = initialIndex?.focusModels ? selectionForFocus(initialIndex.focusModels) : undefined;
  const [index, setIndex] = useState<WireIndex | null>(initialIndex);
  const [selectedApps, setSelectedApps] = useState<string[] | null>(
    openedOn ? openedOn.apps : (persisted.apps ?? null)
  );
  const [selectedModels, setSelectedModels] = useState<string[] | null>(
    openedOn ? openedOn.models : (persisted.models ?? null)
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const selectedIdRef = useRef(selectedId);
  const hoveredEdgeRef = useRef(hoveredEdgeId);
  selectedIdRef.current = selectedId;
  hoveredEdgeRef.current = hoveredEdgeId;
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const expandedRef = useRef(expandedIds);
  expandedRef.current = expandedIds;
  const [exportOpen, setExportOpen] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const appOptions = useMemo<PickOption[]>(
    () =>
      (index?.apps ?? []).map((app) => ({
        id: app.name,
        label: app.name,
        detail: String(app.models.length),
      })),
    [index]
  );
  const modelOptions = useMemo<PickOption[]>(() => {
    if (!index) return [];
    const apps =
      selectedApps === null
        ? index.apps
        : index.apps.filter((app) => selectedApps.includes(app.name));
    return apps.flatMap((app) =>
      app.models.map((model) => ({
        id: `${app.name}/${model.name}`,
        label: model.name,
        detail: String(model.fields.length),
        group: app.name,
      }))
    );
  }, [index, selectedApps]);
  const filteredIndex = useMemo(
    () => (index ? filterIndex(index, selectedApps, selectedModels) : null),
    [index, selectedApps, selectedModels]
  );
  const narrowed = selectedApps !== null || selectedModels !== null;

  useEffect(() => {
    if (!index) return;
    const names = new Set(index.apps.map((app) => app.name));
    setSelectedApps((prev) => {
      if (prev === null) return null;
      const kept = prev.filter((name) => names.has(name));
      if (kept.length === prev.length) return prev;
      return kept.length === index.apps.length ? null : kept;
    });
  }, [index]);

  useEffect(() => {
    if (!index) return;
    const ids = new Set(modelOptions.map((option) => option.id));
    setSelectedModels((prev) => {
      if (prev === null) return null;
      const kept = prev.filter((id) => ids.has(id));
      if (kept.length === prev.length) return prev;
      return kept.length === modelOptions.length ? null : kept;
    });
  }, [index, modelOptions]);

  useEffect(() => {
    vscode.setState<PersistedGraphState>({
      apps: selectedApps,
      models: selectedModels,
    });
  }, [selectedApps, selectedModels, vscode]);

  useEffect(() => {
    setSelectedId(null);
  }, [selectedApps, selectedModels]);

  useEffect(() => {
    const onMsg = (event: MessageEvent<ExtensionMessage>) => {
      // Origin check — CodeQL js/missing-origin-check. The policy lives in
      // ../webviewMessages because src/webview/ is excluded from tsc and so
      // nothing in it can be required by a test; see the comment there for
      // why this compares `origin` rather than `source` (#55).
      if (!acceptsMessage(event, window.origin)) return;
      const data = event.data;
      if (data.type === 'index') {
        setIndex(data.payload);
        if (data.payload.focusModels) {
          const focus = selectionForFocus(data.payload.focusModels);
          setSelectedApps(focus.apps);
          setSelectedModels(focus.models);
        }
      } else if (data.type === 'theme') {
        document.body.classList.toggle('dol-light', data.payload === 'light');
      }
    };
    window.addEventListener('message', onMsg);
    vscode.postMessage({ type: 'ready' });
    return () => window.removeEventListener('message', onMsg);
  }, [vscode]);

  useEffect(() => {
    if (!filteredIndex) return;
    document.body.classList.toggle('dol-light', filteredIndex.theme === 'light');
    const { nodes: builtNodes, edges: builtEdges } = buildGraph(filteredIndex);
    if (builtNodes.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }
    let cancelled = false;
    autoLayout(builtNodes, builtEdges)
      .then((laid) => {
        if (cancelled) return;
        setNodes(stampExpanded(laid.nodes, expandedRef.current));
        setEdges(laid.edges.map((edge) => presentEdge(edge, selectedIdRef.current, hoveredEdgeRef.current)));
      })
      .catch(() => {
        if (cancelled) return;
        // Fallback: grid layout if elk fails.
        const cols = Math.max(1, Math.ceil(Math.sqrt(builtNodes.length)));
        setNodes(
          stampExpanded(
            builtNodes.map((n, i) => ({
              ...n,
              position: { x: (i % cols) * 320, y: Math.floor(i / cols) * 280 },
            })),
            expandedRef.current
          )
        );
        setEdges(builtEdges.map((edge) => presentEdge(edge, selectedIdRef.current, hoveredEdgeRef.current)));
      });
    return () => {
      cancelled = true;
    };
  }, [filteredIndex, setNodes, setEdges]);

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
        const expanded = expandedIds.has(n.id);
        return {
          ...n,
          zIndex: expanded ? 10 : 0,
          data: {
            ...nd,
            expanded,
            highlighted: n.id === selectedId,
            dimmed: selectedId !== null && !connected,
          } as unknown as Record<string, unknown>,
        };
      })
    );
    setEdges((curr) => curr.map((edge) => presentEdge(edge, selectedId, hoveredEdgeId)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, expandedIds, hoveredEdgeId]);

  const onNodeClick = useCallback<NodeMouseHandler>((_, node) => {
    setSelectedId((prev) => (prev === node.id ? null : node.id));
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(node.id)) next.delete(node.id);
      else next.add(node.id);
      return next;
    });
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

  const countIndex = useCallback((value: WireIndex | null) => {
    if (!value) return { apps: 0, models: 0 };
    let models = 0;
    for (const a of value.apps) models += a.models.length;
    return { apps: value.apps.length, models };
  }, []);
  const totalStats = useMemo(() => countIndex(index), [countIndex, index]);
  const visibleStats = useMemo(
    () => countIndex(filteredIndex),
    [countIndex, filteredIndex]
  );

  const workspaceName = index?.workspaceName ?? 'workspace';
  const hasModels = nodes.length > 0;
  const hasAnyModels = totalStats.models > 0;

  return (
    <div className="dol-app">
      <header className="dol-header">
        <div className="dol-header-title">
          ORM Synapse<span className="dol-title-sep">·</span>
          {workspaceName}
        </div>
        <div className="dol-filter-bar">
          <MultiSelect
            label="Apps"
            allLabel="All apps"
            noun="apps"
            options={appOptions}
            value={selectedApps}
            onChange={setSelectedApps}
          />
          <MultiSelect
            label="Models"
            allLabel="All models"
            noun="models"
            options={modelOptions}
            value={selectedModels}
            onChange={setSelectedModels}
          />
          {narrowed && (
            <button
              type="button"
              className="dol-picker-clear"
              title="Show every app and model"
              aria-label="Reset filter"
              onClick={() => {
                setSelectedApps(null);
                setSelectedModels(null);
              }}
            >
              ×
            </button>
          )}
        </div>
        <div className="dol-header-actions">
          <span className="dol-badge">
            {narrowed
              ? `${visibleStats.apps}/${totalStats.apps} apps · ${visibleStats.models}/${totalStats.models} models`
              : `${totalStats.apps} app${totalStats.apps === 1 ? '' : 's'} · ${totalStats.models} model${totalStats.models === 1 ? '' : 's'}`}
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
            onEdgeMouseEnter={(_, edge) => setHoveredEdgeId(edge.id)}
            onEdgeMouseLeave={() => setHoveredEdgeId(null)}
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
                <span className="dol-legend-swatch" style={{ borderTopColor: 'var(--dol-color-fk-cascade)' }} />
                CASCADE
              </span>
              <span className="dol-legend-item">
                <span
                  className="dol-legend-swatch dol-legend-dashed"
                  style={{ borderTopColor: 'var(--dol-color-fk-setnull)' }}
                />
                SET_NULL
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ borderTopColor: 'var(--dol-color-fk-protect)' }} />
                PROTECT
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ borderTopColor: 'var(--dol-color-o2o)' }} />
                1:1
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-swatch" style={{ borderTopColor: 'var(--dol-color-m2m)' }} />
                M2M
              </span>
              <span className="dol-legend-item">
                <span className="dol-legend-card" />
                unmanaged
              </span>
            </div>
          </ReactFlow>
        ) : (
          <div className="dol-empty-state">
            {hasAnyModels && narrowed ? (
              <>
                No models in this selection.{' '}
                <button
                  type="button"
                  className="dol-link-btn"
                  onClick={() => {
                    setSelectedApps(null);
                    setSelectedModels(null);
                  }}
                >
                  Reset filter
                </button>
              </>
            ) : (
              <>
                No models to diagram yet — open a Django project with a{' '}
                <code>models.py</code> file.
              </>
            )}
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
