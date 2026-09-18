import { useState } from 'react'
import { AuthProvider, useAuth } from '@/lib/AuthContext'
import { useIsAdmin } from '@/lib/useAccount'
import { LoginScreen } from '@/screens/LoginScreen'
import { DatabaseScreen } from '@/screens/DatabaseScreen'
import { PipelineScreen } from '@/screens/PipelineScreen'
import { CockpitScreen } from '@/screens/CockpitScreen'

type Ecran = 'database' | 'pipeline' | 'cockpit'

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
  // Base de données et Trieur de Data restent visibles pour tout compte
  // ayant accès à au moins un environnement.
  const onglets: [Ecran, string][] = [
    ['database', 'Base de données'],
    ['pipeline', 'Trieur de Data'],
    ...(isAdmin ? ([['cockpit', 'Cockpit']] as [Ecran, string][]) : []),
  ]

  return (
    <div>
      <nav className="flex gap-1 border-b border-[var(--border)] bg-[var(--card)] px-4 pt-2">
        {onglets.map(([key, label]) => (
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
      {ecran === 'cockpit' && isAdmin && <CockpitScreen />}
      {ecran === 'pipeline' && <PipelineScreen />}
      {(ecran === 'database' || (ecran === 'cockpit' && !isAdmin)) && <DatabaseScreen />}
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
