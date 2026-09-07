import { useEffect, useState } from 'react'

export function useThemeVar(name: string, fallback: string) {
  const [color, setColor] = useState(fallback)
  useEffect(() => {
    const read = () => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
      if (value) setColor(value)
    }
    read()
    const observer = new MutationObserver(read)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [name])
  return color
}
