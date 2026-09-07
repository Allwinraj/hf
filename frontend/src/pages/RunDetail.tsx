import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Icon from '../components/Icon'
import IconNav from '../components/IconNav'
import RunTrace from '../components/RunTrace'
import ThemeToggle from '../components/ThemeToggle'
import { api } from '../lib/api'
import type { RunSnapshot } from '../types/nexus'

export default function RunDetail() {
  const { runId } = useParams()
  const [snap, setSnap] = useState<RunSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    api
      .getSnapshot(runId)
      .then(setSnap)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load run'))
  }, [runId])

  const artifacts = snap?.run.artifacts ?? []
  const names = artifacts.map((path) => path.split(/[/\\]/).pop() ?? path)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-container-lowest">
      <header className="z-20 flex h-16 shrink-0 items-center justify-between border-b border-[var(--ey-line)] bg-surface/80 px-gutter backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <Link to="/architect/create" className="hover-tint rounded-lg p-2 text-on-surface-variant" aria-label="Back to Architect">
            <Icon name="arrow_back" />
          </Link>
          <h1 className="font-headline-md text-accent-grad">Studio run</h1>
          {snap && (
            <span className="chip chip-accent font-mono-label">
              {snap.run.id.slice(0, 8)} · {snap.run.status}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          {snap?.run.extra?.source === 'library' && (
            <Link
              to={`/architect/create?pipeline=${snap.run.pipeline_id}`}
              className="font-label-md text-primary-fixed-dim hover:underline"
            >
              Open pipeline
            </Link>
          )}
        </div>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <IconNav />
        <main className="page-aura flex-1 overflow-y-auto p-gutter">
          {error && <p className="font-body-md text-red-500">{error}</p>}
          {!snap && !error && (
            <div className="mx-auto max-w-4xl space-y-3">
              <div className="skeleton h-6 w-48" />
              <div className="skeleton h-24 w-full" />
              <div className="skeleton h-24 w-full" />
            </div>
          )}
          {snap && (
            <div className="relative z-10 mx-auto max-w-4xl space-y-8">
              <section>
                <h2 className="title-rule mb-2 font-label-md uppercase tracking-wider text-on-surface-variant">Summary</h2>
                <p className="font-body-md text-on-surface-variant">
                  Pipeline {snap.run.pipeline_id.slice(0, 8)} · version {snap.run.pipeline_version}
                  {snap.run.started_at ? ` · started ${snap.run.started_at}` : ''}
                </p>
                {snap.run.error && <p className="mt-2 text-red-500">{snap.run.error}</p>}
              </section>
              {names.length > 0 && (
                <section>
                  <h2 className="title-rule mb-2 font-label-md uppercase tracking-wider text-on-surface-variant">Downloads</h2>
                  <div className="flex flex-wrap gap-3">
                    {names.map((name) => (
                      <a
                        key={name}
                        href={api.artifactUrl(snap.run.id, name)}
                        className="hover-tint lift inline-flex items-center gap-2 rounded-xl border border-primary-fixed-dim/30 px-4 py-2 font-label-md text-primary-fixed-dim"
                      >
                        {name}
                      </a>
                    ))}
                  </div>
                </section>
              )}
              <section>
                <h2 className="title-rule mb-3 font-label-md uppercase tracking-wider text-on-surface-variant">Step trace</h2>
                <RunTrace steps={snap.run.steps} />
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
