import { useEffect, useState } from 'react'
import Icon from './Icon'
import TypingDots from './TypingDots'

export interface ProgressStep {
  node_id: string
  label: string
  status: string
  message: string
}

const PHASES = [
  'Reading the files you attached…',
  'Lining the sheets up and matching records…',
  'Running the calculations on every row…',
  'Applying the decision policy…',
  'Consolidating the data…',
  'Building the dashboard and the report…',
]

function stepIcon(status: string) {
  if (status === 'running') return 'progress_activity'
  if (status === 'ok') return 'check_circle'
  if (status === 'skipped') return 'skip_next'
  if (status === 'error') return 'error'
  return 'radio_button_unchecked'
}

export default function ProcessingState({
  steps = [],
  title = 'Processing your data',
}: {
  steps?: ProgressStep[]
  title?: string
}) {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => setPhase((current) => (current + 1) % PHASES.length), 2600)
    return () => window.clearInterval(id)
  }, [])

  // The live node is more honest than the rotating copy, so it wins when present.
  const live = steps.find((step) => step.status === 'running')
  const done = steps.filter((step) => step.status !== 'running').length

  return (
    <div className="h-full min-h-0 overflow-y-auto p-6">
      <div className="neu-raised rail rise rounded-3xl p-6 pl-7">
        <div className="flex flex-wrap items-center gap-3">
          <Icon name="progress_activity" className="animate-spin text-[22px] text-primary-fixed-dim" />
          <h2 className="font-headline-sm text-accent-grad">{title}</h2>
          {steps.length ? (
            <span className="chip chip-accent font-mono-label">
              {done}/{steps.length} steps
            </span>
          ) : null}
        </div>
        <p key={phase} className="rise mt-3 font-body-md text-on-surface">
          {live ? `${live.label} — ${live.message || 'working'}` : PHASES[phase]}
        </p>
        <div className="progress-strip mt-4 h-1.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--ey-ink)_10%,transparent)]" />
        <div className="mt-3">
          <TypingDots label="This can take a moment on large files" />
        </div>
      </div>

      {steps.length ? (
        <ol className="stagger mt-4 space-y-2">
          {steps.map((step) => (
            <li key={step.node_id} className="neu-inset flex gap-2 rounded-xl px-4 py-2">
              <Icon
                name={stepIcon(step.status)}
                className={`mt-0.5 text-[18px] ${
                  step.status === 'error'
                    ? 'text-red-500'
                    : step.status === 'ok'
                      ? 'text-emerald-500'
                      : 'text-primary-fixed-dim'
                } ${step.status === 'running' ? 'animate-spin' : ''}`}
              />
              <div className="min-w-0">
                <div className="font-label-md text-on-surface">
                  {step.label} · {step.status}
                </div>
                {step.message ? (
                  <div className="font-body-md text-sm text-on-surface-variant">{step.message}</div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-28" />
        ))}
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="skeleton h-64" />
        <div className="skeleton h-64" />
      </div>
    </div>
  )
}
