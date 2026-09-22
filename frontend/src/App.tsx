import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { AuthProvider, useAuth } from '@/lib/AuthContext'
import { useIsAdmin } from '@/lib/useAccount'
import { LoginScreen } from '@/screens/LoginScreen'
import { ThemeToggle } from '@/components/ThemeToggle'

// Chargement à la demande, un chunk par écran (audit bundle-size) : la
// plupart des comptes ne chargent jamais le Cockpit (réservé aux admins),
// et ouvrir juste la Base de données n'a plus besoin de télécharger/parser
// le code du Pipeline (651 lignes) ou du Cockpit (448 lignes). Chaque
// import() est gardé à part (pas juste passé à lazy()) pour pouvoir aussi
// être appelé depuis prefetchEcrans() ci-dessous, sans dupliquer le
// chemin du module.
const importDatabaseScreen = () =>
  import('@/screens/DatabaseScreen').then((m) => ({ default: m.DatabaseScreen }))
const importPipelineScreen = () =>
  import('@/screens/PipelineScreen').then((m) => ({ default: m.PipelineScreen }))
const importCockpitScreen = () =>
  import('@/screens/CockpitScreen').then((m) => ({ default: m.CockpitScreen }))
const importPrelevementScreen = () =>
  import('@/screens/PrelevementScreen').then((m) => ({ default: m.PrelevementScreen }))

const DatabaseScreen = lazy(importDatabaseScreen)
const PipelineScreen = lazy(importPipelineScreen)
const CockpitScreen = lazy(importCockpitScreen)
const PrelevementScreen = lazy(importPrelevementScreen)

// Bug réel signalé par Raphaël (2026-09-22) : "quand on clique ça met un
// peu de blanc après ça charge" -- le premier clic sur un onglet pas
// encore ouvert télécharge son chunk JS à ce moment-là, donc l'écran
// "Chargement…" (fallback Suspense) s'affiche brièvement. Précharge tous
// les chunks en tâche de fond, une fois la page bien affichée et le
// réseau plus libre (requestIdleCallback, jamais pendant le premier
// rendu) -- par le temps où l'utilisateur clique sur un autre onglet, le
// chunk est déjà en cache navigateur et `lazy()` le résout instantanément,
// sans repasser par le réseau ni afficher le fallback.
function prefetchEcrans(isAdmin: boolean) {
  const importers = isAdmin
    ? [importDatabaseScreen, importPipelineScreen, importCockpitScreen, importPrelevementScreen]
    : [importDatabaseScreen, importPipelineScreen]
  for (const importer of importers) {
    importer().catch(() => {
      // Silencieux : un échec de préchargement n'empêche pas le clic
      // normal de réessayer via lazy() au moment voulu.
    })
  }
}

function EcranFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <p className="text-sm text-[var(--muted)]">Chargement…</p>
    </div>
  )
}

// Filet pour le découpage par écran (chunk par écran, voir plus haut) :
// si le navigateur a gardé en cache une page qui référence un chunk JS
// disparu depuis (remplacé par un redéploiement -- nom de fichier
// différent à chaque build), le "import()" dynamique échoue avec une
// vraie exception. Sans ce filet, React démonte l'arbre en silence ->
// écran blanc ou contenu manquant, aucune erreur visible (bug réel déjà
// rencontré et corrigé le 2026-09-18 sur une autre branche, jamais porté
// sur main -- reproduit le 2026-09-22 : le père de Raphaël ne voyait
// aucune des nouvelles questions de règle après un déploiement, page
// restée sur un chunk périmé). Un seul rechargement automatique suffit
// puisqu'il récupère alors le nouvel index.html avec les bons noms de
// chunks -- au-delà, on affiche un message au lieu de boucler.
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

type Ecran = 'database' | 'pipeline' | 'cockpit' | 'prelevement'

function AppContent() {
  const { session, loading } = useAuth()
  const { isAdmin, loaded: isAdminLoaded } = useIsAdmin(!loading && Boolean(session))
  // Trieur de Data par défaut (usage quotidien) -- Base de données et
  // Cockpit restent accessibles via les onglets du haut.
  const [ecran, setEcran] = useState<Ecran>('pipeline')

  // Précharge les autres écrans dès que le statut admin est connu (donc
  // dès que la liste d'onglets définitive est connue) -- voir
  // prefetchEcrans ci-dessus.
  useEffect(() => {
    if (!isAdminLoaded) return
    const idle = 'requestIdleCallback' in window ? window.requestIdleCallback : (cb: () => void) => setTimeout(cb, 300)
    const cancelIdle = 'cancelIdleCallback' in window ? window.cancelIdleCallback : clearTimeout
    const handle = idle(() => prefetchEcrans(isAdmin))
    return () => cancelIdle(handle as never)
  }, [isAdminLoaded, isAdmin])

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

  // Bug réel signalé par Raphaël (2026-09-22) : "ya que base de donnee et
  // data qui saffiche en premier et apres ya prélèvement et cockpit en
  // decalage" -- avant, la barre d'onglets s'affichait dès la session
  // connue, avec seulement "Base de données"/"Trieur de Data" (isAdmin
  // valant faux le temps d'un aller-retour réseau), puis "Prélèvement"/
  // "Cockpit" apparaissaient d'un coup une fois le statut admin résolu :
  // décalage visible de la barre d'onglets. Attendre isAdminLoaded ici
  // (après avoir confirmé qu'une session existe, sinon un compte non
  // connecté resterait bloqué sur "Chargement…" -- useIsAdmin(ready=false)
  // ne se déclenche jamais, `loaded` ne devient donc jamais vrai) affiche
  // la barre UNE SEULE FOIS, déjà complète -- jamais deux étapes.
  if (!isAdminLoaded) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-[var(--muted)]">Chargement…</p>
      </div>
    )
  }

  // Le Cockpit est réservé aux administrateurs -- même règle que côté
  // API (require_cockpit_access) : un compte non-admin ne voit même
  // pas l'onglet, plutôt que d'ouvrir un écran qui échouerait en 403.
  // Base de données et Trieur de Data restent visibles pour tout compte
  // ayant accès à au moins un environnement.
  const onglets: [Ecran, string][] = [
    ['database', 'Base de données'],
    ['pipeline', 'Trieur de Data'],
    ...(isAdmin
      ? ([
          ['prelevement', 'Prélèvement'],
          ['cockpit', 'Cockpit'],
        ] as [Ecran, string][])
      : []),
  ]

  return (
    <div>
      <nav className="flex items-center justify-between gap-1 border-b border-[var(--border)] bg-[var(--card)] px-4 pt-2">
        <div className="flex gap-1">
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
        </div>
        <div className="pb-2">
          <ThemeToggle />
        </div>
      </nav>
      <EcranErrorBoundary>
        <Suspense fallback={<EcranFallback />}>
          {ecran === 'cockpit' && isAdmin && <CockpitScreen />}
          {ecran === 'prelevement' && isAdmin && <PrelevementScreen />}
          {ecran === 'pipeline' && <PipelineScreen />}
          {(ecran === 'database' || ((ecran === 'cockpit' || ecran === 'prelevement') && !isAdmin)) && (
            <DatabaseScreen />
          )}
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
