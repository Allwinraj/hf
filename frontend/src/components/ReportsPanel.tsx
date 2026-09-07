import { useEffect, useState } from 'react'
import Icon from './Icon'
import SheetGrid from './SheetGrid'
import { api } from '../lib/api'
import type { LineageView, ReportSpec, SheetCard } from '../types/nexus'

export default function ReportsPanel({
  pipelineId,
  runId,
  lineage,
  artifacts,
}: {
  pipelineId: string
  runId: string
  lineage: LineageView | null
  artifacts: string[]
}) {
  const [fmt, setFmt] = useState<'xlsx' | 'pdf'>('xlsx')
  const [spec, setSpec] = useState<ReportSpec | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [active, setActive] = useState<SheetCard | null>(null)
  const [busy, setBusy] = useState(false)
  const [link, setLink] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getReportSpec(pipelineId, runId, fmt)
      .then((body) => {
        setSpec(body)
        setSelected((body.sections || []).map((item) => item.catalog_id))
        setActive((body.sheets || lineage?.sheets || [])[0] || null)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load report spec'))
  }, [pipelineId, runId, fmt, lineage?.sheets])

  const sheets = spec?.sheets || lineage?.sheets || []

  const generate = async () => {
    if (!spec) return
    setBusy(true)
    setError(null)
    try {
      const sections = (spec.sections || []).filter((item) => selected.includes(item.catalog_id))
      const body = await api.generateReport(pipelineId, runId, fmt, sections)
      setLink(api.artifactUrl(runId, body.artifact))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not generate report')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_5%,transparent)] p-4">
        <div className="neu-inset flex rounded-full p-1">
          {(['xlsx', 'pdf'] as const).map((item) => (
            <button
              key={item}
              type="button"
              className={`flex items-center gap-1.5 rounded-full px-4 py-1 font-label-md transition-all duration-200 ${
                fmt === item ? 'neu-raised bg-primary-container text-on-primary-container' : 'text-on-surface'
              }`}
              onClick={() => setFmt(item)}
            >
              <Icon name={item === 'xlsx' ? 'table_view' : 'picture_as_pdf'} className="text-[16px]" />
              {item === 'xlsx' ? 'Excel' : 'PDF'}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="neu-btn cta-sheen flex items-center gap-2 rounded-2xl px-4 py-2 font-label-md disabled:opacity-50"
          disabled={busy}
          onClick={() => void generate()}
        >
          <Icon
            name={busy ? 'progress_activity' : 'auto_awesome'}
            className={`text-[18px] text-primary-fixed-dim ${busy ? 'animate-spin' : ''}`}
          />
          {busy ? 'Generating…' : 'Generate'}
        </button>
        {link ? (
          <a
            href={link}
            className="neu-btn lift flex items-center gap-2 rounded-2xl px-4 py-2 font-label-md text-primary-fixed-dim"
          >
            <Icon name="download" className="text-[18px]" />
            Download
          </a>
        ) : null}
        <span className="chip ml-auto font-mono-label">{selected.length} sections selected</span>
      </div>
      {error ? <p className="px-4 py-2 font-body-md text-red-500">{error}</p> : null}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_1fr]">
        <aside className="overflow-y-auto border-r border-[var(--ey-line)] p-4">
          <h3 className="title-rule font-mono-label uppercase tracking-wider text-on-surface-variant">Sections</h3>
          <ul className="stagger mt-3 space-y-2">
            {(spec?.sections || []).map((item) => (
              <li key={`${item.catalog_id}-${item.title}`}>
                <label
                  className={`hover-tint flex cursor-pointer items-start gap-2 rounded-xl border p-2 font-body-md text-sm text-on-surface ${
                    selected.includes(item.catalog_id)
                      ? 'border-primary-fixed-dim/50 bg-[color-mix(in_srgb,var(--ey-accent)_10%,transparent)]'
                      : 'border-[var(--ey-line)]'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-1 accent-[#fca311]"
                    checked={selected.includes(item.catalog_id)}
                    onChange={(e) =>
                      setSelected((prev) =>
                        e.target.checked ? [...prev, item.catalog_id] : prev.filter((id) => id !== item.catalog_id),
                      )
                    }
                  />
                  <span>
                    <span className="font-label-md">{item.title || item.catalog_id}</span>
                    {item.source_port ? (
                      <span className="block font-mono-label text-[11px] text-on-surface-variant">
                        {item.source_port}
                        {item.source_node ? ` · ${item.source_node}` : ''}
                      </span>
                    ) : null}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <h3 className="title-rule mt-6 font-mono-label uppercase tracking-wider text-on-surface-variant">
            Produced by the pipeline
          </h3>
          <ul className="mt-2 space-y-1">
            {artifacts.map((name) => (
              <li key={name}>
                <a
                  href={api.artifactUrl(runId, name.split(/[/\\]/).pop() || name)}
                  className="hover-tint flex items-center gap-2 rounded-lg px-2 py-1 font-label-md text-primary-fixed-dim"
                >
                  <Icon name="description" className="text-[16px]" />
                  <span className="truncate">{name.split('/').pop()}</span>
                </a>
              </li>
            ))}
            {!artifacts.length ? <li className="font-body-md text-sm text-on-surface-variant">None yet.</li> : null}
          </ul>
        </aside>
        {active || sheets.length ? (
          <SheetGrid
            pipelineId={pipelineId}
            runId={runId}
            sheets={sheets}
            columns={lineage?.columns}
            active={active || sheets[0]}
            onActive={setActive}
            hint="Report preview only. Generate Excel or PDF to download. Open How it works to expand a row and see the calculation."
          />
        ) : (
          <p className="p-4 font-body-md text-on-surface-variant">No sheet preview.</p>
        )}
      </div>
    </div>
  )
}
