// Hooks partagés "quel compte, quels environnements" -- utilisés par
// DatabaseScreen ET CockpitScreen. Avant, chaque écran refaisait son
// propre useEffect(listOrgs)/useEffect(getMe) : deux copies de la même
// règle ("les orgs accessibles", "suis-je admin ?") qui pouvaient
// diverger silencieusement -- une seule source de vérité ici.

import { useEffect, useState } from 'react'
import { ApiError, getMe, listOrgs, type Organization } from './api'

// Cache module-level (survit aux démontages/remontages du composant, PAS
// aux rechargements de page) -- App.tsx démonte entièrement l'écran actif
// à chaque changement d'onglet du haut (Base de données / Trieur de Data
// / Cockpit, voir App.tsx), donc CHAQUE bascule relançait sinon un aller-
// retour réseau à vide : la barre d'onglets et le sélecteur
// d'environnement (conditionnés à `orgs`/`orgId`) disparaissaient
// complètement du DOM le temps de la requête, sans aucun indicateur --
// l'écran blanc entre deux menus signalé par Raphaël. Ça faisait aussi
// perdre l'environnement choisi à chaque bascule, silencieusement. Le
// cache sert le dernier résultat connu IMMÉDIATEMENT au remontage (plus
// de blanc, sélection conservée), pendant qu'un nouvel appel réseau
// revalide en arrière-plan.
let cachedOrgs: Organization[] | null = null
let cachedOrgsError: string | null = null
let cachedOrgId: string | null = null
let cachedIsAdmin: boolean | null = null

// À appeler à la déconnexion (voir AuthContext.signOut) -- signOut() ne
// recharge pas la page, donc sans ce nettoyage explicite, une connexion
// avec un AUTRE compte dans le même onglet verrait un instant les
// environnements/le statut admin du compte précédent, le temps que le
// nouvel appel réseau écrase le cache.
export function clearAccountCache() {
  cachedOrgs = null
  cachedOrgsError = null
  cachedOrgId = null
  cachedIsAdmin = null
}

export function useOrgs() {
  const [orgs, setOrgs] = useState<Organization[] | null>(cachedOrgs)
  const [orgsError, setOrgsError] = useState<string | null>(cachedOrgsError)
  const [orgId, setOrgIdState] = useState<string | null>(cachedOrgId)

  function setOrgId(id: string | null) {
    cachedOrgId = id
    setOrgIdState(id)
  }

  useEffect(() => {
    let cancelled = false
    listOrgs()
      .then((data) => {
        if (cancelled) return
        cachedOrgs = data
        cachedOrgsError = null
        setOrgs(data)
        // Ne touche à orgId QUE si rien n'est encore choisi, ou si
        // l'environnement choisi n'existe plus dans la liste fraîche
        // (accès retiré entre-temps) -- ne jamais écraser un choix
        // manuel encore valide par le 1er de la liste.
        if (cachedOrgId == null || !data.some((o) => o.id === cachedOrgId)) {
          const next = data.length > 0 ? data[0].id : null
          cachedOrgId = next
          setOrgIdState(next)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const msg = err instanceof ApiError ? err.message : 'Erreur inconnue.'
        cachedOrgsError = msg
        setOrgsError(msg)
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
// Même cache que cachedOrgs ci-dessus (déclaré plus haut), même raison :
// sans lui, chaque remontage d'écran (changement d'onglet du haut)
// repart de `isAdmin = false` le temps de la requête -- un admin voyait
// ses contrôles admin/l'onglet Cockpit disparaître puis réapparaître à
// chaque bascule.
export function useIsAdmin(ready: boolean) {
  const [isAdmin, setIsAdmin] = useState(cachedIsAdmin ?? false)
  const [loaded, setLoaded] = useState(cachedIsAdmin !== null)

  useEffect(() => {
    if (!ready) return
    let cancelled = false
    getMe()
      .then((data) => {
        // Écrit le cache SEULEMENT si cet appel n'a pas été annulé
        // (revue Copilot, PR #30) -- un getMe() lancé avant un
        // démontage/déconnexion peut se résoudre APRÈS coup ; sans ce
        // garde, il réinjecterait le statut admin de l'ancien compte
        // dans le cache partagé, visible par un remontage suivant même
        // pour un autre compte.
        if (cancelled) return
        const value = Boolean(data.profile.is_super_admin)
        cachedIsAdmin = value
        setIsAdmin(value)
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
