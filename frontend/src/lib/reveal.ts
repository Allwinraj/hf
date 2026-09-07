import type { Pipeline, PipelineEdge, PipelineNode, ProgressiveReveal } from '../types/nexus'

function deepMerge(base: Record<string, unknown>, patch: Record<string, unknown>) {
  const out: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    const current = out[key]
    if (value && typeof value === 'object' && !Array.isArray(value) && current && typeof current === 'object' && !Array.isArray(current)) {
      out[key] = deepMerge(current as Record<string, unknown>, value as Record<string, unknown>)
    } else {
      out[key] = value
    }
  }
  return out
}

export function emptyPipeline(id = 'draft'): Pipeline {
  return { id, name: 'draft', version: '0.1', nodes: [], edges: [] }
}

export function applyReveal(pipeline: Pipeline, delta: ProgressiveReveal): Pipeline {
  const nodes = new Map(pipeline.nodes.map((node) => [node.id, node]))
  const edges = new Map(pipeline.edges.map((edge) => [edge.id, edge]))

  for (const id of delta.remove_node_ids) {
    nodes.delete(id)
    for (const [eid, edge] of [...edges.entries()]) {
      if (edge.source === id || edge.target === id) edges.delete(eid)
    }
  }
  for (const id of delta.remove_edge_ids) edges.delete(id)

  for (const node of delta.upsert_nodes) {
    const existing = nodes.get(node.id)
    if (!existing) {
      nodes.set(node.id, node)
    } else {
      nodes.set(node.id, {
        ...existing,
        ...node,
        config: { ...existing.config, ...node.config },
      })
    }
  }
  for (const edge of delta.upsert_edges) edges.set(edge.id, edge)
  for (const patch of delta.config_patches) {
    const node = nodes.get(patch.node_id)
    if (node) nodes.set(patch.node_id, { ...node, config: deepMerge(node.config, patch.config) })
  }

  return { ...pipeline, nodes: [...nodes.values()], edges: [...edges.values()] }
}

export function mergePipeline(current: Pipeline | null, incoming: Pipeline | null, reveal: ProgressiveReveal | null): Pipeline {
  if (incoming && incoming.nodes) return incoming
  const base = current ?? emptyPipeline()
  if (!reveal) return base
  return applyReveal(base, reveal)
}

export function upsertNodeConfig(pipeline: Pipeline, nodeId: string, config: Record<string, unknown>): Pipeline {
  return {
    ...pipeline,
    nodes: pipeline.nodes.map((node) =>
      node.id === nodeId ? { ...node, config: deepMerge(node.config, config) } : node,
    ),
  }
}

export type { PipelineNode, PipelineEdge }
