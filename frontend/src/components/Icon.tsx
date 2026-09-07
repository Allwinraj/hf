export type IconName = string

export default function Icon({
  name,
  className = '',
  fill = false,
}: {
  name: string
  className?: string
  fill?: boolean
}) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined ${fill ? 'fill-icon' : ''} ${className}`}
    >
      {name}
    </span>
  )
}
