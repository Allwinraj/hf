import { Link, useLocation } from 'react-router-dom'
import Icon from './Icon'
import ThemeToggle from './ThemeToggle'

export default function TopNav() {
  const location = useLocation()
  const isArchitect = location.pathname.startsWith('/architect')

  return (
    <header className="fixed top-0 z-50 w-full border-b border-[var(--ey-line)] bg-background/95 shadow-[var(--neu-raised)] backdrop-blur-xl">
      <span
        aria-hidden="true"
        className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-primary-fixed-dim/60 to-transparent"
      />
      <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-gutter">
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <Link
            to="/"
            className="flex items-center gap-2 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-dashed focus-visible:outline-primary-fixed-dim"
          >
            <Icon name="dataset" className="text-primary-fixed-dim" fill />
            <span className="font-headline-sm text-headline-sm font-bold tracking-tight text-on-surface">
              Nexus 2.0
            </span>
          </Link>
        </div>

        <nav className="hidden gap-2 md:flex" aria-label="Primary">
          {[
            { to: '/architect', label: 'Architect', active: isArchitect },
            { to: '/agents', label: 'Agents', active: location.pathname === '/agents' },
          ].map((tab) => (
            <Link
              key={tab.to}
              to={tab.to}
              className={`relative rounded-full px-4 py-2 font-label-md text-label-md transition-all duration-300 ${
                tab.active
                  ? 'text-primary-fixed-dim'
                  : 'hover-tint text-on-surface-variant hover:text-primary-fixed-dim'
              }`}
            >
              {tab.label}
              {tab.active ? (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-3 -bottom-0.5 h-0.5 rounded-full bg-gradient-to-r from-transparent via-primary-fixed-dim to-transparent"
                />
              ) : null}
            </Link>
          ))}
        </nav>

        <Link
          to="/architect"
          className="cta-sheen neu-btn rounded-2xl px-4 py-2 font-label-md text-label-md text-on-surface hover:text-primary-fixed-dim"
        >
          Launch Architect
        </Link>
      </div>
    </header>
  )
}
