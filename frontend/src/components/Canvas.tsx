import { useCallback, useEffect, useMemo, useState } from 'react'
import { useThemeVar } from '../lib/useThemeVar'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Icon from './Icon'
import { useAgents } from '../context/AgentContext'
import {
  agentTitle,
  layoutPipeline,
  type FlowNode,
  type NodeConfig,
} from '../data/flowNodes'

function PipelineNodeView({ data }: NodeProps<FlowNode>) {
  const config = data as NodeConfig
  const isKnowledge = config.agent === 'ingestion' && config.mode === 'knowledge'
  const isOutput = config.agent === 'output'
  const ports = config.ports.length ? config.ports : ['default']
  const status = config.runStatus
  return (
    <div
      className={`neu-raised lift min-w-[200px] rounded-xl p-4 ${isKnowledge ? 'border-dashed' : ''} ${
        status === 'running' ? 'anim-decide-breathe' : ''
      }`}
    >
      <Handle type="target" position={Position.Top} id="default" className="!bg-tertiary-fixed-dim" />
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--ey-line)] bg-surface">
          <Icon
            name={config.icon}
            className={isOutput ? 'text-primary-fixed-dim' : 'text-tertiary-fixed-dim'}
          />
        </div>
        <div className="min-w-0">
          <div className="truncate font-label-md text-on-surface">{config.label}</div>
          <div className="mt-1 font-mono-label text-on-surface-variant">
            {agentTitle(config.agent, config.mode)}
            {config.mode ? ` · ${config.mode}` : ''}
          </div>
        </div>
      </div>
      {status && (
        <div
          className={`mt-3 inline-flex rounded-full border px-2 py-0.5 font-mono-label uppercase tracking-wider ${
            status === 'ok'
              ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-500'
              : status === 'error'
                ? 'border-red-500/50 bg-red-500/10 text-red-500'
                : status === 'skipped'
                  ? 'border-[var(--ey-line)] text-on-surface-variant'
                  : 'border-primary-fixed-dim/40 bg-[color-mix(in_srgb,var(--ey-accent)_12%,transparent)] text-primary-fixed-dim'
          }`}
        >
          {status}
        </div>
      )}
      {ports.map((port, index) => (
        <Handle
          key={port}
          type="source"
          position={Position.Bottom}
          id={port}
          className="!bg-tertiary-fixed-dim"
          style={{ left: `${((index + 1) / (ports.length + 1)) * 100}%` }}
          title={port}
        />
      ))}
    </div>
  )
}

const nodeTypes = { pipeline: PipelineNodeView }

export default function Canvas() {
  const { pipeline, selectNode, run } = useAgents()
  const gridColor = useThemeVar('--ey-grid', '#14213d')
  const edgeStroke = useThemeVar('--ey-edge', '#14213d')
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark',
  )

  useEffect(() => {
    const read = () => {
      setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark')
    }
    read()
    const observer = new MutationObserver(read)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  const laid = useMemo(() => {
    const statusByNode = new Map((run?.steps ?? []).map((s) => [s.node_id, s.status]))
    const { nodes, edges } = layoutPipeline(pipeline, [], theme)
    return {
      nodes: nodes.map((n) => ({
        ...n,
        data: { ...n.data, runStatus: statusByNode.get(n.id) },
      })),
      edges,
    }
  }, [pipeline, run, theme])

  const [nodes, setNodes, onNodesChange] = useNodesState(laid.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(laid.edges)

  useEffect(() => {
    setNodes(laid.nodes)
    setEdges(laid.edges)
  }, [laid, setEdges, setNodes])

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string }) => {
      selectNode(node.id)
    },
    [selectNode],
  )

  return (
    <div className="relative h-full w-full border-l border-[var(--ey-line)] bg-background">
      {pipeline.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
          <div className="neu-raised rise max-w-sm rounded-3xl p-6 text-center">
            <Icon name="account_tree" className="anim-float text-[32px] text-primary-fixed-dim" />
            <p className="mt-3 font-body-md text-on-surface-variant">
              Canvas is empty. Describe your process and upload working data — nodes appear
              as Nexus learns enough to build them.
            </p>
          </div>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        defaultEdgeOptions={{
          animated: run?.status === 'running',
          style: { stroke: edgeStroke, strokeWidth: 2.5 },
          markerEnd: { type: 'arrowclosed', color: edgeStroke, width: 18, height: 18 },
        }}
        proOptions={{ hideAttribution: true }}
        className="bg-transparent"
      >
        <Background variant={BackgroundVariant.Lines} gap={28} size={1} lineWidth={1} color={gridColor} />
        <Controls showInteractive={false} className="!border-[var(--ey-line)] !bg-surface !shadow-none" />
      </ReactFlow>
    </div>
  )
}
