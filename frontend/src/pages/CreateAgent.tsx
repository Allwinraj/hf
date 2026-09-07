import { useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import Icon from '../components/Icon'
import IconNav from '../components/IconNav'
import Canvas from '../components/Canvas'
import ChatPanel from '../components/ChatPanel'
import ResizableSplit from '../components/ResizableSplit'
import NodeConfigPanel from '../components/NodeConfigPanel'
import ThemeToggle from '../components/ThemeToggle'
import { useAgents } from '../context/AgentContext'
import { api } from '../lib/api'

export default function CreateAgent() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const pipelineParam = params.get('pipeline')
  const {
    startSession,
    loadLibrary,
    pipelineName,
    setPipelineName,
    pipelineVersion,
    setPipelineVersion,
    confirmed,
    libraryPipelineId,
    selectedNodeId,
    selectNode,
    pipeline,
    syncNode,
    saveLibrary,
    run,
    busy,
    error,
    sessionId,
  } = useAgents()

  useEffect(() => {
    if (pipelineParam) void loadLibrary(pipelineParam)
    else void startSession()
  }, [loadLibrary, pipelineParam, startSession])

  const selected = pipeline.nodes.find((n) => n.id === selectedNodeId) ?? null
  const canSave = Boolean(confirmed && sessionId && !libraryPipelineId)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-container-lowest">
      <header className="z-20 flex h-16 shrink-0 items-center justify-between border-b border-[var(--ey-line)] bg-background px-gutter">
        <div className="flex items-center gap-4">
          <h1 className="font-headline-md text-headline-md text-accent-grad">Architect Studio</h1>
          <div className="h-4 w-px bg-[var(--ey-line)]" />
          <div className="hidden rounded-2xl border border-[var(--ey-line)] bg-surface p-1 md:flex md:gap-2">
            <input
              className="bg-transparent px-2 py-1 font-label-md text-label-md text-on-surface outline-none"
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              aria-label="Pipeline name"
            />
            <input
              className="w-20 bg-transparent px-2 py-1 font-mono-label text-on-surface-variant outline-none"
              value={pipelineVersion}
              onChange={(e) => setPipelineVersion(e.target.value)}
              aria-label="Version"
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          {error && <span className="max-w-xs truncate font-mono-label text-red-500">{error}</span>}
          {libraryPipelineId && (
            <button
              type="button"
              onClick={() => navigate(`/agents/${libraryPipelineId}`)}
              className="hover-tint flex items-center gap-2 rounded-xl border border-[var(--ey-line)] px-4 py-2 font-label-md text-on-surface"
            >
              <Icon name="chat" className="text-[18px]" />
              Run in chat
            </button>
          )}
          <button
            disabled={!canSave || busy}
            onClick={async () => {
              const saved = await saveLibrary()
              if (saved) navigate('/agents')
            }}
            className="cta-sheen flex items-center gap-2 rounded-xl bg-primary-container px-5 py-2 font-label-md text-on-primary-container transition-all hover:brightness-110 disabled:opacity-40"
          >
            <Icon name="save" className="text-[18px]" />
            Save
          </button>
        </div>
      </header>

      {run && (
        <div className="rise flex flex-wrap items-center gap-3 border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_8%,var(--ey-card))] px-gutter py-2">
          <span className="chip chip-accent font-mono-label">
            Run {run.id.slice(0, 8)} · {run.status}
          </span>
          {run.artifacts.map((name) => (
            <a
              key={name}
              href={api.artifactUrl(run.id, name)}
              className="hover-tint flex items-center gap-1.5 rounded-lg px-2 py-1 font-label-md text-primary-fixed-dim"
            >
              <Icon name="download" className="text-[16px]" />
              {name}
            </a>
          ))}
          <Link
            to={`/runs/${run.id}`}
            className="hover-tint flex items-center gap-1.5 rounded-lg px-2 py-1 font-label-md text-on-surface"
          >
            <Icon name="timeline" className="text-[16px]" />
            Open trace
          </Link>
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <IconNav />
        <ResizableSplit left={<ChatPanel />} right={<Canvas />} />
        {selected && (
          <div className="flex w-full max-w-md lg:w-96">
            <NodeConfigPanel
              node={selected}
              onSync={(id, config) => void syncNode(id, config)}
              onClose={() => selectNode(null)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
