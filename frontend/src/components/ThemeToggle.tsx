import { useTheme, type Theme } from '@/lib/ThemeContext'

// Trois boutons plutôt qu'un menu déroulant -- l'état choisi est visible
// d'un coup d'œil, pas besoin d'ouvrir quoi que ce soit pour savoir sur
// quel réglage on est (Raphaël, 2026-09-21 : "le plus simple possible").
const OPTIONS: { value: Theme; label: string; title: string }[] = [
  { value: 'clair', label: '☀️', title: 'Thème clair' },
  { value: 'sombre', label: '🌙', title: 'Thème sombre' },
  { value: 'auto', label: '💻', title: 'Suivre le réglage du téléphone/ordinateur' },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <div className="inline-flex overflow-hidden rounded-md shadow-[var(--ring-card)]">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          title={opt.title}
          aria-label={opt.title}
          aria-pressed={theme === opt.value}
          onClick={() => setTheme(opt.value)}
          className={
            'px-2 py-1 text-sm ' +
            (theme === opt.value
              ? 'bg-[var(--primary)] text-[var(--primary-foreground)]'
              : 'bg-[var(--card)] text-[var(--muted)] hover:text-[var(--foreground)]')
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
