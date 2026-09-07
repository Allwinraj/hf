type Status = 'published' | 'draft'

const config: Record<
  Status,
  { label: string; className: string; dot: string; icon: string }
> = {
  published: {
    label: 'Published',
    className:
      'border-tertiary-fixed-dim/20 bg-tertiary-fixed-dim/10 text-tertiary-fixed-dim',
    dot: 'bg-tertiary-fixed-dim',
    icon: 'check_circle',
  },
  draft: {
    label: 'Draft',
    className:
      'border-surface-tint/30 bg-surface-tint/10 text-surface-tint',
    dot: 'bg-surface-tint',
    icon: 'draft',
  },
}

export default function StatusPill({ status }: { status: Status }) {
  const c = config[status]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-label-md text-[11px] ${c.className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden="true" />
      {c.label}
    </span>
  )
}
