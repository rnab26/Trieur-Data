import { MasterColumnsPanel } from '@/screens/MasterColumnsPanel'

// Onglet 1 du Trieur de Data -- mirroir de views/tab1_colonnes_maitres.py
// ("Gérer vos colonnes maîtres"). Réutilise TEL QUEL le composant déjà
// écrit pour Base de données → Colonnes maîtres (MasterColumnsPanel +
// PersonalColumnSets) : "colonnes maîtres" est UNE seule notion pour tout
// l'environnement (voir api/main.py, section Colonnes maîtres) -- créer
// une deuxième liste ici serait exactement la dérive que le CLAUDE.md du
// projet interdit ("une seule source de vérité"). Les fonctionnalités du
// Python (créer/nommer/appliquer/supprimer un jeu de colonnes, dernier
// jeu mémorisé par compte) sont donc déjà couvertes par ce composant --
// voir PersonalColumnSets.tsx pour la mémoire par compte.
export function Tab1ColonnesMaitres({
  orgId,
  isAdmin,
  onColumnsChange,
}: {
  orgId: string
  isAdmin: boolean
  onColumnsChange?: (columns: string[]) => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Gérer vos colonnes maîtres</h2>
        <p className="text-sm text-[var(--muted)]">
          Ajoutez, supprimez ou modifiez vos colonnes maîtres ci-dessous. La liste est conservée
          pour cet environnement et réutilisée par le mapping (étape 2) et le filtrage (étape 3).
        </p>
        <p className="mt-1 text-xs text-[var(--muted)]">
          Astuce : les colonnes <strong>TELEPHONE MOBILE</strong> et <strong>TELEPHONE FIXE</strong>{' '}
          sont détectées automatiquement d'après le contenu (préfixes 06/07 = mobile, 01-05/08/09 =
          fixe), même si l'en-tête source est absente ou trompeuse.
        </p>
      </div>
      <MasterColumnsPanel orgId={orgId} isAdmin={isAdmin} onColumnsChange={onColumnsChange} />
    </div>
  )
}
