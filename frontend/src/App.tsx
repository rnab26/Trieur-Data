import { Component, lazy, Suspense, useState, type ReactNode } from 'react'
import { AuthProvider, useAuth } from '@/lib/AuthContext'
import { useIsAdmin } from '@/lib/useAccount'
import { LoginScreen } from '@/screens/LoginScreen'

// Chargement à la demande, un chunk par écran (audit bundle-size) : la
// plupart des comptes ne chargent jamais le Cockpit (réservé aux admins),
// et ouvrir juste la Base de données n'a plus besoin de télécharger/parser
// le code du Pipeline (651 lignes) ou du Cockpit (448 lignes).
const DatabaseScreen = lazy(() =>
  import('@/screens/DatabaseScreen').then((m) => ({ default: m.DatabaseScreen })),
)
const PipelineScreen = lazy(() =>
  import('@/screens/PipelineScreen').then((m) => ({ default: m.PipelineScreen })),
)
const CockpitScreen = lazy(() =>
  import('@/screens/CockpitScreen').then((m) => ({ default: m.CockpitScreen })),
)

function EcranFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <p className="text-sm text-[var(--muted)]">Chargement…</p>
    </div>
  )
}

// Filet pour le decoupage par ecran (chunk par ecran, voir plus haut) :
// si le navigateur a garde en cache une page qui reference un chunk JS
// disparu depuis (remplace par un redeploiement -- nom de fichier
// different a chaque build), le "import()" dynamique echoue avec une
// vraie exception. Sans ce filet, React demonte l'arbre en silence ->
// ecran blanc, aucune erreur visible (constate en reel). Un seul
// rechargement automatique suffit puisqu'il recupere alors le nouvel
// index.html avec les bons noms de chunks -- au-dela, on affiche un
// message au lieu de boucler.
class EcranErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch() {
    const key = 'trieur_ecran_reload_once'
    if (!sessionStorage.getItem(key)) {
      sessionStorage.setItem(key, '1')
      window.location.reload()
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4 text-center">
          <p className="text-sm text-[var(--foreground)]">
            Le chargement a échoué (nouvelle version disponible).
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-md bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]"
          >
            Recharger la page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

type Ecran = 'database' | 'pipeline' | 'cockpit'

function AppContent() {
  const { session, loading } = useAuth()
  const { isAdmin } = useIsAdmin(!loading && Boolean(session))
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
      <EcranErrorBoundary>
        <Suspense fallback={<EcranFallback />}>
          {ecran === 'cockpit' && isAdmin && <CockpitScreen />}
          {ecran === 'pipeline' && <PipelineScreen />}
          {(ecran === 'database' || (ecran === 'cockpit' && !isAdmin)) && <DatabaseScreen />}
        </Suspense>
      </EcranErrorBoundary>
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
