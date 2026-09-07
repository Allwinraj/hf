import type { Edge, Node } from '@xyflow/react'
import type { AgentKind, Pipeline, PipelineNode, RunStepView } from '../types/nexus'

export type NodeKind = AgentKind

export interface NodeConfig {
  [key: string]: unknown
  id: string
  label: string
  kind: AgentKind
  agent: AgentKind
  mode: string
  behaviorVersion: string
  ports: string[]
  config: Record<string, unknown>
  icon: string
  runStatus?: RunStepView['status'] | 'running'
}

export type FlowNode = Node<NodeConfig>

export const MATCHER_PORTS = ['matched', 'residuals', 'exceptions']
export const DECISION_PORTS = ['approved', 'flagged', 'escalated']

export function agentIcon(agent: AgentKind, mode?: string): string {
  if (agent === 'ingestion' && mode === 'knowledge') return 'menu_book'
  switch (agent) {
    case 'ingestion':
      return 'dataset'
    case 'matcher':
      return 'join_inner'
    case 'math':
      return 'functions'
    case 'decision':
      return 'gavel'
    case 'output':
      return 'output'
  }
}

export function agentTitle(agent: AgentKind, mode?: string): string {
  if (agent === 'ingestion' && mode === 'knowledge') return 'Knowledge ingest'
  if (agent === 'ingestion') return 'Data ingest'
  switch (agent) {
    case 'matcher':
      return 'Matcher'
    case 'math':
      return 'Rules & Math'
    case 'decision':
      return 'Decision'
    case 'output':
      return 'Output'
  }
}

export function sourcePorts(node: PipelineNode): string[] {
  const named = node.ports.filter((p) => (p.direction ?? 'out') === 'out').map((p) => p.name)
  if (named.length) return named
  if (node.agent === 'matcher') return MATCHER_PORTS
  if (node.agent === 'decision') return DECISION_PORTS
  return ['default']
}

export function layoutPipeline(
  pipeline: Pipeline,
  previous: FlowNode[] = [],
  theme: 'light' | 'dark' = 'dark',
): { nodes: FlowNode[]; edges: Edge[] } {
  const prevPos = new Map(previous.map((n) => [n.id, n.position]))
  const laneIndex: Record<AgentKind, number> = {
    ingestion: 0,
    matcher: 1,
    math: 2,
    decision: 3,
    output: 4,
  }
  const colCount: Record<number, number> = {}
  const nodes: FlowNode[] = pipeline.nodes.map((node) => {
    const lane = laneIndex[node.agent] ?? 0
    const col = colCount[lane] ?? 0
    colCount[lane] = col + 1
    const position = prevPos.get(node.id) ?? { x: 48 + col * 280, y: 48 + lane * 160 }
    return toFlowNode(node, position)
  })
  const edges: Edge[] = pipeline.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_port || 'default',
    targetHandle: edge.target_port || 'default',
    animated: true,
    style: { stroke: portColor(edge.source_port, theme), strokeWidth: 2.5 },
    markerEnd: {
      type: 'arrowclosed',
      color: portColor(edge.source_port, theme),
      width: 18,
      height: 18,
    },
  }))
  return { nodes, edges }
}

export function toFlowNode(
  node: PipelineNode,
  position: { x: number; y: number },
  runStatus?: NodeConfig['runStatus'],
): FlowNode {
  return {
    id: node.id,
    type: 'pipeline',
    position,
    data: {
      id: node.id,
      label: node.label || node.id,
      kind: node.agent,
      agent: node.agent,
      mode: node.mode,
      behaviorVersion: node.behavior_ref || '',
      ports: sourcePorts(node),
      config: node.config || {},
      icon: agentIcon(node.agent, node.mode),
      runStatus,
    },
  }
}

function portColor(port: string, theme: 'light' | 'dark' = 'dark'): string {
  const light = theme === 'light'
  switch (port) {
    case 'matched':
    case 'approved':
      return light ? '#166534' : '#4ade80'
    case 'residuals':
    case 'flagged':
      return light ? '#92400e' : '#fbbf24'
    case 'exceptions':
    case 'escalated':
      return light ? '#991b1b' : '#f87171'
    default:
      return light ? '#14213d' : '#fca311'
  }
}

export const initialNodes: FlowNode[] = []
export const initialEdges: Edge[] = []
