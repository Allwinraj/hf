export default function TypingDots({ label = 'Thinking' }: { label?: string }) {
  return (
    <span className="flex items-center gap-2 font-body-md text-sm text-on-surface-variant">
      <span className="flex items-end gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="typing-dot h-1.5 w-1.5 rounded-full bg-primary-fixed-dim"
            style={{ animationDelay: `${i * 0.18}s` }}
          />
        ))}
      </span>
      {label}…
    </span>
  )
}
