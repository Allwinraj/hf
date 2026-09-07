import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import type { ColumnCard, RowTrace, SheetCard, SheetPage } from '../types/nexus'
import RowExplain from './RowExplain'

const EXCEPTION_PORTS = new Set(['exceptions', 'flagged', 'escalated', 'residuals'])

export default function SheetGrid({
  pipelineId,
  runId,
  sheets,
  columns,
  active,
  onActive,
  onSelectColumn,
  expandable = false,
  hint,
}: {
  pipelineId: string
  runId: string
  sheets: SheetCard[]
  columns?: ColumnCard[]
  active: SheetCard | null
  onActive: (sheet: SheetCard) => void
  onSelectColumn?: (column: string) => void
  expandable?: boolean
  hint?: ReactNode
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState(0)
  const [page, setPage] = useState<SheetPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [onlyExceptions, setOnlyExceptions] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<number>>(new Set())
  const [traces, setTraces] = useState<Record<number, RowTrace>>({})
  const [loading, setLoading] = useState<Record<number, boolean>>({})
  const [traceError, setTraceError] = useState<Record<number, string>>({})
  const limit = 40

  // The sheet can be far wider than the pane, so the expanded panel is sized to
  // the visible area instead of the full table width.
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const measure = () => setViewport(el.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    setOffset(0)
    setOpen(new Set())
    setTraces({})
    setLoading({})
    setTraceError({})
  }, [active?.node_id, active?.port, onlyExceptions])

  useEffect(() => {
    if (!active) return
    let cancelled = false
    api
      .getSheetRows(pipelineId, runId, active.node_id, active.port, {
        offset,
        limit,
        only_exceptions: onlyExceptions,
      })
      .then((body) => {
        if (!cancelled) setPage(body)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load sheet')
      })
    return () => {
      cancelled = true
    }
  }, [pipelineId, runId, active?.node_id, active?.port, offset, onlyExceptions])

  const originByCol = useMemo(() => {
    const map = new Map<string, ColumnCard>()
    for (const col of columns || []) {
      if (active && col.port && col.port !== active.port) continue
      map.set(col.column, col)
    }
    return map
  }, [columns, active])

  const toggleRow = (index: number) => {
    if (!expandable || !active) return
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
        return next
      }
      next.add(index)
      return next
    })
    if (traces[index] || loading[index]) return
    setLoading((prev) => ({ ...prev, [index]: true }))
    api
      .explainRow(pipelineId, runId, active.node_id, active.port, index)
      .then((body) => {
        setTraces((prev) => ({ ...prev, [index]: body }))
        setTraceError((prev) => {
          const next = { ...prev }
          delete next[index]
          return next
        })
      })
      .catch((err: unknown) => {
        setTraceError((prev) => ({
          ...prev,
          [index]: err instanceof Error ? err.message : 'Could not explain this row',
        }))
      })
      .finally(() => setLoading((prev) => ({ ...prev, [index]: false })))
  }

  if (!sheets.length) {
    return <p className="p-4 font-body-md text-on-surface-variant">No output sheets on this run.</p>
  }

  const cols = page?.columns || active?.columns || []
  const rows = page?.rows || []
  const total = page?.total || active?.row_count || 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_5%,transparent)] px-3 py-2">
        {sheets.map((sheet) => (
          <button
            key={`${sheet.node_id}-${sheet.port}`}
            type="button"
            onClick={() => onActive(sheet)}
            className={`flex items-center gap-2 overflow-hidden rounded-xl px-3 py-1.5 font-label-md transition-all duration-200 ${
              active?.node_id === sheet.node_id && active?.port === sheet.port
                ? 'rail neu-btn-active bg-primary-container pl-4 text-on-primary-container'
                : 'neu-btn text-on-surface hover:-translate-y-0.5'
            }`}
          >
            {sheet.sheet_name}
            <span className="chip font-mono-label">{sheet.row_count}</span>
          </button>
        ))}
        {expandable ? (
          <label
            className={`hover-tint ml-auto flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 font-label-md ${
              onlyExceptions
                ? 'border-primary-fixed-dim/60 bg-[color-mix(in_srgb,var(--ey-accent)_14%,transparent)] text-on-surface'
                : 'border-[var(--ey-line)] text-on-surface-variant'
            }`}
          >
            <input
              type="checkbox"
              className="accent-[#fca311]"
              checked={onlyExceptions}
              onChange={(e) => setOnlyExceptions(e.target.checked)}
            />
            Exceptions only
          </label>
        ) : null}
      </div>
      {hint ? (
        <p className="border-b border-[var(--ey-line)] px-4 py-2 font-body-md text-sm text-on-surface-variant">{hint}</p>
      ) : active?.purpose ? (
        <p className="border-b border-[var(--ey-line)] px-4 py-2 font-body-md text-sm text-on-surface-variant">
          {active.purpose}
        </p>
      ) : null}
      {error ? <p className="px-4 py-2 font-body-md text-red-500">{error}</p> : null}
      <div ref={scroller} className="min-h-0 flex-1 overflow-auto">
        <table className="data-table w-full min-w-max text-left font-body-md text-sm">
          <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_var(--ey-line)]">
            <tr>
              <th className="bg-surface px-3 py-2 font-mono-label text-on-surface-variant">
                {expandable ? '' : '#'}
              </th>
              {cols.map((col) => (
                <th key={col} className="bg-surface px-3 py-2">
                  <button
                    type="button"
                    className="text-left font-mono-label uppercase tracking-wider text-on-surface-variant transition-colors hover:text-primary-fixed-dim"
                    onClick={() => onSelectColumn?.(col)}
                    title={originByCol.get(col)?.why}
                  >
                    {col}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const index = Number(row._row_index ?? 0)
              const flagged =
                EXCEPTION_PORTS.has(active?.port || '') ||
                ['flagged', 'escalated', 'unmatched', 'exceptions'].includes(String(row.verdict || row.status || ''))
              const isOpen = open.has(index)
              return (
                <Fragment key={index}>
                  <tr
                    className={`border-t border-[var(--ey-line)] transition-colors ${
                      expandable ? 'cursor-pointer select-none' : ''
                    } ${isOpen ? 'bg-primary-container/30' : flagged ? 'bg-primary-fixed/10' : ''}`}
                    title={expandable ? 'Double-click to open the calculation for this row' : undefined}
                    onDoubleClick={() => toggleRow(index)}
                  >
                    <td className="px-3 py-2 font-mono-label text-on-surface-variant">
                      {expandable ? (
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          aria-label={isOpen ? 'Collapse this row' : 'Expand this row'}
                          className="hover-tint rounded-md px-1"
                          onClick={(event) => {
                            event.stopPropagation()
                            toggleRow(index)
                          }}
                        >
                          <span
                            className={`inline-block transition-transform duration-200 ${
                              isOpen ? 'rotate-90 text-primary-fixed-dim' : ''
                            }`}
                          >
                            ▸
                          </span>
                        </button>
                      ) : (
                        index + 1
                      )}
                    </td>
                    {cols.map((col) => {
                      const value = row[col]
                      const numeric = typeof value === 'number'
                      return (
                        <td
                          key={col}
                          className={`px-3 py-2 text-on-surface ${numeric ? 'text-right tabular-nums' : ''}`}
                        >
                          {value == null ? '' : String(value)}
                        </td>
                      )
                    })}
                  </tr>
                  {isOpen ? (
                    <tr className="border-t border-[var(--ey-line)]">
                      <td colSpan={cols.length + 1} className="p-0">
                        <div
                          className="rise sticky left-0 max-w-full border-l-[3px] border-l-primary-fixed-dim bg-[color-mix(in_srgb,var(--ey-page)_70%,transparent)] px-4 py-3"
                          style={viewport ? { width: viewport } : undefined}
                        >
                          <RowExplain
                            trace={traces[index] || null}
                            loading={loading[index]}
                            error={traceError[index]}
                          />
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-[var(--ey-line)] bg-[color-mix(in_srgb,var(--ey-accent)_5%,transparent)] px-4 py-2 font-label-md text-on-surface-variant">
        <span className="tabular-nums">
          {Math.min(offset + 1, total)}–{Math.min(offset + rows.length, total)} of {total}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="neu-btn rounded-xl px-3 py-1 disabled:opacity-40"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            Prev
          </button>
          <button
            type="button"
            className="neu-btn rounded-xl px-3 py-1 disabled:opacity-40"
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
