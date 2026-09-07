import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'nexus.architect.chatRatio'
const MIN_PANE = 200

export default function ResizableSplit({
  left,
  right,
  defaultWidth = 340,
}: {
  left: ReactNode
  right: ReactNode
  defaultWidth?: number
}) {
  const root = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(defaultWidth)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startW = useRef(width)

  const clamp = useCallback((next: number) => {
    const total = root.current?.clientWidth ?? window.innerWidth
    const max = Math.max(MIN_PANE, total - MIN_PANE)
    return Math.min(max, Math.max(MIN_PANE, next))
  }, [])

  useEffect(() => {
    const total = root.current?.clientWidth ?? 0
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const ratio = Number(saved)
        if (Number.isFinite(ratio) && total) {
          setWidth(clamp(ratio * total))
          return
        }
      }
    } catch {
      /* ignore */
    }
    if (total) setWidth(clamp(defaultWidth))
  }, [clamp, defaultWidth])

  useEffect(() => {
    const el = root.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      setWidth((current) => clamp(current))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [clamp])

  const onMove = useCallback(
    (event: MouseEvent) => {
      if (!dragging.current) return
      setWidth(clamp(startW.current + event.clientX - startX.current))
    },
    [clamp],
  )

  const onUp = useCallback(() => {
    if (!dragging.current) return
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    const total = root.current?.clientWidth || 1
    try {
      localStorage.setItem(STORAGE_KEY, String(width / total))
    } catch {
      /* ignore */
    }
  }, [width])

  useEffect(() => {
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [onMove, onUp])

  return (
    <div ref={root} className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex h-full min-h-0 flex-shrink-0 flex-col overflow-hidden" style={{ width }}>
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize chat panel"
        title="Drag to resize"
        className="group relative z-10 w-2 shrink-0 cursor-col-resize split-handle transition-colors hover:bg-primary-fixed-dim"
        onMouseDown={(event) => {
          dragging.current = true
          startX.current = event.clientX
          startW.current = width
          document.body.style.cursor = 'col-resize'
          document.body.style.userSelect = 'none'
        }}
      >
        <div className="absolute inset-y-0 -left-1 -right-1" />
        <div className="absolute left-1/2 top-1/2 h-14 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-fixed-dim" />
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{right}</div>
    </div>
  )
}
