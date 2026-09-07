import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import Icon from '../components/Icon'
import TopNav from '../components/TopNav'
import WebGLBackground from '../components/WebGLBackground'
import { agents } from '../data/agents'

function Reveal({
  children,
  delay = 0,
  className = '',
}: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            el.style.animationDelay = `${delay}ms`
            el.classList.add('is-visible')
            observer.unobserve(el)
          }
        })
      },
      { threshold: 0.15 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [delay])

  return (
    <div ref={ref} className={`reveal ${className}`}>
      {children}
    </div>
  )
}

function MouseGlow({ tint = 'gold' }: { tint?: 'gold' | 'cyan' }) {
  const sectionRef = useRef<HTMLDivElement>(null)
  const orbRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const section = sectionRef.current
    const orb = orbRef.current
    if (!section || !orb) return

    let raf = 0
    const onMove = (e: MouseEvent) => {
      const rect = section.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        orb.style.transform = `translate3d(${x - 160}px, ${y - 160}px, 0)`
      })
    }
    window.addEventListener('mousemove', onMove)
    return () => {
      window.removeEventListener('mousemove', onMove)
      cancelAnimationFrame(raf)
    }
  }, [])

  const color = tint === 'cyan' ? 'bg-tertiary-fixed/10' : 'bg-primary-fixed/10'

  return (
    <div ref={sectionRef} className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        ref={orbRef}
        className={`absolute h-80 w-80 rounded-full blur-[100px] ${color}`}
      />
    </div>
  )
}

