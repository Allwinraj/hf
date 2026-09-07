import { useState } from 'react'
import InspectionModal, { type InspectableAgent } from './InspectionModal'
import type { Envelope, RunStepFull } from '../types/nexus'

const statusClass: Record<string, string> = {
  ok: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-500',
  skipped: 'border-[var(--ey-line)] text-on-surface-variant',
  error: 'border-red-500/40 bg-red-500/10 text-red-500',
}

export default function RunTrace({ steps }: { steps: RunStepFull[] }) {
  const [inspect, setInspect] = useState<InspectableAgent | null>(null)

  return (
    <>
      <ol className="stagger space-y-3">
        {steps.map((step, index) => (
          <li
            key={`${step.node_id}-${index}`}
            className="lift rail rounded-xl border border-[var(--ey-line)] bg-surface-container-high p-4 pl-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="font-label-md text-on-surface">
                  {index + 1}. {step.node_id}
                </div>
                <div className="mt-1 font-mono-label text-on-surface-variant">
                  {step.agent}
                  {step.behavior_version ? ` · ${step.behavior_version}` : ''}
                  {step.outputs[0]?.emitted_by ? ` · ${step.outputs[0].emitted_by}` : ''}
                  {' · '}
                  {step.duration_ms.toFixed(1)} ms
                </div>
              </div>
              <span className={`rounded-full border px-2.5 py-1 font-mono-label ${statusClass[step.status] ?? 'border-[var(--ey-line)]'}`}>
                {step.status}
              </span>
            </div>
            {step.error && <p className="mt-2 font-body-md text-red-500">{step.error}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              {step.outputs.map((env, i) => (
                <button
                  key={`${env.port}-${i}`}
                  type="button"
                  className="hairline hover-tint rounded-full border px-3 py-1 font-mono-label text-primary-fixed-dim"
                  onClick={() => setInspect(envelopeInspect(step, env, 'output'))}
                >
                  out:{env.port}
                </button>
              ))}
              {step.inputs.map((env, i) => (
                <button
                  key={`in-${env.port}-${i}`}
                  type="button"
                  className="hover-tint rounded-full border border-[var(--ey-line)] px-3 py-1 font-mono-label text-on-surface-variant"
                  onClick={() => setInspect(envelopeInspect(step, env, 'input'))}
                >
                  in:{env.port}
                </button>
              ))}
            </div>
          </li>
        ))}
      </ol>
      {inspect && <InspectionModal agent={inspect} onClose={() => setInspect(null)} />}
    </>
  )
}

function envelopeInspect(step: RunStepFull, env: Envelope, direction: string): InspectableAgent {
  return {
    name: `${step.node_id} ${direction} · ${env.port}`,
    icon: 'mail',
    description: `emitted_by ${env.emitted_by}`,
    badge: env.port,
    modeDetails: [],
    envelope: env,
  }
}
