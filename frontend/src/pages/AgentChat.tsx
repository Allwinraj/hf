import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import TopNav from '../components/TopNav'
import Icon from '../components/Icon'
import MarkdownBody from '../components/MarkdownBody'
import DashboardPanel from '../components/DashboardPanel'
import HowItWorksPanel from '../components/HowItWorksPanel'
import LineagePanel from '../components/LineagePanel'
import ProcessingState from '../components/ProcessingState'
import ReportsPanel from '../components/ReportsPanel'
import TypingDots from '../components/TypingDots'
import { api } from '../lib/api'
import type { DashboardView, FileSlot, LineageView, Pipeline, RunStreamEvent, RunView } from '../types/nexus'

type ViewId = 'dashboard' | 'how' | 'lineage' | 'reports'

interface ThinkingLine {
  node_id: string
  agent: string
  label: string
  status: 'running' | 'ok' | 'skipped' | 'error'
  message: string
}

interface Bubble {
  id: string
  role: 'assistant' | 'user'
  content: string
  thinking?: ThinkingLine[]
  pending?: boolean
}

function mergeLine(lines: ThinkingLine[], next: ThinkingLine): ThinkingLine[] {
  const index = lines.findIndex((line) => line.node_id === next.node_id)
  if (index < 0) return [...lines, next]
  const copy = [...lines]
  copy[index] = next
  return copy
}

function statusIcon(status: ThinkingLine['status'] | string) {
  if (status === 'running') return 'progress_activity'
  if (status === 'ok') return 'check_circle'
  if (status === 'skipped') return 'skip_next'
  if (status === 'error') return 'error'
  return 'circle'
}

const VIEWS: { id: ViewId; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'how', label: 'How it works', icon: 'account_tree' },
  { id: 'lineage', label: 'Lineage', icon: 'conversion_path' },
  { id: 'reports', label: 'Reports', icon: 'download' },
]

