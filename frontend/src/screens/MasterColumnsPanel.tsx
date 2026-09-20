import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, getMasterColumns, setMasterColumns } from '@/lib/api'
import { PersonalColumnSets } from './PersonalColumnSets'

// Réglages des colonnes maîtres de l'environnement -- mirroir de
// views/tab_database.py:_render_settings. `save_org_master_columns`
// (trieur/db.py) remplace TOUJOURS la liste complète et ordonnée : pas
// besoin d'endpoints séparés pour renommer/réordonner/supprimer, on
// renvoie chaque fois la liste entière modifiée via le même
// POST /orgs/{org_id}/master-columns (déjà réservé aux administrateurs
// côté API).
export function MasterColumnsPanel({
  orgId,
  isAdmin,
  onColumnsChange,
}: {
  orgId: string
  isAdmin: boolean
  // Optionnel : notifie un parent qui a besoin de connaître la liste à
  // jour (ex. l'onglet "Import et Mapping" du Trieur de Data, qui cible
  // ces mêmes colonnes maîtres) -- DatabaseScreen ne le passe pas, aucun
  // changement de comportement pour lui.
  onColumnsChange?: (columns: string[]) => void
}) {
  const [columns, setColumns] = useState<string[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [newCol, setNewCol] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getMasterColumns(orgId)
      .then((data) => {
        if (cancelled) return
        setColumns(data.columns)
        onColumnsChange?.(data.columns)
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

  async function persist(next: string[]) {
    setSaving(true)
    setSaveError(null)
    try {
      await setMasterColumns(orgId, next)
      setColumns(next)
      onColumnsChange?.(next)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  function moveUp(i: number) {
    if (!columns || i === 0) return
    const next = [...columns]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    void persist(next)
  }

  function moveDown(i: number) {
    if (!columns || i === columns.length - 1) return
    const next = [...columns]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    void persist(next)
  }

  function rename(i: number, name: string) {
    if (!columns) return
    const next = [...columns]
    next[i] = name
    setColumns(next) // reflète la frappe sans attendre la sauvegarde
  }

  function commitRename(i: number) {
    if (!columns) return
    const name = columns[i].trim()
    if (!name) return
    void persist(columns.map((c, idx) => (idx === i ? name : c)))
  }

  function removeAt(i: number) {
    if (!columns) return
    const name = columns[i]
    if (!window.confirm(`Supprimer la colonne « ${name} » des réglages de cet environnement ?\n\nLes clients déjà importés ne sont pas modifiés -- seuls l'affichage et le prochain import s'adaptent.`)) {
      return
    }
    void persist(columns.filter((_, idx) => idx !== i))
  }

  function addColumn() {
    if (!columns) return
    const name = newCol.trim()
    if (!name) return
    if (columns.some((c) => c.toLowerCase() === name.toLowerCase())) {
      setSaveError('Cette colonne existe déjà.')
      return
    }
    void persist([...columns, name]).then(() => setNewCol(''))
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Colonnes maîtres de l'environnement</h2>
        <p className="text-sm text-[var(--muted)]">
          {isAdmin
            ? "Crée, renomme, réordonne ou supprime les colonnes de cet environnement. Les clients déjà importés ne sont pas modifiés -- seuls l'affichage et le prochain import s'adaptent."
            : 'Colonnes de cet environnement, modifiables par un administrateur uniquement.'}
        </p>
      </div>

      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && !loading && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && !error && columns && columns.length === 0 && (
        <p className="text-sm text-[var(--muted)]">Aucune colonne définie pour l'instant.</p>
      )}

      {!loading && !error && columns && columns.length > 0 && (
        <ul className="flex flex-col gap-2">
          {columns.map((col, i) => (
            <li key={i} className="flex items-center gap-2">
              {isAdmin ? (
                <Input
                  value={col}
                  onChange={(e) => rename(i, e.target.value)}
                  onBlur={() => commitRename(i)}
                  className="max-w-xs"
                />
              ) : (
                <span className="text-sm">{col}</span>
              )}
              {isAdmin && (
                <>
                  <Button variant="secondary" onClick={() => moveUp(i)} disabled={i === 0 || saving}>
                    ⬆️
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => moveDown(i)}
                    disabled={i === columns.length - 1 || saving}
                  >
                    ⬇️
                  </Button>
                  <Button variant="danger" onClick={() => removeAt(i)} disabled={saving}>
                    🗑️
                  </Button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {isAdmin && !loading && !error && (
        <div className="flex items-center gap-2">
          <Input
            placeholder="Nouvelle colonne"
            value={newCol}
            onChange={(e) => setNewCol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addColumn()
            }}
            className="max-w-xs"
          />
          <Button onClick={addColumn} disabled={saving || !newCol.trim()}>
            ➕ Ajouter
          </Button>
        </div>
      )}

      {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
      {saving && <p className="text-sm text-[var(--muted)]">Enregistrement…</p>}

      <PersonalColumnSets onApply={isAdmin ? persist : undefined} />
      {!isAdmin && (
        <p className="text-xs text-[var(--muted)]">
          Appliquer un jeu personnel modifie les colonnes maîtres de cet environnement --
          réservé aux administrateurs. Tu peux quand même créer/gérer tes jeux personnels
          ci-dessus, l'application se fera depuis un compte admin.
        </p>
      )}
    </div>
  )
}
