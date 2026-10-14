import { useEffect, useState } from 'react'
import { useAuth } from '@/lib/AuthContext'
import { COCKPIT_LIEN_ID, menuAssezLarge, nomPourCockpit, poserBalise, retirerBalise } from '@/lib/cockpitCentral'

// Bouton du menu qui ouvre le cockpit central (écrire une demande ou un bug, voir où ça en est).
// À ne rendre QUE pour un administrateur (voir App.tsx : même règle que l'onglet Cockpit).
//
// Écran large : un bouton « Demandes » dans le menu. Petit écran : le menu du Trieur déborde déjà
// (il fait ~500 px), donc aucun bouton ici et le module pose son bouton flottant habituel.
// Le choix est fait UNE fois par chargement de page : le module se lie au bouton du menu à son
// chargement et ne le cherche plus ensuite.
//
// L'effet s'exécute après l'affichage du bouton : le module le trouve alors par son identifiant.
// Le nettoyage retire la balise quand le menu disparaît (déconnexion sans rechargement de page),
// pour qu'un autre compte ne trouve pas un panneau resté accroché à un bouton disparu.
export function CockpitCentral() {
  const { session } = useAuth()
  const utilisateur = nomPourCockpit(session?.user?.email)
  const [dansLeMenu] = useState(() => menuAssezLarge(window))

  useEffect(() => {
    poserBalise(document, utilisateur, dansLeMenu)
    return () => retirerBalise(document)
  }, [utilisateur, dansLeMenu])

  if (!dansLeMenu) return null
  return (
    <button
      id={COCKPIT_LIEN_ID}
      type="button"
      title="Écrire une demande ou signaler un problème (cockpit central)"
      className="min-h-9 rounded-md bg-[var(--card)] px-3 text-sm font-medium text-[var(--muted)] shadow-[var(--ring-card)] hover:text-[var(--foreground)]"
    >
      Demandes
    </button>
  )
}
