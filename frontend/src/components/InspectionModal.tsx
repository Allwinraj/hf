import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from './Icon'

export type PortTone = 'gold' | 'cyan' | 'error' | 'muted'

export interface InspectableMode {
  title: string
  icon?: string
  description: string
  highlight?: boolean
}

export interface InspectableAgent {
  name: string
  icon: string
  description: string
  badge?: string
  modeDetails: InspectableMode[]
  topology?: {
    animation?: string
    inputs: { icon: string; label: string }[]
    outputTitle: string
    outputs: { label: string; tone: PortTone }[]
  }
  envelope?: unknown
}

const portTone: Record<PortTone, string> = {
  gold: 'bg-primary-fixed-dim shadow-[0_0_6px_#e9c400]',
  cyan: 'bg-tertiary-fixed-dim shadow-[0_0_6px_#00dbe8]',
  error: 'bg-error shadow-[0_0_6px_#ffb4ab]',
  muted: 'bg-on-surface-variant shadow-[0_0_6px_#d0c6ab]',
}

export default function InspectionModal({
  agent,
  onClose,
  deployTo,
}: {
  agent: InspectableAgent
  onClose: () => void
  deployTo?: string
}) {
  const navigate = useNavigate()
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[color-mix(in_srgb,var(--ey-navy)_65%,transparent)] p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-label={`${agent.name} inspection`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="rise max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-xl border border-[var(--ey-line)] bg-surface shadow-[var(--neu-raised),0_24px_60px_rgba(0,0,0,0.35)]">
        <div className="flex items-start justify-between border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_7%,transparent)] p-gutter">
          <div className="flex items-start gap-4">
            <div className="box-glow-gold flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-[var(--ey-line)] bg-surface">
              <Icon name={agent.icon} className="text-primary-fixed-dim" />
            </div>
            <div>
              <div className="mb-1 flex items-center gap-3">
                <h1 className="font-headline-md text-headline-md text-on-surface">{agent.name}</h1>
                {agent.badge && (
                  <span className="rounded-sm border border-primary-container/30 bg-primary-container/10 px-2 py-0.5 font-mono-label text-mono-label uppercase tracking-wider text-primary-fixed-dim">
                    {agent.badge}
                  </span>
                )}
              </div>
              <p className="max-w-3xl font-body-md text-body-md text-on-surface-variant">{agent.description}</p>
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close"
            className="hover-tint rounded-full p-2 text-on-surface-variant hover:text-on-surface"
          >
            <Icon name="close" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-gutter">
          {agent.envelope !== undefined && (
            <>
              <h2 className="mb-sm font-label-md text-label-md uppercase tracking-wider text-on-surface opacity-80">
                Envelope
              </h2>
              <pre className="mb-lg max-h-[40vh] overflow-auto rounded-lg border border-[var(--ey-line)] bg-surface-container-low p-4 font-mono-label text-xs text-on-surface">
                {JSON.stringify(agent.envelope, null, 2)}
              </pre>
            </>
          )}

          {agent.modeDetails.length > 0 && (
            <>
              <h2 className="mb-sm font-label-md text-label-md uppercase tracking-wider text-on-surface opacity-80">
                Execution Modes
              </h2>
              <div className="mb-lg grid grid-cols-1 gap-sm md:grid-cols-3">
                {agent.modeDetails.map((mode) => (
                  <div
                    key={mode.title}
                    className={`rounded-lg border p-sm ${
                      mode.highlight ? 'border-primary-fixed-dim/30' : 'border-[var(--ey-line)]'
                    } bg-surface`}
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <Icon
                        name={mode.icon ?? 'tune'}
                        className={`text-[20px] ${mode.highlight ? 'text-primary-fixed-dim' : 'text-on-surface-variant'}`}
                      />
                      <h3 className="font-label-md font-bold text-on-surface">{mode.title}</h3>
                    </div>
                    <p className="font-body-md text-[13px] leading-relaxed text-on-surface-variant">{mode.description}</p>
                  </div>
                ))}
              </div>
            </>
          )}

          {agent.topology && (
            <>
              <h2 className="mb-sm font-label-md text-label-md uppercase tracking-wider text-on-surface opacity-80">
                Ports
              </h2>
              <div className="relative flex min-h-[180px] flex-col items-center justify-center overflow-hidden rounded-lg border border-[var(--ey-line)] bg-surface-container-low p-md">
                <div className="relative z-10 flex w-full max-w-3xl items-center justify-between gap-6">
                  <div className="flex flex-col gap-4">
                    {agent.topology.inputs.map((chip) => (
                      <div key={chip.label} className="flex items-center gap-2 rounded border border-[var(--ey-line)] bg-surface p-2 pr-4 text-sm">
                        <Icon name={chip.icon} className="text-[16px] text-on-surface-variant" />
                        <span className="font-mono-label text-on-surface">{chip.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="flex h-16 w-16 items-center justify-center rounded-full border border-primary-fixed-dim/40 bg-surface-container-lowest">
                    <Icon name={agent.icon} className="text-[28px] text-primary-fixed-dim" />
                  </div>
                  <div className="min-w-[200px] rounded border border-[var(--ey-line)] bg-surface-container p-4">
                    <div className="mb-3 border-b border-[var(--ey-line)] pb-2 font-label-md font-bold text-on-surface">
                      {agent.topology.outputTitle}
                    </div>
                    {agent.topology.outputs.map((out) => (
                      <div key={out.label} className="flex items-center justify-between py-1">
                        <span className="font-mono-label text-mono-label text-on-surface-variant">{out.label}</span>
                        <span className={`h-2 w-2 rounded-full ${portTone[out.tone]}`} />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-4 border-t border-[var(--ey-line)] bg-surface-container/50 p-gutter">
          <button
            onClick={onClose}
            className="hairline hover-tint rounded-xl border px-6 py-2.5 font-label-md text-label-md text-on-surface"
          >
            Close
          </button>
          {deployTo && (
            <button
              onClick={() => navigate(deployTo)}
              className="cta-sheen flex items-center gap-2 rounded-xl bg-primary-container px-6 py-2.5 font-label-md font-bold text-on-primary-container hover:bg-primary-container/90"
            >
              <Icon name="rocket_launch" className="text-[18px]" />
              Deploy to Pipeline
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
