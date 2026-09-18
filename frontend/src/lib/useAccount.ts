// Hooks partagés "quel compte, quels environnements" -- utilisés par
// DatabaseScreen ET CockpitScreen. Avant, chaque écran refaisait son
// propre useEffect(listOrgs)/useEffect(getMe) : deux copies de la même
// règle ("les orgs accessibles", "suis-je admin ?") qui pouvaient
// diverger silencieusement -- une seule source de vérité ici.

import { useEffect, useState } from 'react'
import { ApiError, getMe, listOrgs, type Organization } from './api'

export function useOrgs() {
  const [orgs, setOrgs] = useState<Organization[] | null>(null)
  const [orgsError, setOrgsError] = useState<string | null>(null)
  const [orgId, setOrgId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listOrgs()
      .then((data) => {
        if (cancelled) return
        setOrgs(data)
        if (data.length > 0) setOrgId(data[0].id)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setOrgsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { orgs, orgsError, orgId, setOrgId }
}

// `ready` doit valoir false tant que la session Supabase n'est pas
// restaurée/obtenue (voir AuthContext.loading) -- sinon getMe() part
// AVANT que le jeton existe (App.tsx monte ce hook sans attendre la fin
// du chargement de la session), échoue silencieusement (catch
// ci-dessous), et comme l'effet ne dépendait que de [] il ne se
// relançait JAMAIS après coup : isAdmin restait faux pour toujours après
// un login normal, l'onglet Cockpit n'apparaissait jamais pour un admin
// (revue PR #24, point #3). En dépendant de `ready`, l'effet se relance
// dès que la session devient disponible.
export function useIsAdmin(ready: boolean) {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!ready) return
    let cancelled = false
    getMe()
      .then((data) => {
        if (!cancelled) setIsAdmin(Boolean(data.profile.is_super_admin))
      })
      .catch(() => {
        // Pas bloquant : en cas d'échec, on reste en lecture seule /
        // sans accès Cockpit.
        if (!cancelled) setIsAdmin(false)
      })
      .finally(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [ready])

  return { isAdmin, loaded }
}
