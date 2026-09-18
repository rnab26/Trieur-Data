import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError, getMasterColumns, setMasterColumns } from '@/lib/api'
import { PersonalColumnSets } from './PersonalColumnSets'

// Copie conforme de views/tab1_colonnes_maitres.py : UN textarea (une
// colonne par ligne) + UN bouton "Enregistrer" qui remplace toute la
// liste (dédoublonnage insensible à la casse, ordre préservé -- même
// logique que le `deduped` cote Python), + UN bouton "Réinitialiser".
// Pas d'ajout/renommage/suppression un par un : éditer le texte et
// ré-enregistrer couvre tous les cas, exactement comme l'original.
const DEFAULT_MASTER_COLUMNS = [
  'NOM', 'PRENOM', 'GENRE/CIVILITE', 'VILLE', 'CP', 'ADRESSE',
  'TELEPHONE MOBILE', 'TELEPHONE FIXE', 'EMAIL', 'DATE DE NAISSANCE', 'Source Data',
]

function dedupePreservingOrder(lines: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of lines) {
    const c = raw.trim()
    if (!c) continue
    const key = c.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(c)
  }
  return out
}

export function MasterColumnsPanel({
  orgId,
  isAdmin,
  onSaved,
}: {
  orgId: string
  isAdmin: boolean
  // Appelé après toute modification persistée -- permet à l'écran
  // parent (ex. PipelineScreen, qui garde sa propre copie des colonnes
  // maîtres pour le mapping/les filtres) de la recharger sans dupliquer
  // ici la logique de fetch. Optionnel : DatabaseScreen n'en a pas
  // besoin, il relit déjà getMasterColumns séparément pour BulkActions.
  onSaved?: () => void
}) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getMasterColumns(orgId)
      .then((data) => {
        if (cancelled) return
        setText(data.columns.join('\n'))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  async function persist(next: string[], successMessage: string) {
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(null)
    try {
      await setMasterColumns(orgId, next)
      setText(next.join('\n'))
      setSaveSuccess(successMessage)
      onSaved?.()
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  function handleSave() {
    const deduped = dedupePreservingOrder(text.split('\n'))
    if (deduped.length === 0) {
      setSaveError('Veuillez entrer au moins une colonne maître.')
      setSaveSuccess(null)
      return
    }
    void persist(deduped, `${deduped.length} colonnes maîtres enregistrées et conservées.`)
  }

  function handleReset() {
    void persist(DEFAULT_MASTER_COLUMNS.slice(), 'Liste réinitialisée aux colonnes par défaut.')
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Gérer vos colonnes maîtres</h2>
        <p className="text-sm text-[var(--muted)]">
          {isAdmin
            ? 'Ajoutez, supprimez ou modifiez vos colonnes maîtres ci-dessous, une par ligne. La liste est conservée après rechargement de la page.'
            : 'Colonnes de cet environnement, modifiables par un administrateur uniquement.'}
        </p>
      </div>

      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && !loading && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && !error && (
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          readOnly={!isAdmin}
          rows={12}
          className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)]"
        />
      )}

      {isAdmin && !loading && !error && (
        <div className="flex items-center gap-2">
          <Button onClick={handleSave} disabled={saving}>
            💾 Enregistrer la liste des colonnes maîtres
          </Button>
          <Button variant="secondary" onClick={handleReset} disabled={saving}>
            ↩️ Réinitialiser (liste par défaut)
          </Button>
        </div>
      )}

      {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
      {saveSuccess && !saveError && <p className="text-sm text-[var(--success,#16a34a)]">{saveSuccess}</p>}
      {saving && <p className="text-sm text-[var(--muted)]">Enregistrement…</p>}

      <p className="text-sm text-[var(--muted)]">
        ℹ️ Astuce : les colonnes <strong>TELEPHONE MOBILE</strong> et <strong>TELEPHONE FIXE</strong> sont
        détectées automatiquement d'après le contenu (préfixes 06/07 = mobile, 01-05/08/09 = fixe), même si
        l'en-tête est absente ou trompeuse.
      </p>

      <PersonalColumnSets />
    </div>
  )
}
