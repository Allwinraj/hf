import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useThemeVar } from '../lib/useThemeVar'
import { api } from '../lib/api'
import type { DashboardView, DashboardWidget } from '../types/nexus'

const COLORS = ['#FCA311', '#14213D', '#E5E5E5', '#000000', '#FCA311']

// Titles repeat across widgets, so the position keeps sibling keys unique.
function widgetKey(widget: DashboardWidget, position: number) {
  return `${widget.catalog_id}-${widget.source_port ?? ''}-${widget.title ?? ''}-${position}`
}

function useCountUp(value: number | undefined) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (value == null || Number.isNaN(value)) {
      setShown(0)
      return
    }
    const start = performance.now()
    const from = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 600)
      setShown(from + (value - from) * t)
      if (t < 1) requestAnimationFrame(tick)
    }
    const id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [value])
  return shown
}

function Kpi({ widget }: { widget: DashboardWidget }) {
  const shown = useCountUp(typeof widget.value === 'number' ? widget.value : undefined)
  const display =
    typeof widget.value === 'number'
      ? widget.unit === '%'
        ? shown.toFixed(1)
        : Number.isInteger(widget.value)
          ? Math.round(shown)
          : shown.toFixed(1)
      : widget.value ?? '—'
  return (
    <div className="neu-raised lift rail rounded-2xl p-5 pl-6" title={widget.explain?.why}>
      <div className="font-mono-label uppercase tracking-wider text-on-surface-variant">{widget.title}</div>
      <div className="mt-2 font-headline-lg text-headline-lg text-accent-grad">
        {display}
        {widget.unit ? <span className="ml-1 text-base text-on-surface-variant">{widget.unit}</span> : null}
      </div>
      {widget.subtitle ? <div className="mt-1 font-body-md text-sm text-on-surface-variant">{widget.subtitle}</div> : null}
      {widget.delta != null ? (
        <span className="chip chip-accent mt-2 font-mono-label">Δ {widget.delta}</span>
      ) : null}
      {widget.trend?.length ? (
        <div className="mt-2 h-8">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={widget.trend.map((value, index) => ({ name: index, value }))}>
              <Line type="monotone" dataKey="value" stroke="#FCA311" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </div>
  )
}

function ChartFrame({ widget, children }: { widget: DashboardWidget; children: ReactNode }) {
  return (
    <div className="neu-raised lift h-80 rounded-2xl p-4" title={widget.explain?.why}>
      <div className="mb-2 flex h-8 items-center justify-between gap-2">
        <div className="truncate font-label-md text-on-surface">{widget.title}</div>
        {widget.source_port ? <span className="chip font-mono-label">{widget.source_port}</span> : null}
      </div>
      <div className="h-[calc(100%_-_2.5rem)]">{children}</div>
    </div>
  )
}

function useTooltipStyle() {
  const card = useThemeVar('--ey-card', '#ffffff')
  const line = useThemeVar('--ey-line', '#e5e5e5')
  const ink = useThemeVar('--ey-ink', '#14213d')
  return useMemo(
    () => ({
      contentStyle: {
        background: card,
        border: `1px solid ${line}`,
        borderRadius: 12,
        color: ink,
        fontSize: 12,
      },
      labelStyle: { color: ink },
      itemStyle: { color: ink },
    }),
    [card, line, ink],
  )
}

export default function DashboardPanel({
  dashboard,
  runId,
  onMailChange,
}: {
  dashboard: DashboardView | null
  runId?: string
  onMailChange?: () => void
}) {
  const widgets = dashboard?.widgets || []
  const grid = useThemeVar('--ey-grid', '#E5E5E5')
  const ink = useThemeVar('--ey-ink', '#14213D')
  const tip = useTooltipStyle()
  const kpis = useMemo(() => widgets.filter((w) => w.catalog_id === 'kpi_card' || w.catalog_id === 'rate_gauge'), [widgets])
  const narratives = useMemo(() => widgets.filter((w) => w.catalog_id === 'narrative_card'), [widgets])
  const charts = useMemo(
    () =>
      widgets.filter((w) =>
        ['bar_chart', 'pie_chart', 'donut_chart', 'line_chart', 'area_chart', 'grouped_bar_chart', 'stacked_bar_chart', 'variance_chart'].includes(
          w.catalog_id,
        ),
      ),
    [widgets],
  )
  const tables = useMemo(
    () => widgets.filter((w) => ['insight_table', 'breakdown_table', 'exception_table', 'action_list', 'mail_reply_table'].includes(w.catalog_id)),
    [widgets],
  )

  if (!dashboard) {
    return (
      <div className="space-y-4 p-6">
        <p className="font-body-md text-on-surface-variant">Run the pipeline to build this dashboard.</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton h-28" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="skeleton h-64" />
          <div className="skeleton h-64" />
        </div>
      </div>
    )
  }

  const profile = dashboard.profile

  return (
    <div className="h-full min-h-0 space-y-4 overflow-y-auto overflow-x-hidden p-4">
      <div className="neu-inset rail rounded-2xl px-5 py-3">
        <div className="font-headline-sm text-accent-grad">{profile?.name || 'Run dashboard'}</div>
        <p className="mt-1 font-body-md text-sm text-on-surface-variant">
          {profile?.purpose || 'Charts follow this use case and the columns in the run.'}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {profile?.status ? <span className="chip chip-accent font-mono-label">{profile.status}</span> : null}
          {profile?.totals != null ? <span className="chip font-mono-label">{profile.totals} rows</span> : null}
          <span className="chip font-mono-label">{widgets.length} widgets</span>
        </div>
      </div>
      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((widget, position) => (
          <Kpi key={widgetKey(widget, position)} widget={widget} />
        ))}
      </div>
      {narratives.map((widget, position) => (
        <div
          key={widgetKey(widget, position)}
          className="neu-raised rail rounded-2xl p-5 pl-6 font-body-md text-on-surface"
        >
          {widget.text || widget.title}
        </div>
      ))}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {charts.map((widget, position) => {
          const data = (widget.data || []) as Record<string, unknown>[]
          const chartKey = widgetKey(widget, position)
          if (widget.catalog_id === 'bar_chart' || widget.catalog_id === 'variance_chart') {
            return (
              <ChartFrame key={chartKey} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    <Bar dataKey="value" fill="#FCA311" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'grouped_bar_chart') {
            return (
              <ChartFrame key={chartKey} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    <Bar dataKey="actual" fill="#FCA311" />
                    <Bar dataKey="expected" fill="#14213D" />
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'stacked_bar_chart') {
            const series = widget.series || ['value']
            return (
              <ChartFrame key={chartKey} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    {series.map((key, index) => (
                      <Bar key={key} dataKey={key} stackId="a" fill={COLORS[index % COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'line_chart' || widget.catalog_id === 'area_chart') {
            return (
              <ChartFrame key={chartKey} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  {widget.catalog_id === 'area_chart' ? (
                    <AreaChart data={data}>
                      <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                      <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                      <YAxis tick={{ fill: ink, fontSize: 11 }} />
                      <Tooltip {...tip} />
                      <Area type="monotone" dataKey="value" stroke="#FCA311" fill="#FCA311" fillOpacity={0.25} />
                    </AreaChart>
                  ) : (
                    <LineChart data={data}>
                      <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                      <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                      <YAxis tick={{ fill: ink, fontSize: 11 }} />
                      <Tooltip {...tip} />
                      <Line type="monotone" dataKey="value" stroke="#FCA311" strokeWidth={2} dot={false} />
                    </LineChart>
                  )}
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          const donut = widget.catalog_id === 'donut_chart'
          return (
            <ChartFrame key={chartKey} widget={widget}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data} dataKey="value" nameKey="name" innerRadius={donut ? 48 : 0} outerRadius={80}>
                    {data.map((_, index) => (
                      <Cell key={index} fill={COLORS[index % COLORS.length]} stroke={ink} />
                    ))}
                  </Pie>
                  <Tooltip {...tip} />
                </PieChart>
              </ResponsiveContainer>
            </ChartFrame>
          )
        })}
        {tables.map((widget, position) => {
          if (widget.catalog_id === 'mail_reply_table') {
            return (
              <MailReplyTable
                key={widgetKey(widget, position)}
                widget={widget}
                runId={runId}
                onMailChange={onMailChange}
              />
            )
          }
          if (widget.catalog_id === 'action_list') {
            return (
              <div key={widgetKey(widget, position)} className="neu-raised lift rounded-2xl p-4">
                <div className="mb-3 font-label-md text-on-surface">{widget.title}</div>
                <ul className="stagger space-y-2">
                  {(widget.actions || []).map((item) => (
                    <li key={item} className="neu-inset rail rounded-xl px-4 py-2 font-body-md text-on-surface">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )
          }
          return (
            <div
              key={widgetKey(widget, position)}
              className="neu-raised lift flex max-h-80 min-h-0 flex-col overflow-hidden rounded-2xl p-4"
            >
              <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
                <div className="font-label-md text-on-surface">{widget.title}</div>
                <span className="chip font-mono-label">{(widget.rows || []).length} rows</span>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="data-table w-full text-left font-body-md text-sm">
                  <thead className="sticky top-0 z-10 bg-surface">
                    <tr>
                      {(widget.columns || []).map((col) => (
                        <th
                          key={col}
                          className="border-b border-[var(--ey-line)] bg-surface pb-2 pr-3 font-mono-label uppercase tracking-wider text-on-surface-variant"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(widget.rows || []).map((row, index) => (
                      <tr key={index} className="border-t border-[var(--ey-line)] transition-colors">
                        {(widget.columns || []).map((col) => (
                          <td key={col} className="py-2 pr-3 text-on-surface">
                            {String(row[col] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MailReplyTable({
  widget,
  runId,
  onMailChange,
}: {
  widget: DashboardWidget
  runId?: string
  onMailChange?: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const rows = (widget.mail_rows || widget.rows || []) as Record<string, unknown>[]
  const act = async (action: 'send' | 'skip' | 'send_all', mailId?: string) => {
    if (!runId) return
    setBusy(mailId || action)
    try {
      await api.sendMail(runId, action, mailId ? [mailId] : [])
      if (action !== 'send_all') setOpenId(null)
      await onMailChange?.()
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="neu-raised lift col-span-full flex max-h-[40rem] min-h-0 flex-col overflow-hidden rounded-2xl p-4">
      <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
        <div>
          <div className="font-label-md text-on-surface">{widget.title}</div>
          <p className="mt-1 font-mono-label text-on-surface-variant">
            Double-click a row to expand the draft reply. Edit it, then Send.
          </p>
        </div>
        <button
          className="cta-sheen rounded-xl bg-primary-container px-3 py-1.5 font-label-md font-bold text-on-primary-container disabled:opacity-50"
          disabled={!runId || busy != null}
          onClick={() => void act('send_all')}
        >
          {busy === 'send_all' ? 'Sending…' : 'Send all'}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="data-table w-full text-left font-body-md text-sm">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr>
              {['subject', 'from', 'item', 'verdict', 'status', ''].map((col) => (
                <th
                  key={col}
                  className="border-b border-[var(--ey-line)] bg-surface pb-2 pr-3 font-mono-label uppercase tracking-wider text-on-surface-variant"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const mailId = String(row.mail_id ?? '')
              const status = String(row.send_status ?? 'draft')
              const open = openId === mailId
              return (
                <Fragment key={mailId || String(row.subject)}>
                  <tr
                    className="cursor-pointer border-t border-[var(--ey-line)] hover:bg-[color-mix(in_srgb,var(--ey-accent)_8%,transparent)]"
                    onDoubleClick={() => setOpenId(open ? null : mailId)}
                  >
                    <td className="py-2 pr-3 text-on-surface">{String(row.subject ?? '')}</td>
                    <td className="py-2 pr-3 text-on-surface">{String(row.from ?? '')}</td>
                    <td className="py-2 pr-3 text-on-surface">{String(row.item ?? '')}</td>
                    <td className="py-2 pr-3 text-on-surface">{String(row.verdict ?? '')}</td>
                    <td className="py-2 pr-3 text-on-surface">{status}</td>
                    <td className="py-2 pr-3">
                      {status === 'draft' && runId ? (
                        <div className="flex gap-2" onDoubleClick={(event) => event.stopPropagation()}>
                          <button
                            className="rounded-lg border border-[var(--ey-line)] px-2 py-1 font-mono-label disabled:opacity-50"
                            disabled={busy != null}
                            onClick={() => void act('send', mailId)}
                          >
                            Send
                          </button>
                          <button
                            className="rounded-lg border border-[var(--ey-line)] px-2 py-1 font-mono-label disabled:opacity-50"
                            disabled={busy != null}
                            onClick={() => void act('skip', mailId)}
                          >
                            Don&apos;t send
                          </button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                  {open ? (
                    <tr className="border-t border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-line)_18%,transparent)]">
                      <td colSpan={6} className="p-3">
                        <MailDraftEditor
                          key={mailId}
                          row={row}
                          runId={runId}
                          busy={busy}
                          onClose={() => setOpenId(null)}
                          onSaved={async () => {
                            await onMailChange?.()
                          }}
                          onSend={(id) => void act('send', id)}
                          onSkip={(id) => void act('skip', id)}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function addressFrom(row: Record<string, unknown>) {
  const explicit = String(row.to_address ?? '').trim()
  if (explicit) return explicit
  const from = String(row.from ?? '')
  const match = from.match(/<([^>]+)>/)
  return match ? match[1] : from
}

function MailDraftEditor({
  row,
  runId,
  busy,
  onClose,
  onSaved,
  onSend,
  onSkip,
}: {
  row: Record<string, unknown>
  runId?: string
  busy: string | null
  onClose: () => void
  onSaved: (row: Record<string, unknown>) => void | Promise<void>
  onSend: (mailId: string) => void
  onSkip: (mailId: string) => void
}) {
  const mailId = String(row.mail_id ?? '')
  const status = String(row.send_status ?? 'draft')
  const editable = status === 'draft'
  const [toAddress, setToAddress] = useState(addressFrom(row))
  const [subject, setSubject] = useState(String(row.draft_subject ?? `Re: ${row.subject ?? ''}`))
  const [body, setBody] = useState(String(row.draft_body ?? ''))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    if (!runId || !editable) return false
    setSaving(true)
    setError(null)
    try {
      const result = await api.saveMailDraft(runId, {
        mail_id: mailId,
        to_address: toAddress,
        draft_subject: subject,
        draft_body: body,
      })
      await onSaved(result.row)
      return true
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not save draft')
      return false
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-label-md text-on-surface">Draft reply</div>
          <p className="mt-1 font-body-md text-sm text-on-surface-variant">
            {String(row.verdict ?? 'pending').toString().toUpperCase()}
            {row.explanation ? ` — ${String(row.explanation)}` : ''}
          </p>
        </div>
        <button className="hover-tint rounded-full px-2 py-1 font-mono-label" onClick={onClose}>
          Collapse
        </button>
      </div>
      <label className="block">
        <span className="mb-1 block font-mono-label text-on-surface-variant">To</span>
        <input className="field" value={toAddress} disabled={!editable} onChange={(e) => setToAddress(e.target.value)} />
      </label>
      <label className="block">
        <span className="mb-1 block font-mono-label text-on-surface-variant">Subject</span>
        <input className="field" value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="block">
        <span className="mb-1 block font-mono-label text-on-surface-variant">Message</span>
        <textarea
          className="field min-h-[180px] whitespace-pre-wrap"
          value={body}
          disabled={!editable}
          onChange={(e) => setBody(e.target.value)}
        />
      </label>
      {error ? <p className="font-body-md text-sm text-error">{error}</p> : null}
      <div className="flex flex-wrap justify-end gap-2">
        {editable && runId ? (
          <>
            <button
              className="rounded-xl border border-[var(--ey-line)] px-3 py-2 font-label-md disabled:opacity-50"
              disabled={saving || busy != null}
              onClick={() => void save()}
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
            <button
              className="rounded-xl border border-[var(--ey-line)] px-3 py-2 font-label-md disabled:opacity-50"
              disabled={saving || busy != null}
              onClick={() =>
                void save().then((ok) => {
                  if (ok) onSkip(mailId)
                })
              }
            >
              Don&apos;t send
            </button>
            <button
              className="cta-sheen rounded-xl bg-primary-container px-3 py-2 font-label-md font-bold text-on-primary-container disabled:opacity-50"
              disabled={saving || busy != null}
              onClick={() =>
                void save().then((ok) => {
                  if (ok) onSend(mailId)
                })
              }
            >
              Send
            </button>
          </>
        ) : (
          <button className="rounded-xl border border-[var(--ey-line)] px-3 py-2 font-label-md" onClick={onClose}>
            Collapse
          </button>
        )}
      </div>
    </div>
  )
}