const processes = [
  {
    title: 'Record-to-Report',
    body: 'Automate ledger close, consolidation, and financial statement generation with absolute precision and traceable data lineage.',
    svg: (
      <svg className="h-full w-full p-4" viewBox="0 0 100 100" fill="none">
        <circle className="anim-float text-primary-fixed-dim" cx="20" cy="50" r="4" fill="currentColor" style={{ animationDelay: '0s' }} />
        <circle className="anim-pulse-ring anim-float relative text-primary-fixed-dim" cx="50" cy="50" r="6" fill="currentColor" style={{ animationDelay: '0.5s' }} />
        <circle className="anim-float text-primary-fixed-dim" cx="80" cy="50" r="4" fill="currentColor" style={{ animationDelay: '1s' }} />
        <path className="anim-data-flow text-primary-fixed-dim/50" d="M 24 50 L 44 50" stroke="currentColor" strokeWidth="1.5" />
        <path className="anim-data-flow text-primary-fixed-dim/50" d="M 56 50 L 76 50" stroke="currentColor" strokeWidth="1.5" />
        <rect className="text-primary-fixed-dim/30" x="42" y="30" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <rect className="text-primary-fixed-dim/30" x="42" y="60" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="1.5" />
        <path className="text-primary-fixed-dim/50" d="M 50 40 L 50 44" stroke="currentColor" strokeWidth="1.5" />
        <path className="text-primary-fixed-dim/50" d="M 50 56 L 50 60" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
  },
  {
    title: 'Procure-to-Pay',
    body: 'Streamline vendor onboarding, complex invoice processing, and payment execution through intelligent matching agents.',
    svg: (
      <svg className="h-full w-full p-4" viewBox="0 0 100 100" fill="none">
        <path className="text-primary-fixed-dim/30" d="M 30 70 L 30 30 L 70 30" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle className="text-primary-fixed-dim" cx="30" cy="70" r="3" fill="currentColor" />
        <circle className="text-primary-fixed-dim" cx="30" cy="30" r="3" fill="currentColor" />
        <circle className="text-primary-fixed-dim" cx="70" cy="30" r="3" fill="currentColor" />
        <path className="anim-data-flow text-primary-fixed-dim/50" d="M 50 50 L 70 70" stroke="currentColor" strokeWidth="1.5" />
        <circle className="anim-spin-slow text-primary-fixed-dim" cx="50" cy="50" r="5" fill="none" stroke="currentColor" strokeDasharray="4 4" strokeWidth="1.5" />
        <circle className="anim-pulse-ring relative text-primary-fixed-dim/20" cx="70" cy="70" r="6" fill="currentColor" />
        <circle className="text-primary-fixed-dim" cx="70" cy="70" r="2" fill="currentColor" />
      </svg>
    ),
  },
  {
    title: 'Order-to-Cash',
    body: 'Accelerate revenue recognition, autonomous billing generation, and smart collections with agent-driven follow-ups.',
    svg: (
      <svg className="h-full w-full p-4" viewBox="0 0 100 100" fill="none">
        <circle className="anim-spin-slow text-primary-fixed-dim/30" cx="50" cy="50" r="20" fill="none" stroke="currentColor" strokeDasharray="10 5" strokeWidth="1" />
        <circle className="text-primary-fixed-dim/20" cx="50" cy="50" r="30" fill="none" stroke="currentColor" strokeWidth="0.5" />
        <path className="text-primary-fixed-dim/60" d="M 50 15 L 50 25 M 85 50 L 75 50 M 50 85 L 50 75 M 15 50 L 25 50" stroke="currentColor" strokeWidth="2" />
        <circle className="anim-pulse-ring relative text-primary-fixed-dim" cx="50" cy="50" r="4" fill="currentColor" />
        <circle className="anim-float text-primary-fixed-dim" cx="30" cy="30" r="2" fill="currentColor" />
        <circle className="anim-float text-primary-fixed-dim" cx="70" cy="30" r="2" fill="currentColor" style={{ animationDelay: '1s' }} />
        <circle className="anim-float text-primary-fixed-dim" cx="70" cy="70" r="2" fill="currentColor" style={{ animationDelay: '0.5s' }} />
        <circle className="anim-float text-primary-fixed-dim" cx="30" cy="70" r="2" fill="currentColor" style={{ animationDelay: '1.5s' }} />
      </svg>
    ),
  },
  {
    title: 'FP&A',
    body: 'Turn actuals and forecasts into clear variance narratives, driver analysis, and management-ready insights.',
    svg: (
      <svg className="h-full w-full p-4" viewBox="0 0 100 100" fill="none">
        <line className="text-primary-fixed-dim/30" x1="12" y1="78" x2="88" y2="78" stroke="currentColor" strokeWidth="1" />
        <line className="text-primary-fixed-dim/30" x1="12" y1="78" x2="12" y2="18" stroke="currentColor" strokeWidth="1" />
        <rect className="anim-float text-tertiary-fixed-dim" x="24" y="52" width="12" height="26" rx="1.5" fill="currentColor" style={{ animationDelay: '0s' }} />
        <rect className="anim-float text-tertiary-fixed-dim" x="42" y="38" width="12" height="40" rx="1.5" fill="currentColor" style={{ animationDelay: '0.3s' }} />
        <rect className="anim-float text-tertiary-fixed-dim" x="60" y="28" width="12" height="50" rx="1.5" fill="currentColor" style={{ animationDelay: '0.6s' }} />
        <path className="anim-data-flow text-primary-fixed-dim/70" d="M 20 66 L 30 60 L 48 46 L 66 34 L 82 24" stroke="currentColor" strokeWidth="1.5" fill="none" />
        <circle className="anim-pulse-ring relative text-primary-fixed-dim" cx="82" cy="24" r="3.5" fill="currentColor" />
      </svg>
    ),
  },
]

export default function Landing() {
  return (
    <div className="relative flex min-h-screen flex-col overflow-x-hidden">
      <TopNav />
      <WebGLBackground />
      <section className="relative flex min-h-screen items-center justify-center px-gutter pb-24 pt-32 md:pb-32 md:pt-48">
        <div className="absolute inset-0 bg-gradient-to-b from-background/20 via-background/65 to-background" />
        <div className="relative z-10 mx-auto max-w-4xl text-center">
          <div className="mb-8">
            <div className="neu-raised inline-flex items-center gap-2 rounded-full px-3 py-1">
              <span className="h-2 w-2 animate-pulse rounded-full bg-primary-fixed-dim" />
              <span className="font-label-md text-label-md text-on-surface">
                Nexus 2.0 Engine Live
              </span>
            </div>
          </div>
          <h1 className="mb-6 text-[40px] font-bold leading-[48px] text-on-surface md:text-[64px] md:leading-[72px]">
            <span className="text-accent-grad">One platform.</span> <br />
            <span className="text-primary-fixed-dim">
              Every finance process. Intelligent agents.
            </span>
          </h1>
          <p className="mx-auto mb-10 max-w-2xl font-body-lg text-body-lg text-on-surface-variant">
            Define any finance workflow in natural language. Nexus autonomously
            assembles the optimal agent constellation, ingests your data, applies
            governed rules, and maintains human oversight.
          </p>
          <Link
            to="/architect"
            className="btn-primary-gradient cta-sheen group inline-flex w-full items-center justify-center gap-2 rounded-2xl px-8 py-4 font-label-md text-label-md text-on-primary-fixed sm:w-auto"
          >
            Enter the Platform
            <Icon name="arrow_forward" className="transition-transform duration-300 group-hover:translate-x-1" />
          </Link>
        </div>
      </section>

      <section className="relative z-10 overflow-hidden border-t border-[var(--ey-line)] bg-background px-gutter py-24">
        <div className="bg-grid-animated pointer-events-none absolute inset-0 opacity-30" />
        <div className="ambient-orb orb-drift-1 left-[-10%] top-[10%] h-72 w-72 bg-primary-fixed/10" />
        <div className="ambient-orb orb-drift-2 right-[-5%] bottom-[0%] h-80 w-80 bg-tertiary-fixed/10" />
        <MouseGlow tint="gold" />

        <div className="relative mx-auto max-w-[1440px] text-center">
          <Reveal>
            <h2 className="mb-16 font-headline-md text-headline-md text-on-surface">
              End-to-End{' '}
              <span className="bg-gradient-to-r from-primary-fixed to-primary-fixed-dim bg-clip-text text-transparent">
                Finance Orchestration
              </span>
            </h2>
          </Reveal>
          <div className="grid grid-cols-1 gap-8 text-left md:grid-cols-2 xl:grid-cols-4">
            {processes.map((p, i) => (
              <Reveal key={p.title} delay={i * 120} className="h-full">
                <div className="glass-panel lift group relative flex h-full flex-col rounded-xl p-8">
                  <div className="mb-6 flex h-48 items-center justify-center overflow-hidden rounded-lg border border-[var(--ey-line)] bg-surface-container">
                    <div className="absolute inset-0" />
                    {p.svg}
                  </div>
                  <h3 className="mb-3 font-headline-sm text-headline-sm text-on-surface">
                    {p.title}
                  </h3>
                  <p className="font-body-md text-body-md text-on-surface-variant">
                    {p.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="relative z-10 overflow-hidden border-t border-[var(--ey-line)] bg-background px-gutter py-24">
        <div className="bg-grid-animated pointer-events-none absolute inset-0 opacity-20" />
        <div className="ambient-orb orb-drift-2 right-[-10%] top-[0%] h-72 w-72 bg-primary-fixed/10" />
        <div className="ambient-orb orb-drift-1 left-[-8%] bottom-[5%] h-72 w-72 bg-tertiary-fixed/10" />
        <MouseGlow tint="cyan" />

        <div className="relative mx-auto max-w-[1440px]">
          <Reveal>
            <div className="mb-16 text-center">
              <h2 className="mb-4 font-headline-md text-headline-md text-on-surface">
                Meet the team
              </h2>
              <h3 className="mb-4 font-headline-sm text-headline-sm text-primary-fixed-dim">
                Core agents. Infinite workflows.
              </h3>
              <p className="mx-auto max-w-3xl font-body-md text-body-md text-on-surface-variant">
                A growing library of specialist agents powers every use case. Only
                the configuration changes.
              </p>
            </div>
          </Reveal>
          <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent, i) => (
              <Reveal key={agent.id} delay={i * 100}>
                <div className="glass-panel lift group flex h-full flex-col gap-4 rounded-xl bg-surface-bright p-6">
                  <div className="flex aspect-square items-center justify-center overflow-hidden rounded-lg border border-[var(--ey-line)] bg-surface-container">
                    <span
                      className={`material-symbols-outlined text-6xl text-primary-fixed-dim/50 transition-colors group-hover:text-primary-fixed-dim ${agent.topology.animation}`}
                    >
                      {agent.icon}
                    </span>
                  </div>
                  <div>
                    <h4 className="mb-2 font-headline-sm text-headline-sm text-on-surface">
                      {agent.name}
                    </h4>
                    <p className="font-body-md text-body-md text-sm text-on-surface-variant">
                      {agent.tagline}
                    </p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <footer className="relative z-10 mt-auto w-full border-t border-[var(--ey-line)] bg-background py-12">
        <div className="mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-8 px-gutter md:grid-cols-2">
          <div className="flex flex-col items-center gap-4 md:flex-row md:gap-8">
            <span className="font-headline-sm text-headline-sm text-primary-fixed-dim">
              Nexus 2.0
            </span>
            <span className="font-body-md text-body-md text-on-surface-variant">
              © 2024 Nexus 2.0 AI Studio. All rights reserved.
            </span>
          </div>
          <nav className="flex flex-wrap justify-center gap-6 md:justify-end">
            {['Privacy Policy', 'Terms of Service', 'Documentation', 'Support'].map(
              (label) => (
                <a
                  key={label}
                  href="#"
                  className="font-body-md text-body-md text-on-surface-variant transition-colors hover:text-primary-fixed-dim"
                >
                  {label}
                </a>
              ),
            )}
          </nav>
        </div>
      </footer>
    </div>
  )
}