export default function AgentChat() {
  const { agentId } = useParams()
  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [slots, setSlots] = useState<FileSlot[]>([])
  const [missing, setMissing] = useState<string[]>([])
  const [messages, setMessages] = useState<Bubble[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [run, setRun] = useState<RunView | null>(null)
  const [view, setView] = useState<ViewId>('dashboard')
  const [dashboard, setDashboard] = useState<DashboardView | null>(null)
  const [lineage, setLineage] = useState<LineageView | null>(null)
  const [chatOpen, setChatOpen] = useState(true)
  const [preparing, setPreparing] = useState(false)
  const [progress, setProgress] = useState<ThinkingLine[]>([])
  const fileInput = useRef<HTMLInputElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const running = useRef(false)

  useEffect(() => {
    if (!agentId) return
    api
      .getPipeline(agentId)
      .then((body) => {
        setPipeline(body)
        const nextSlots = body.file_slots || []
        setSlots(nextSlots)
        setMissing(body.missing_files || nextSlots.map((s) => s.filename))
        setMessages([
          {
            id: 'hello',
            role: 'assistant',
            content:
              `This is ${body.name}. Attach the required files, then I will run the pipeline. ` +
              `After it finishes, use Dashboard, How it works, Lineage, and Reports in the sidebar.`,
          },
        ])
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load agent'))
  }, [agentId])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const loadResultViews = async (pipelineId: string, runId: string) => {
    try {
      const [nextDash, nextLineage] = await Promise.all([
        api.getDashboard(pipelineId, runId),
        api.getLineage(pipelineId, runId),
      ])
      setDashboard(nextDash)
      setLineage(nextLineage)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not load results')
    }
  }

  const startRun = async () => {
    if (!agentId || running.current) return
    running.current = true
    setBusy(true)
    setChatOpen(true)
    setError(null)
    setPreparing(true)
    setProgress([])
    const thinkingId = `think-${Date.now()}`
    setMessages((prev) => [
      ...prev,
      { id: thinkingId, role: 'assistant', content: 'Running the pipeline…', thinking: [] },
    ])
    const applyEvent = (event: RunStreamEvent) => {
      const starting = event.type === 'node_start'
      if ((!starting && event.type !== 'node_finish') || !event.node_id) return
      const next: ThinkingLine = {
        node_id: event.node_id,
        agent: event.agent || '',
        label: event.label || event.agent || event.node_id,
        status: starting ? 'running' : (event.status as ThinkingLine['status']) || 'ok',
        message: starting
          ? event.message || `Running ${event.label || event.agent}`
          : event.summary || event.message || event.skip_reason || event.error || '',
      }
      setProgress((prev) => mergeLine(prev, next))
      setMessages((prev) =>
        prev.map((message) =>
          message.id === thinkingId
            ? { ...message, thinking: mergeLine(message.thinking || [], next) }
            : message,
        ),
      )
    }
    try {
      const nextRun = await api.runLibraryStream(agentId, applyEvent)
      setRun(nextRun)
      setView('dashboard')
      setMessages((prev) => [
        ...prev.filter((message) => message.id !== thinkingId),
        {
          id: thinkingId,
          role: 'assistant',
          content: 'Run complete. Open Dashboard, How it works, Lineage, or Reports in the sidebar. Ask anything about this result.',
          thinking: prev.find((message) => message.id === thinkingId)?.thinking,
        },
      ])
      await loadResultViews(agentId, nextRun.id)
      setChatOpen(false)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Run failed')
    } finally {
      running.current = false
      setBusy(false)
      setPreparing(false)
    }
  }

  const onFiles = async (files: FileList) => {
    if (!agentId) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.uploadLibraryFiles(agentId, files)
      setMissing(result.missing_files)
      if (!result.missing_files.length) {
        setBusy(false)
        await startRun()
        return
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      if (!running.current) setBusy(false)
    }
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!agentId || busy) return
    const text = draft.trim()
    setDraft('')
    if (run && text) {
      setChatOpen(true)
      const pendingId = `a-${Date.now()}`
      setMessages((prev) => [
        ...prev,
        { id: `q-${Date.now()}`, role: 'user', content: text },
        { id: pendingId, role: 'assistant', content: '', pending: true },
      ])
      setBusy(true)
      setError(null)
      try {
        const body = await api.askLibrary(agentId, run.id, text, view)
        setMessages((prev) =>
          prev.map((message) =>
            message.id === pendingId ? { ...message, content: body.answer, pending: false } : message,
          ),
        )
      } catch (err) {
        setMessages((prev) => prev.filter((message) => message.id !== pendingId))
        setError(err instanceof Error ? err.message : 'Could not answer')
      } finally {
        setBusy(false)
      }
      return
    }
    if (!run) {
      if (text) {
        setMessages((prev) => [...prev, { id: `q-${Date.now()}`, role: 'user', content: text }])
      }
      await startRun()
    }
  }

  const accept = slots.map((s) => s.filename.replace(/^.*(\.[^.]+)$/, '*$1')).join(',') || '.csv,.xlsx,.pdf,.txt,.md'
  const hint = slots.length ? slots.map((s) => s.filename).join(', ') : 'any files this DAG accepts'

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopNav />
      <div className="flex min-h-0 flex-1 pt-16">
        <aside className="neu-raised m-4 flex w-72 shrink-0 flex-col overflow-y-auto rounded-3xl p-5">
          <Link
            to="/agents"
            className="mb-4 inline-flex w-fit items-center gap-1 font-label-md text-primary-fixed-dim transition-transform hover:-translate-x-0.5 hover:underline"
          >
            ← Library
          </Link>
          <h1 className="font-headline-md text-accent-grad">{pipeline?.name || 'Agent'}</h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {pipeline?.version ? <span className="chip font-mono-label">{pipeline.version}</span> : null}
            {busy ? (
              <span className="chip chip-accent font-mono-label">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary-container" />
                working
              </span>
            ) : run ? (
              <span className="chip chip-accent font-mono-label">run {run.status}</span>
            ) : (
              <span className="chip font-mono-label">idle</span>
            )}
          </div>
          <button
            type="button"
            className={`cta-sheen mt-6 flex w-full items-center justify-center gap-2 rounded-2xl py-3 font-label-md ${
              chatOpen ? 'neu-btn-active bg-primary-container text-on-primary-container' : 'neu-btn text-on-surface'
            }`}
            onClick={() => setChatOpen((open) => !open)}
          >
            <Icon name="chat" className="text-[18px]" />
            Chat with agent
          </button>
          <button
            type="button"
            className="neu-btn cta-sheen mt-2 flex w-full items-center justify-center gap-2 rounded-2xl py-3 font-label-md text-on-surface"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
          >
            <Icon name="upload_file" className="text-[18px]" />
            Attach
          </button>
          <p className="mt-2 font-mono-label text-[11px] text-on-surface-variant">Same names: {hint}</p>
          {missing.length > 0 && (
            <p className="mt-1 font-mono-label text-[11px] text-primary-fixed-dim">Still need: {missing.join(', ')}</p>
          )}
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            multiple
            accept={accept}
            onChange={(e) => {
              if (e.target.files?.length) void onFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <nav className="stagger mt-6 flex flex-col gap-2" aria-label="Result views">
            {VIEWS.map((item) => {
              const enabled = Boolean(run)
              const selected = view === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  disabled={!enabled}
                  onClick={() => setView(item.id)}
                  className={`group flex items-center gap-2 overflow-hidden rounded-2xl px-4 py-3 text-left font-label-md transition-all duration-200 ${
                    selected
                      ? 'rail neu-btn-active bg-primary-container text-on-primary-container'
                      : 'neu-btn text-on-surface hover:translate-x-0.5'
                  } ${enabled ? '' : 'opacity-40'}`}
                >
                  <Icon
                    name={item.icon}
                    className="text-[18px] transition-transform duration-200 group-hover:scale-110"
                  />
                  {item.label}
                </button>
              )
            })}
          </nav>
          {view === 'reports' && run && (
            <div className="mt-4 space-y-2">
              {run.artifacts.map((name) => (
                <a
                  key={name}
    href={api.artifactUrl(run.id, name.split(/[/\\]/).pop() || name)}
                  className="neu-btn lift block truncate rounded-2xl px-3 py-2 font-label-md text-primary-fixed-dim"
                >
                  {name}
                </a>
              ))}
              {!run.artifacts.length && (
                <p className="font-body-md text-sm text-on-surface-variant">No Excel/PDF on this run.</p>
              )}
            </div>
          )}
        </aside>

        <main className="relative m-4 ml-0 flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="neu-raised flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-3xl">
            {preparing ? (
              <ProcessingState steps={progress} />
            ) : (
              <>
                {view === 'dashboard' && (
                  <DashboardPanel
                    dashboard={dashboard}
                    runId={run?.id}
                    onMailChange={() => {
                      if (agentId && run) void loadResultViews(agentId, run.id)
                    }}
                  />
                )}
                {view === 'how' && agentId && run ? (
                  <HowItWorksPanel pipeline={pipeline} lineage={lineage} pipelineId={agentId} runId={run.id} />
                ) : null}
                {view === 'how' && !run ? (
                  <p className="p-6 font-body-md text-on-surface-variant">Run the pipeline to inspect each sheet.</p>
                ) : null}
                {view === 'lineage' && <LineagePanel lineage={lineage} />}
                {view === 'reports' && run && agentId ? (
                  <ReportsPanel
                    pipelineId={agentId}
                    runId={run.id}
                    lineage={lineage}
                    artifacts={run.artifacts}
                  />
                ) : null}
                {view === 'reports' && !run ? (
                  <p className="p-6 font-body-md text-on-surface-variant">Run the pipeline to generate reports.</p>
                ) : null}
              </>
            )}
          </div>
          {chatOpen ? (
            <div className="neu-raised slide-in-right absolute inset-y-0 right-0 z-20 flex w-[min(28rem,100%)] flex-col overflow-hidden rounded-3xl shadow-[var(--neu-raised),-24px_0_48px_rgba(0,0,0,0.18)]">
              <div className="flex shrink-0 items-center justify-between border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_8%,transparent)] px-4 py-3">
                <div className="flex items-center gap-2 font-label-md text-on-surface">
                  <Icon name="auto_awesome" className="text-[18px] text-primary-fixed-dim" />
                  Chat with agent
                </div>
                <button
                  type="button"
                  className="neu-btn hover-tint rounded-xl px-2 py-1 text-on-surface"
                  onClick={() => setChatOpen(false)}
                  aria-label="Close chat"
                >
                  <Icon name="close" className="text-[18px]" />
                </button>
              </div>
              <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`rise flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl p-4 font-body-md ${
                        message.role === 'assistant'
                          ? 'neu-raised rounded-tl-md text-on-surface'
                          : 'neu-inset whitespace-pre-wrap rounded-tr-md text-on-surface'
                      }`}
                    >
                      {message.pending ? (
                        <TypingDots label="Reading the result to answer you" />
                      ) : message.role === 'assistant' ? (
                        <MarkdownBody text={message.content} />
                      ) : (
                        message.content
                      )}
                      {message.thinking?.length ? (
                        <ol className="mt-3 max-h-64 space-y-2 overflow-y-auto">
                          {message.thinking.map((line) => (
                            <li key={line.node_id} className="neu-inset rise flex gap-2 rounded-xl px-3 py-2">
                              <Icon
                                name={statusIcon(line.status)}
                                className={`mt-0.5 text-[18px] ${
                                  line.status === 'error'
                                    ? 'text-red-500'
                                    : line.status === 'ok'
                                      ? 'text-emerald-500'
                                      : 'text-primary-fixed-dim'
                                } ${line.status === 'running' ? 'animate-spin' : ''}`}
                              />
                              <div>
                                <div className="font-label-md text-on-surface">
                                  {line.label} · {line.status}
                                </div>
                                <div className="font-body-md text-on-surface-variant">{line.message}</div>
                              </div>
                            </li>
                          ))}
                        </ol>
                      ) : null}
                    </div>
                  </div>
                ))}
                {error && <p className="font-body-md text-red-500">{error}</p>}
              </div>
              <form onSubmit={onSubmit} className="relative flex shrink-0 items-center p-4 pt-0">
                <input
                  className="field w-full py-3 pl-4 pr-12"
                  placeholder={run ? 'Ask about this result…' : 'Send to run the pipeline…'}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={busy}
                />
                <button type="submit" className="absolute right-7 text-primary-fixed-dim" disabled={busy} aria-label="Send">
                  <Icon name="send" />
                </button>
              </form>
            </div>
          ) : null}
        </main>
      </div>
    </div>
  )
}
