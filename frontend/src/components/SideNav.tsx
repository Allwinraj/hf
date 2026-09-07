import { NavLink } from 'react-router-dom'
import Icon from './Icon'

const items = [
  { to: '/architect', icon: 'dashboard', label: 'Overview' },
  { to: '/architect/skills', icon: 'account_tree', label: 'Skill Library' },
  { to: '/architect/create', icon: 'smart_toy', label: 'Create Agent' },
  { to: '/agents', icon: 'grid_view', label: 'Library' },
]

export default function SideNav() {
  return (
    <aside className="hidden w-64 flex-shrink-0 flex-col gap-sm border-r border-[var(--ey-line)] bg-background p-sm md:flex">
      <nav className="stagger mt-lg flex flex-col gap-xs" aria-label="Architect studio">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `group flex items-center gap-sm overflow-hidden rounded-2xl px-sm py-xs font-label-md text-label-md transition-all duration-200 ${
                isActive
                  ? 'rail neu-btn-active bg-primary-container text-on-primary-container'
                  : 'neu-btn text-on-surface-variant hover:translate-x-0.5 hover:text-on-surface'
              }`
            }
          >
            <Icon name={item.icon} className="transition-transform duration-200 group-hover:scale-110" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
