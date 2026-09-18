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

export function useIsAdmin() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    getMe()
      .then((data) => {
        if (!cancelled) setIsAdmin(Boolean(data.profile.is_super_admin))
      })
      .catch(() => {
        // Pas bloquant : en cas d'échec, on reste en lecture seule /
        // sans accès Cockpit.
      })
      .finally(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { isAdmin, loaded }
}
