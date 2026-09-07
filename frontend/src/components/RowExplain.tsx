import Icon from './Icon'
import type { RowTrace, RowTraceStep } from '../types/nexus'

function stageTitle(stage: string) {
  if (stage === 'matched' || stage === 'ingested') return 'How it was paired'
  if (stage === 'computed') return 'How the number was calculated'
  if (stage === 'decided') return 'Why this result'
  return stage.replace(/_/g, ' ')
}

function stageIcon(stage: string) {
  if (stage === 'matched' || stage === 'ingested') return 'link'
  if (stage === 'computed') return 'functions'
  if (stage === 'decided') return 'gavel'
  return 'timeline'
}

function StepBlock({ step }: { step: RowTraceStep }) {
  return (
    <div className="neu-inset rail rounded-xl p-3 pl-4">
      <div className="flex items-center gap-2">
        <Icon name={stageIcon(step.stage)} className="text-[16px] text-primary-fixed-dim" />
        <div className="font-label-md capitalize text-on-surface">{stageTitle(step.stage)}</div>
      </div>
      {step.substituted ? (
        <p className="mt-2 rounded-lg bg-[color-mix(in_srgb,var(--ey-accent)_12%,transparent)] px-2 py-1 font-mono-label text-sm text-on-surface">
          {step.substituted}
        </p>
      ) : null}
      {step.expression && step.expression !== step.substituted ? (
        <p className="mt-1 font-mono-label text-[11px] text-on-surface-variant">{step.expression}</p>
      ) : null}
      {step.gate ? <p className="mt-1 font-mono-label text-sm text-on-surface-variant">{step.gate}</p> : null}
      {step.value != null ? (
        <p className="mt-2 font-body-md text-sm text-on-surface">
          Result: <span className="font-semibold tabular-nums">{String(step.value)}</span>
        </p>
      ) : null}
      {step.verdict ? (
        <span className="chip chip-accent mt-2 font-mono-label uppercase tracking-wider">{step.verdict}</span>
      ) : null}
      {step.explanation ? <p className="mt-2 font-body-md text-sm text-on-surface">{step.explanation}</p> : null}
      {step.why ? <p className="mt-1 font-body-md text-sm text-on-surface-variant">{step.why}</p> : null}
    </div>
  )
}

export default function RowExplain({
  trace,
  loading,
  error,
}: {
  trace: RowTrace | null
  loading?: boolean
  error?: string | null
}) {
  if (loading) {
    return (
      <div className="space-y-2">
        <div className="skeleton h-4 w-56" />
        <div className="skeleton h-16 w-full" />
        <div className="skeleton h-16 w-full" />
      </div>
    )
  }
  if (error) {
    return <p className="font-body-md text-sm text-red-500">{error}</p>
  }
  if (!trace?.steps?.length && !trace?.justification?.length) {
    return <p className="font-body-md text-sm text-on-surface-variant">No calculation trail is stored for this row.</p>
  }
  const lines = (trace?.justification || []).slice(0, 3)
  return (
    <div className="space-y-3">
      {lines.length ? (
        <div className="neu-raised rounded-xl p-3">
          <div className="flex items-center gap-2 font-label-md text-on-surface">
            <Icon name="lightbulb" className="text-[16px] text-primary-fixed-dim" />
            Justification
          </div>
          <ol className="mt-2 space-y-2">
            {lines.map((line, index) => (
              <li key={line} className="flex gap-2 font-body-md text-sm text-on-surface">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-container font-mono-label text-[11px] text-on-primary-container">
                  {index + 1}
                </span>
                {line}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <div className="font-mono-label uppercase tracking-wider text-on-surface-variant">
        Pairing, formula, gate, and decision
      </div>
      <div className="stagger space-y-3">
        {(trace?.steps || []).map((step, index) => (
          <StepBlock key={`${step.stage}-${index}`} step={step} />
        ))}
      </div>
    </div>
  )
}
