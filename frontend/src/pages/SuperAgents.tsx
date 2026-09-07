import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import TopNav from '../components/TopNav'
import Icon from '../components/Icon'
import { api } from '../lib/api'
import type { LibraryPipeline } from '../types/nexus'

export default function SuperAgents() {
  const navigate = useNavigate()
  const [pipelines, setPipelines] = useState<LibraryPipeline[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listPipelines()
      .then((body) => setPipelines(body.pipelines))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load library'))
  }, [])

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopNav />
      <div className="relative flex flex-1 overflow-hidden pt-16">
        <aside className="flex h-full w-64 flex-col border-r border-outline-variant/10 bg-surface-container-low py-sm">
          <div className="mb-sm border-b border-outline-variant/10 px-sm pb-md">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded border border-outline-variant/20 bg-background text-primary">
                <Icon name="widgets" fill />
              </div>
              <div>
                <h2 className="text-[16px] font-headline-md text-primary">Super Agents</h2>
                <p className="text-[12px] font-label-md text-on-surface-variant">Saved pipelines</p>
              </div>
            </div>
            <button
              onClick={() => navigate('/architect/create')}
              className="cta-sheen flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-primary-container font-label-md text-on-primary-container hover:bg-primary-fixed"
            >
              <Icon name="add" className="text-[18px]" />
              New in Architect
            </button>
          </div>
        </aside>

        <main className="page-aura relative z-10 flex-1 overflow-y-auto p-gutter">
          <div className="rise relative z-10 mb-8">
            <span className="chip chip-accent mb-3 font-mono-label uppercase tracking-widest">
              {pipelines.length} saved
            </span>
            <h1 className="mb-2 font-display-lg text-display-lg text-accent-grad">Super Agents Library</h1>
            <p className="font-body-lg text-body-lg text-on-surface-variant">
              Agents you confirmed and saved. Open or Run to chat, attach the same file names, and get results.
            </p>
          </div>
          {error && <p className="mb-4 font-body-md text-red-500">{error}</p>}
          {pipelines.length === 0 && !error && (
            <p className="font-body-md text-on-surface-variant">
              No saved pipelines yet. Confirm a draft in Architect and press Save.
            </p>
          )}
          <div className="stagger relative z-10 grid grid-cols-1 gap-md pb-xl md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {pipelines.map((item) => (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                onDoubleClick={() => navigate(`/agents/${item.id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') navigate(`/agents/${item.id}`)
                }}
                className="glass-card lift rail group flex flex-col rounded-xl border border-outline-variant/20 p-md pl-7 text-left"
              >
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-outline-variant/20 bg-surface-container transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110">
                  <Icon name="account_tree" className="text-[24px] text-tertiary-fixed" />
                </div>
                <h3 className="text-[18px] font-headline-md text-on-surface transition-colors group-hover:text-primary-fixed-dim">
                  {item.name}
                </h3>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="chip chip-accent font-mono-label uppercase tracking-wider">{item.version}</span>
                  <span className="chip font-mono-label">{item.nodes} nodes</span>
                </div>
                {item.file_slots?.length ? (
                  <p className="mt-3 font-mono-label text-[11px] text-on-surface-variant">
                    {item.file_slots.map((s) => s.filename).join(', ')}
                  </p>
                ) : null}
                <div className="mt-6 flex gap-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/agents/${item.id}`)}
                    className="cta-sheen rounded-xl bg-primary-container px-3 py-1.5 font-label-md text-on-primary-container"
                  >
                    Run
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate(`/architect/create?pipeline=${item.id}`)}
                    className="hairline hover-tint rounded-xl border px-3 py-1.5 font-label-md text-on-surface"
                  >
                    Canvas
                  </button>
                </div>
              </div>
            ))}
          </div>
        </main>
      </div>
    </div>
  )
}
