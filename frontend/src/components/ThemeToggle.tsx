import { useTheme } from '../context/ThemeContext'
import Icon from './Icon'

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const isLight = theme === 'light'

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isLight}
      aria-label={isLight ? 'Switch to dark theme' : 'Switch to light theme'}
      className="neu-inset flex items-center gap-2 rounded-full p-1"
      onClick={() => setTheme(isLight ? 'dark' : 'light')}
    >
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-full transition-all ${
          !isLight ? 'bg-primary-container text-on-primary-container neu-raised' : 'text-on-surface-variant'
        }`}
      >
        <Icon name="dark_mode" className="text-[18px]" />
      </span>
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-full transition-all ${
          isLight ? 'bg-primary-container text-on-primary-container neu-raised' : 'text-on-surface-variant'
        }`}
      >
        <Icon name="light_mode" className="text-[18px]" />
      </span>
    </button>
  )
}
