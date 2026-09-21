import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

// Réglage clair/sombre/auto demandé par Raphaël (2026-09-21) -- avant,
// seul le Cockpit forçait le sombre (.cockpit-dark, demande explicite
// passée), le reste de l'appli suivait juste le système sans réglage
// possible. Un seul réglage pour toute l'appli désormais : "auto" laisse
// le système décider (prefers-color-scheme), "clair"/"sombre" forcent
// l'un ou l'autre partout, y compris le Cockpit.

export type Theme = 'clair' | 'sombre' | 'auto'

const STORAGE_KEY = 'trieur-data-theme'

const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void } | null>(null)

function lire(): Theme {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'clair' || v === 'sombre' || v === 'auto') return v
  } catch {
    // Stockage indisponible (navigation privée, etc.) -- repli silencieux
    // sur "auto", jamais bloquant pour l'affichage.
  }
  return 'auto'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(lire)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'auto') {
      root.removeAttribute('data-theme')
    } else {
      root.setAttribute('data-theme', theme === 'clair' ? 'light' : 'dark')
    }
  }, [theme])

  function setTheme(t: Theme) {
    setThemeState(t)
    try {
      localStorage.setItem(STORAGE_KEY, t)
    } catch {
      // Pas grave si ça ne persiste pas -- le réglage reste actif pour
      // cette visite, juste pas mémorisé pour la prochaine.
    }
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme doit être utilisé sous <ThemeProvider>.')
  return ctx
}
