// Cockpit central (rnab26/Cockpit-General) dans le menu du Trieur : un bouton « Demandes »
// qui ouvre la boîte de demandes (écrire une demande ou un bug, voir où ça en est).
// Réservé aux administrateurs : même règle que l'onglet Cockpit (useIsAdmin, voir App.tsx).
//
// C'est la balise donnée par le cockpit après son questionnaire d'emplacement (2026-10-14 :
// emplacement = bouton dans le menu, accès = l'équipe), posée par le code parce que ce site
// est une appli React, pas une page HTML où on la collerait à la main :
//   <script src="…/cockpit-embed.js" data-cle="…" data-utilisateur="…"
//           data-mode="bouton" data-declencheur="#cockpit-central-lien"></script>
// Sur un petit écran (< LARGEUR_MENU_PX) le menu du Trieur est déjà trop large : le module garde alors
// son bouton flottant habituel (en bas à droite) au lieu d'un bouton de plus dans le menu.
// La clé sert seulement à reconnaître le projet : elle ne donne aucun accès à la base, elle est
// faite pour figurer dans le code d'un site (d'où sa présence ici, dans un dépôt public).

export const COCKPIT_EMBED_URL = 'https://rnab26.github.io/Cockpit-General/embed/cockpit-embed.js'
export const COCKPIT_CLE = 'af4a4775a19f4cddb0df05cc88fa768daf06c4f881cc413d97a255ea0af10a5c'
/** Identifiant du bouton du menu : le module le cherche au chargement (data-declencheur). */
export const COCKPIT_LIEN_ID = 'cockpit-central-lien'
/** Libellé du bouton flottant du module : sert aussi à le retrouver pour le retirer. */
const LIBELLE = 'Demandes'
const MARQUE = 'data-cockpit-central'
/** Mesuré (14 oct. 2026) : le menu d'un administrateur fait ~600 px avec ce bouton ; en dessous, il déborde. */
export const LARGEUR_MENU_PX = 640

/** Le menu a-t-il la place d'accueillir le bouton ? (décidé une fois par chargement de page, voir CockpitCentral) */
export function menuAssezLarge(win: Window): boolean {
  return win.matchMedia(`(min-width: ${LARGEUR_MENU_PX}px)`).matches
}

/** Nom montré dans le cockpit pour ce compte : la partie avant le « @ » de l'e-mail. */
export function nomPourCockpit(email: string | null | undefined): string {
  const local = (email ?? '').split('@')[0]?.trim() ?? ''
  return local ? local.slice(0, 40) : 'Équipe'
}

/**
 * Ajoute la balise du module à la page, une seule fois. Le bouton du menu doit DÉJÀ exister :
 * le module le cherche une seule fois, au chargement, et sans lui poserait un bouton flottant.
 * dansLeMenu = faux : pas de bouton dans le menu, le module pose son bouton flottant.
 */
export function poserBalise(doc: Document, utilisateur: string, dansLeMenu: boolean): void {
  if (doc.querySelector(`script[${MARQUE}]`)) return
  const s = doc.createElement('script')
  s.src = COCKPIT_EMBED_URL
  s.async = true
  s.setAttribute(MARQUE, '1')
  s.setAttribute('data-cle', COCKPIT_CLE)
  s.setAttribute('data-utilisateur', utilisateur)
  s.setAttribute('data-mode', 'bouton')
  s.setAttribute('data-libelle', LIBELLE)
  // Sans data-declencheur, le module pose son propre bouton flottant.
  if (dansLeMenu) s.setAttribute('data-declencheur', `#${COCKPIT_LIEN_ID}`)
  doc.body.appendChild(s)
}

/** Retire la balise et tout ce que le module a posé (panneau, bouton flottant), à la fermeture du menu. */
export function retirerBalise(doc: Document): void {
  // Panneau ouvert : on le referme par son chemin normal (Échap), pour qu'il défasse son entrée d'historique.
  const hote = doc.querySelector<HTMLElement>('.cockpit-embed')
  if (hote && hote.style.display === 'block') doc.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  doc.querySelectorAll(`script[${MARQUE}]`).forEach((n) => n.remove())
  doc.querySelectorAll('.cockpit-embed').forEach((n) => n.remove())
  doc.querySelectorAll(`body > button[aria-label="${LIBELLE}"]`).forEach((n) => n.remove())
}
