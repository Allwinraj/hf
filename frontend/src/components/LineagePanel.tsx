import Icon from './Icon'
import type { LineageView } from '../types/nexus'

function statusTone(status: string) {
  if (status === 'error') return 'border-red-500/40 bg-red-500/10 text-red-500'
  if (status === 'skipped') return 'border-[var(--ey-line)] text-on-surface-variant'
  return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500'
}

function SectionHead({ icon, title, count }: { icon: string; title: string; count?: number }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h3 className="title-rule flex items-center gap-2 font-mono-label uppercase tracking-wider text-on-surface-variant">
        <Icon name={icon} className="text-[16px] text-primary-fixed-dim" />
        {title}
      </h3>
      {count != null ? <span className="chip font-mono-label">{count}</span> : null}
    </div>
  )
}

export default function LineagePanel({ lineage }: { lineage: LineageView | null }) {
  if (!lineage) {
    return (
      <div className="space-y-3 p-6">
        <p className="font-body-md text-on-surface-variant">Run the pipeline to see how output was derived.</p>
        <div className="skeleton h-24 w-full" />
        <div className="skeleton h-40 w-full" />
      </div>
    )
  }

  return (
    <div className="stagger h-full min-h-0 space-y-4 overflow-y-auto p-4">
      <section className="neu-raised rounded-2xl p-4">
        <SectionHead icon="input" title="Inputs" count={lineage.inputs.length} />
        <ul className="space-y-2">
          {lineage.inputs.map((item) => (
            <li
              key={item.node_id}
              className="neu-inset rail flex flex-wrap items-center gap-2 rounded-xl px-4 py-2 font-body-md text-on-surface"
            >
              {item.label}
              {item.filename ? <span className="chip font-mono-label">{item.filename}</span> : null}
              {item.mode ? <span className="chip chip-accent font-mono-label">{item.mode}</span> : null}
            </li>
          ))}
          {!lineage.inputs.length && <li className="text-on-surface-variant">No ingest filenames stored.</li>}
        </ul>
      </section>
      <section className="neu-raised rounded-2xl p-4">
        <SectionHead icon="conversion_path" title="How each step derived output" count={lineage.steps.length} />
        <ol className="space-y-3">
          {lineage.steps.map((step, position) => (
            <li key={step.node_id} className="neu-inset rail lift rounded-xl p-3 pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-container font-mono-label text-[11px] text-on-primary-container">
                  {position + 1}
                </span>
                <span className="font-label-md text-on-surface">{step.label}</span>
                <span className="chip font-mono-label">{step.agent}</span>
                <span className={`chip border font-mono-label uppercase ${statusTone(step.status)}`}>
                  {step.status}
                </span>
              </div>
              {step.summary ? <p className="mt-2 font-body-md text-sm text-on-surface-variant">{step.summary}</p> : null}
              {step.skip_reason ? (
                <p className="mt-1 font-body-md text-sm text-on-surface-variant">Skipped: {step.skip_reason}</p>
              ) : null}
              {step.formula_en ? (
                <p className="mt-2 font-body-md text-sm text-on-surface">{String(step.formula_en)}</p>
              ) : null}
              {step.ast ? (
                <p className="mt-2 rounded-lg bg-[color-mix(in_srgb,var(--ey-accent)_12%,transparent)] px-2 py-1 font-mono-label text-on-surface">
                  {String(step.ast)}
                </p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {step.catalog_id ? <span className="chip font-mono-label">formula {step.catalog_id}</span> : null}
                {step.keys ? <span className="chip font-mono-label">keys {JSON.stringify(step.keys)}</span> : null}
                {step.policy ? <span className="chip font-mono-label">policy {JSON.stringify(step.policy)}</span> : null}
                {Object.keys(step.row_counts || {}).length ? (
                  <span className="chip chip-accent font-mono-label">rows {JSON.stringify(step.row_counts)}</span>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </section>
      <section className="neu-raised rounded-2xl p-4">
        <SectionHead icon="download" title="Outputs" count={lineage.outputs.length} />
        <ul className="space-y-2">
          {lineage.outputs.map((item) => (
            <li
              key={item.artifact}
              className="neu-inset rail flex items-center gap-2 rounded-xl px-4 py-2 font-body-md text-on-surface"
            >
              <Icon name="description" className="text-[16px] text-primary-fixed-dim" />
              {item.artifact}
            </li>
          ))}
          {!lineage.outputs.length && (
            <li className="text-on-surface-variant">No files yet — check Reports after a completed run.</li>
          )}
        </ul>
      </section>
    </div>
  )
}
