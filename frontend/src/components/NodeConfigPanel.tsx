import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'
import type { PipelineNode } from '../types/nexus'

const FLAG_KEYS = [
  'directional',
  'allocation',
  'residual',
  'reversal',
  'keyless',
  'distinct_guard',
] as const

export default function NodeConfigPanel({
  node,
  onSync,
  onClose,
}: {
  node: PipelineNode
  onSync: (nodeId: string, config: Record<string, unknown>) => void
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [draft, setDraft] = useState<Record<string, unknown>>(node.config)
  const [advanced, setAdvanced] = useState(false)
  const [schemaOpen, setSchemaOpen] = useState(false)
  const [inspector, setInspector] = useState(false)
  const mode = String(draft.mode ?? node.mode ?? '')

  useEffect(() => {
    setDraft(node.config)
  }, [node])

  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  const setField = (key: string, value: unknown) => {
    setDraft((prev) => {
      const next = { ...prev, [key]: value }
      if (node.agent === 'output' && key === 'mode') {
        if (value === 'pdf') next.formats = ['pdf']
        else if (value === 'both') next.formats = ['xlsx', 'pdf']
        else next.formats = ['xlsx']
      }
      return next
    })
  }

  const flags = (draft.flags as Record<string, boolean> | undefined) ?? {}

  return (
    <aside
      className="slide-in-right flex h-full w-full max-w-md flex-col border-l border-[var(--ey-line)] bg-surface shadow-[-16px_0_40px_rgba(0,0,0,0.22)] lg:w-96"
      aria-label="Node configuration"
    >
      <div className="flex items-center justify-between border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_8%,transparent)] p-md">
        <div>
          <h2 className="font-headline-md text-headline-md text-accent-grad">Node Configuration</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <span className="chip font-mono-label">{node.label || node.id}</span>
            <span className="chip chip-accent font-mono-label">{node.agent}</span>
          </div>
        </div>
        <button
          ref={closeRef}
          onClick={onClose}
          aria-label="Close configuration panel"
          className="hover-tint rounded-full p-1.5 text-on-surface-variant hover:text-on-surface"
        >
          <Icon name="close" />
        </button>
      </div>

      <div className="flex-1 space-y-md overflow-y-auto p-md">
        {node.agent === 'ingestion' && mode === 'mailbox' && (
          <>
            <Section title="Mode">
              <p className="font-body-md text-on-surface-variant">Mailbox — unread IMAP, SMTP after dashboard Send.</p>
            </Section>
            <Section title="IMAP">
              <Field label="Host">
                <input className="field" value={String(draft.imap_host ?? '')} onChange={(e) => setField('imap_host', e.target.value)} />
              </Field>
              <Field label="Port">
                <input className="field" type="number" value={Number(draft.imap_port ?? 993)} onChange={(e) => setField('imap_port', Number(e.target.value))} />
              </Field>
              <Field label="Username">
                <input className="field" value={String(draft.username ?? '')} onChange={(e) => setField('username', e.target.value)} />
              </Field>
              <Field label="App password">
                <input className="field" type="password" value={String(draft.password ?? '')} onChange={(e) => setField('password', e.target.value)} />
              </Field>
              <Field label="Folder">
                <input className="field" value={String(draft.folder ?? 'INBOX')} onChange={(e) => setField('folder', e.target.value)} />
              </Field>
              <label className="flex items-center gap-2 font-mono-label text-on-surface">
                <input type="checkbox" checked={draft.unread_only !== false} onChange={(e) => setField('unread_only', e.target.checked)} />
                Unread only
              </label>
            </Section>
            <Section title="SMTP">
              <Field label="Host">
                <input className="field" value={String(draft.smtp_host ?? '')} onChange={(e) => setField('smtp_host', e.target.value)} />
              </Field>
              <Field label="Port">
                <input className="field" type="number" value={Number(draft.smtp_port ?? 587)} onChange={(e) => setField('smtp_port', Number(e.target.value))} />
              </Field>
              <Field label="From address">
                <input className="field" value={String(draft.from_address ?? '')} onChange={(e) => setField('from_address', e.target.value)} />
              </Field>
            </Section>
          </>
        )}

        {node.agent === 'ingestion' && mode !== 'mailbox' && (
          <>
            <Section title="Mode">
              <p className="font-body-md text-on-surface-variant">
                {mode === 'knowledge' ? 'Knowledge' : 'Data'} — set from upload intent.
              </p>
            </Section>
            <Section title="File & parsing">
              <Field label="Path">
                <input className="field" value={String(draft.path ?? '')} onChange={(e) => setField('path', e.target.value)} />
              </Field>
              <Field label="Sheet">
                <input className="field" value={String(draft.sheet ?? '')} onChange={(e) => setField('sheet', e.target.value)} />
              </Field>
              <Field label="Header row">
                <input
                  className="field"
                  type="number"
                  value={Number(draft.header_row ?? 1)}
                  onChange={(e) => setField('header_row', Number(e.target.value))}
                />
              </Field>
            </Section>
            <Section
              title="Detected schema & overrides"
              action={
                <button className="text-tertiary-fixed-dim hover:underline" onClick={() => setSchemaOpen((v) => !v)}>
                  {schemaOpen ? 'Hide' : 'Expand'}
                </button>
              }
            >
              {schemaOpen && (
                <textarea
                  className="field min-h-[120px] font-mono-label text-xs"
                  value={JSON.stringify(draft.schema_overrides ?? draft.schema ?? {}, null, 2)}
                  onChange={(e) => {
                    try {
                      setField('schema_overrides', JSON.parse(e.target.value) as unknown)
                    } catch {
                      /* keep typing */
                    }
                  }}
                />
              )}
              {!schemaOpen && (
                <p className="font-body-md text-on-surface-variant">Optional column rename / type fixes. Changes propagate downstream on sync.</p>
              )}
            </Section>
          </>
        )}

        {node.agent === 'matcher' && (
          <>
            <Section title="How should records relate?">
              <Field label="Mode">
                <select className="field" value={mode} onChange={(e) => setField('mode', e.target.value)}>
                  <option value="dedupe">Dedupe</option>
                  <option value="structural">Structural</option>
                  <option value="semantic">Semantic</option>
                </select>
              </Field>
              {mode !== 'dedupe' && (
                <Field label="Match keys">
                  <input
                    className="field"
                    value={(Array.isArray(draft.keys) ? (draft.keys as string[]) : []).join(', ')}
                    onChange={(e) =>
                      setField(
                        'keys',
                        e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      )
                    }
                    placeholder="po, line"
                  />
                </Field>
              )}
              {mode === 'semantic' && (
                <div>
                  <div className="mb-1 flex justify-between font-mono-label text-on-surface-variant">
                    <span>Confidence threshold</span>
                    <span>{Number(draft.confidence_threshold ?? 0.8)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    className="w-full accent-primary-fixed-dim"
                    value={Number(draft.confidence_threshold ?? 0.8)}
                    onChange={(e) => setField('confidence_threshold', Number(e.target.value))}
                  />
                </div>
              )}
              <p className="font-mono-label text-on-surface-variant">
                Ports: matched · residuals · exceptions. Amount tolerances belong on Math, not here.
              </p>
            </Section>
            <Section title="Relationship flags">
              <div className="grid grid-cols-2 gap-2">
                {FLAG_KEYS.map((flag) => (
                  <label key={flag} className="flex items-center gap-2 font-mono-label text-on-surface">
                    <input
                      type="checkbox"
                      checked={Boolean(flags[flag])}
                      onChange={(e) => setField('flags', { ...flags, [flag]: e.target.checked })}
                    />
                    {flag.replace(/_/g, ' ')}
                  </label>
                ))}
              </div>
              <Field label="Window (days)">
                <input
                  className="field"
                  type="number"
                  value={Number(draft.window_days ?? 0)}
                  onChange={(e) => setField('window_days', Number(e.target.value))}
                />
              </Field>
            </Section>
          </>
        )}

        {node.agent === 'math' && (
          <>
            <Section title="Formula / rule">
              <Field label="Mode">
                <select className="field" value={mode} onChange={(e) => setField('mode', e.target.value)}>
                  <option value="calculation">Calculation</option>
                  <option value="rule">Rule / Gate</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </Field>
              <Field label="Plain English (from chat)">
                <textarea
                  className="field min-h-[80px]"
                  value={String(draft.formula_en ?? '')}
                  onChange={(e) => setField('formula_en', e.target.value)}
                  placeholder="whichever is smaller — 2% of the PO line or $50"
                />
              </Field>
              <Field label="Catalog id">
                <input className="field" value={String(draft.catalog_id ?? '')} onChange={(e) => setField('catalog_id', e.target.value)} />
              </Field>
              <Field label="Compiled formula (used by Math)">
                <textarea
                  className="field min-h-[70px] font-mono-label text-xs"
                  value={String(draft.ast ?? '')}
                  onChange={(e) => setField('ast', e.target.value)}
                  placeholder="compiled from the conversation"
                />
              </Field>
              {Boolean(draft.gate_ast) && (
                <Field label="Compiled gate / flag">
                  <textarea
                    className="field min-h-[56px] font-mono-label text-xs"
                    value={String(draft.gate_ast ?? '')}
                    onChange={(e) => setField('gate_ast', e.target.value)}
                  />
                </Field>
              )}
              {draft.constants != null && (
                <Field label="Numbers from chat">
                  <textarea
                    className="field min-h-[56px] font-mono-label text-xs"
                    value={JSON.stringify(draft.constants ?? {}, null, 2)}
                    onChange={(e) => {
                      try {
                        setField('constants', JSON.parse(e.target.value) as unknown)
                      } catch {
                        /* keep typing */
                      }
                    }}
                  />
                </Field>
              )}
              <Field label="Shape">
                <select className="field" value={String(draft.shape ?? 'per_row')} onChange={(e) => setField('shape', e.target.value)}>
                  <option value="per_row">per-row</option>
                  <option value="aggregate">aggregate</option>
                  <option value="sequential">sequential</option>
                  <option value="scalar">scalar</option>
                </select>
              </Field>
              <Field label="Output column">
                <input className="field" value={String(draft.output_column ?? '')} onChange={(e) => setField('output_column', e.target.value)} />
              </Field>
            </Section>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Precision">
                <input
                  className="field"
                  type="number"
                  value={Number(draft.precision ?? 2)}
                  onChange={(e) => setField('precision', Number(e.target.value))}
                />
              </Field>
              <Field label="Rounding">
                <select className="field" value={String(draft.rounding ?? 'half_up')} onChange={(e) => setField('rounding', e.target.value)}>
                  <option value="half_up">half up</option>
                  <option value="half_down">half down</option>
                  <option value="nearest">nearest</option>
                </select>
              </Field>
            </div>
            <Field label="Empty-value rule (result)">
              <input
                className="field"
                value={String((draft.empty_rule as { result?: string } | undefined)?.result ?? '—')}
                onChange={(e) =>
                  setField('empty_rule', {
                    ...((draft.empty_rule as object) ?? {}),
                    result: e.target.value,
                    on: 'value',
                    when: 'missing',
                  })
                }
              />
            </Field>
            <Section
              title="AST inspector"
              action={
                <button className="text-tertiary-fixed-dim hover:underline" onClick={() => setInspector((v) => !v)}>
                  {inspector ? 'Hide' : 'Show'}
                </button>
              }
            >
              {inspector && (
                <>
                  <Field label="AST">
                    <textarea className="field min-h-[70px] font-mono-label text-xs" value={String(draft.ast ?? '')} onChange={(e) => setField('ast', e.target.value)} />
                  </Field>
                  <Field label="Gate AST">
                    <textarea className="field min-h-[70px] font-mono-label text-xs" value={String(draft.gate_ast ?? '')} onChange={(e) => setField('gate_ast', e.target.value)} />
                  </Field>
                </>
              )}
            </Section>
          </>
        )}

        {node.agent === 'decision' && (
          <>
            <Section title="Judgment">
              <Field label="Mode">
                <select className="field" value={mode} onChange={(e) => setField('mode', e.target.value)}>
                  <option value="anomaly">Anomaly & Risk</option>
                  <option value="policy">Policy & Contract</option>
                  <option value="approval">Approval Gateway</option>
                </select>
              </Field>
              <Field label="Decision policy">
                <textarea className="field min-h-[90px]" value={String(draft.policy ?? '')} onChange={(e) => setField('policy', e.target.value)} />
              </Field>
              <Field label="Authority">
                <select className="field" value={String(draft.authority ?? 'autonomous')} onChange={(e) => setField('authority', e.target.value)}>
                  <option value="autonomous">Autonomous</option>
                  <option value="advisory">Advisory (human sign-off)</option>
                </select>
              </Field>
              <div>
                <div className="mb-1 flex justify-between font-mono-label text-on-surface-variant">
                  <span>Confidence threshold</span>
                  <span>{Number(draft.confidence_threshold ?? 0.85)}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  className="w-full accent-primary-fixed-dim"
                  value={Number(draft.confidence_threshold ?? 0.85)}
                  onChange={(e) => setField('confidence_threshold', Number(e.target.value))}
                />
              </div>
              <p className="font-mono-label text-on-surface-variant">Ports: approved · flagged · escalated</p>
            </Section>
          </>
        )}

        {node.agent === 'output' && (
          <>
            <Section title="Deliverable">
              <Field label="Mode">
                <select className="field" value={mode || String(draft.mode ?? 'excel')} onChange={(e) => setField('mode', e.target.value)}>
                  <option value="excel">Styled Excel</option>
                  <option value="pdf">Visual PDF</option>
                  <option value="both">Excel + PDF</option>
                </select>
              </Field>
              <Field label="Report title">
                <input className="field" value={String(draft.title ?? '')} onChange={(e) => setField('title', e.target.value)} />
              </Field>
              <Field label="File name">
                <input className="field" value={String(draft.filename ?? '')} onChange={(e) => setField('filename', e.target.value)} />
              </Field>
              <Field label="Theme">
                <select className="field" value={String(draft.theme ?? 'executive_classic')} onChange={(e) => setField('theme', e.target.value)}>
                  <option value="executive_classic">Executive Classic</option>
                  <option value="modern_slate">Modern Slate</option>
                  <option value="audit_clean">Audit Clean</option>
                </select>
              </Field>
            </Section>
            <Section title="Charts">
              {(['donut', 'variance', 'trend'] as const).map((chart) => {
                const charts = (draft.charts as Record<string, boolean> | undefined) ?? {}
                return (
                  <label key={chart} className="flex items-center gap-2 font-mono-label">
                    <input
                      type="checkbox"
                      checked={charts[chart] !== false}
                      onChange={(e) => setField('charts', { ...charts, [chart]: e.target.checked })}
                    />
                    {chart === 'donut' ? 'Match status donut' : chart === 'variance' ? 'Variance bars' : 'Balance trend'}
                  </label>
                )
              })}
              <p className="font-mono-label text-on-surface-variant">Local download only — no Slack / Teams / email in v1.</p>
            </Section>
          </>
        )}

        <Section
          title="Advanced"
          action={
            <button className="text-tertiary-fixed-dim hover:underline" onClick={() => setAdvanced((v) => !v)}>
              {advanced ? 'Hide' : 'Show'}
            </button>
          }
        >
          {advanced && (
            <>
              <Field label="Model">
                <input className="field" value={String(draft.model ?? '')} onChange={(e) => setField('model', e.target.value)} />
              </Field>
              <Field label="Temperature">
                <input
                  className="field"
                  type="number"
                  step={0.1}
                  value={Number(draft.temperature ?? 0.1)}
                  onChange={(e) => setField('temperature', Number(e.target.value))}
                />
              </Field>
            </>
          )}
        </Section>
      </div>

      <div className="flex gap-sm border-t border-[var(--ey-line)] bg-surface-container-low p-md">
        <button onClick={onClose} className="hover-tint flex-1 rounded-xl border border-[var(--ey-line)] px-4 py-2 font-label-md text-on-surface">
          Cancel
        </button>
        <button
          onClick={() => {
            onSync(node.id, draft)
            onClose()
          }}
          className="cta-sheen flex flex-1 items-center justify-center gap-xs rounded-xl bg-primary-container px-4 py-2 font-label-md font-bold text-on-primary-container hover:bg-primary-fixed"
        >
          <Icon name="sync" className="text-[18px]" />
          Sync Node
        </button>
      </div>
    </aside>
  )
}

function Section({
  title,
  action,
  children,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-[var(--ey-line)] bg-surface-container-low p-sm">
      <div className="mb-sm flex items-center justify-between border-b border-[var(--ey-line)] pb-2">
        <h3 className="font-label-md text-label-md text-on-surface">{title}</h3>
        {action}
      </div>
      <div className="flex flex-col gap-sm">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block font-mono-label text-on-surface-variant">{label}</label>
      {children}
    </div>
  )
}
