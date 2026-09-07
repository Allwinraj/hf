import { useEffect, useState } from 'react'
import Icon from './Icon'
import SheetGrid from './SheetGrid'
import type { LineageView, Pipeline, SheetCard } from '../types/nexus'

function statusIcon(status: string) {
  if (status === 'ok') return 'check_circle'
  if (status === 'skipped') return 'skip_next'
  if (status === 'error') return 'error'
  return 'radio_button_unchecked'
}

export default function HowItWorksPanel({
  pipeline,
  lineage,
  pipelineId,
  runId,
}: {
  pipeline: Pipeline | null
  lineage: LineageView | null
  pipelineId?: string
  runId?: string
}) {
  const sheets = lineage?.sheets || []
  const [active, setActive] = useState<SheetCard | null>(null)

  useEffect(() => {
    setActive(sheets[0] || null)
  }, [runId, sheets.length])

  if (!lineage || !runId || !pipelineId) {
    return <p className="p-6 font-body-md text-on-surface-variant">Run the pipeline to see how output was derived.</p>
  }

  const cards = lineage.cards || []

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <div className="stagger flex gap-2 overflow-x-auto border-b border-[var(--ey-line)] p-3">
        {(pipeline?.nodes || cards).map((node, position) => {
          const card = 'agent' in node && 'label' in node ? node : null
          const id = 'id' in node ? node.id : (node as { node_id: string }).node_id
          const label = 'label' in node ? String(node.label) : id
          const agent = 'agent' in node ? String(node.agent) : ''
          const status = cards.find((item) => item.node_id === id)?.status || 'ok'
          const hot = active?.node_id === id
          return (
            <div key={id} className="flex shrink-0 items-center gap-2">
              {position > 0 ? (
                <span aria-hidden="true" className="h-0.5 w-5 rounded-full bg-[var(--ey-line)]" />
              ) : null}
              <div
                className={`lift min-w-[150px] overflow-hidden rounded-2xl p-3 ${
                  hot ? 'rail neu-btn-active bg-primary-container pl-4 text-on-primary-container' : 'neu-raised'
                }`}
              >
                <div className="flex items-center gap-1">
                  <Icon
                    name={statusIcon(status)}
                    className={`text-[16px] ${
                      status === 'error' ? 'text-red-500' : status === 'ok' && !hot ? 'text-emerald-500' : ''
                    }`}
                  />
                  <span className="font-label-md">{label}</span>
                </div>
                <div className="mt-1 font-mono-label text-[11px] uppercase tracking-wider opacity-80">{agent}</div>
                {card && 'why' in card && card.why ? (
                  <p className="mt-1 line-clamp-2 font-body-md text-[11px]">{String(card.why)}</p>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
      <SheetGrid
        pipelineId={pipelineId}
        runId={runId}
        sheets={sheets}
        columns={lineage.columns}
        active={active}
        onActive={setActive}
        expandable
        hint="Double-click any row (or use the ▸ arrow) to open the calculation and justification under it. Open as many rows as you need."
      />
    </div>
  )
}
