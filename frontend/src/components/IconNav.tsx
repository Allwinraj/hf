import { NavLink } from 'react-router-dom'
import Icon from './Icon'

const items = [
  { to: '/architect', icon: 'dashboard', label: 'Overview' },
  { to: '/architect/skills', icon: 'account_tree', label: 'Skill Library' },
  { to: '/architect/create', icon: 'smart_toy', label: 'Create Agent' },
  { to: '/agents', icon: 'grid_view', label: 'Library' },
]

export default function IconNav() {
  return (
    <nav
      className="z-20 flex w-16 shrink-0 flex-col items-center gap-2 border-r border-[var(--ey-line)] bg-background py-4"
      aria-label="Architect studio"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          aria-label={item.label}
          className={({ isActive }) =>
            `group relative flex h-11 w-11 items-center justify-center rounded-xl transition-all duration-200 ${
              isActive
                ? 'neu-btn-active text-primary-fixed-dim'
                : 'neu-btn text-on-surface-variant hover:scale-105 hover:text-on-surface'
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive ? (
                <span
                  aria-hidden="true"
                  className="absolute -left-2 top-1/2 h-6 w-1 -translate-y-1/2 rounded-full bg-primary-container"
                />
              ) : null}
              <Icon name={item.icon} className="text-[22px]" />
              <span className="pointer-events-none absolute left-full z-50 ml-3 whitespace-nowrap rounded-lg border border-[var(--ey-line)] bg-surface px-2.5 py-1 font-mono-label text-on-surface opacity-0 shadow-[var(--neu-raised)] transition-opacity group-hover:opacity-100">
                {item.label}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
