import ELK, { type ElkNode, type ElkExtendedEdge } from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from '@xyflow/react';

const elk = new ELK();

const DEFAULT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.layered.spacing.nodeNodeBetweenLayers': '110',
  'elk.spacing.nodeNode': '70',
  'elk.padding': '[top=32,left=32,bottom=32,right=32]',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  'elk.edgeRouting': 'ORTHOGONAL',
};

// Rough per-node size so ELK knows how much room to reserve.
// Header ~44px, each field row ~24px, footer padding ~20px.
export function measureNode(fieldCount: number): { width: number; height: number } {
  const width = 260;
  const height = 44 + 20 + Math.max(1, fieldCount) * 24;
  return { width, height: Math.min(height, 520) };
}

export async function autoLayout(
  nodes: Node[],
  edges: Edge[]
): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const elkNodes: ElkNode[] = nodes.map((n) => {
    const fc = (n.data as { fieldCount?: number } | undefined)?.fieldCount ?? 1;
    const { width, height } = measureNode(fc);
    return { id: n.id, width, height };
  });
  const elkEdges: ElkExtendedEdge[] = edges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  const graph: ElkNode = {
    id: 'root',
    layoutOptions: DEFAULT_OPTIONS,
    children: elkNodes,
    edges: elkEdges,
  };

  const laidOut = await elk.layout(graph);
  const positioned = new Map<string, { x: number; y: number }>();
  for (const child of laidOut.children ?? []) {
    positioned.set(child.id, { x: child.x ?? 0, y: child.y ?? 0 });
  }
  return {
    nodes: nodes.map((n) => {
      const pos = positioned.get(n.id);
      return pos ? { ...n, position: pos } : n;
    }),
    edges,
  };
}
