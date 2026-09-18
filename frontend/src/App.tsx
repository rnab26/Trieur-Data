import { useState } from 'react'
import { AuthProvider, useAuth } from '@/lib/AuthContext'
import { useIsAdmin } from '@/lib/useAccount'
import { LoginScreen } from '@/screens/LoginScreen'
import { DatabaseScreen } from '@/screens/DatabaseScreen'
import { CockpitScreen } from '@/screens/CockpitScreen'

type Ecran = 'database' | 'cockpit'

function AppContent() {
  const { session, loading } = useAuth()
  const { isAdmin } = useIsAdmin()
  const [ecran, setEcran] = useState<Ecran>('database')

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-[var(--muted)]">Chargement…</p>
      </div>
    )
  }

  if (!session) {
    return <LoginScreen />
  }

  // Le Cockpit est réservé aux administrateurs -- même règle que côté
  // API (require_cockpit_access) : un compte non-admin ne voit même
  // pas l'onglet, plutôt que d'ouvrir un écran qui échouerait en 403.
  return (
    <div>
      {isAdmin && (
        <nav className="flex gap-1 border-b border-[var(--border)] bg-[var(--card)] px-4 pt-2">
          {([
            ['database', 'Base de données'],
            ['cockpit', 'Cockpit'],
          ] as [Ecran, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setEcran(key)}
              className={
                'rounded-t-md px-3 py-2 text-sm font-medium ' +
                (ecran === key
                  ? 'bg-[var(--background)] text-[var(--foreground)]'
                  : 'text-[var(--muted)] hover:text-[var(--foreground)]')
              }
            >
              {label}
            </button>
          ))}
        </nav>
      )}
      {ecran === 'cockpit' && isAdmin ? <CockpitScreen /> : <DatabaseScreen />}
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
