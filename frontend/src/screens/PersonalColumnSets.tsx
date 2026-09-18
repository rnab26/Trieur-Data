import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  applyMyColumnSet,
  deleteMyColumnSet,
  getMe,
  listMyColumnSets,
  saveMyColumnSet,
  type UserColumnSet,
} from '@/lib/api'

// Copie conforme de views/tab1_colonnes_maitres.py:_render_account_memory
// ("🔗 Mémoire liée à ton compte") : un sélecteur de jeux enregistrés +
// Appliquer/Supprimer, et un nom + "Enregistrer les colonnes actuelles
// sous ce nom" -- les colonnes viennent du textarea principal
// (MasterColumnsPanel) au-dessus, jamais d'un éditeur séparé ici. Ce
// n'était PAS un deuxième "Colonnes maîtres" avec ses propres flèches
// haut/bas/ajout/suppression par colonne (version précédente,
// source de confusion réelle constatée par l'utilisateur).
export function PersonalColumnSets({
  currentColumns,
  onApplied,
}: {
  // Colonnes maîtres ACTUELLEMENT enregistrées pour l'environnement
  // (celles du textarea principal, déjà sauvegardées) -- ce que
  // "Enregistrer sous ce nom" capture, comme st.session_state.master_columns.
  currentColumns: string[]
  // Appelé après "Appliquer ce jeu" avec les colonnes du jeu choisi --
  // au parent (MasterColumnsPanel) de les appliquer à l'environnement,
  // une seule notion de colonnes maîtres, jamais dupliquée ici.
  onApplied: (columns: string[]) => void
}) {
  const [sets, setSets] = useState<UserColumnSet[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedId, setSelectedId] = useState('')
  const [autoLoadedLabel, setAutoLoadedLabel] = useState<string | null>(null)

  const [applying, setApplying] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const [newSetName, setNewSetName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([listMyColumnSets(), getMe()])
      .then(([setsData, meData]) => {
        if (cancelled) return
        setSets(setsData.sets)
        const activeId = meData.profile.active_master_column_set_id
        const active = activeId ? setsData.sets.find((s) => s.id === activeId) : undefined
        if (active) {
          setSelectedId(active.id)
          setAutoLoadedLabel(active.name)
          onApplied(active.columns)
        } else if (setsData.sets.length > 0) {
          setSelectedId(setsData.sets[0].id)
        }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleApply() {
    if (!selectedId) return
    setApplying(true)
    setActionError(null)
    try {
      const applied = await applyMyColumnSet(selectedId)
      onApplied(applied.columns)
      setAutoLoadedLabel(null)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setApplying(false)
    }
  }

  async function handleDelete() {
    if (!selectedId) return
    const target = sets?.find((s) => s.id === selectedId)
    if (!target) return
    if (!window.confirm(`Supprimer le jeu « ${target.name} » ? Cette action est irréversible.`)) {
      return
    }
    setDeleting(true)
    setActionError(null)
    try {
      await deleteMyColumnSet(selectedId)
      setSets((prev) => (prev ? prev.filter((s) => s.id !== selectedId) : prev))
      setSelectedId('')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleSave() {
    const name = newSetName.trim()
    const cols = currentColumns.filter((c) => c)
    if (!name) {
      setActionError('Donne un nom à ce jeu de colonnes.')
      return
    }
    if (cols.length === 0) {
      setActionError('Aucune colonne à enregistrer.')
      return
    }
    setSaving(true)
    setActionError(null)
    try {
      const savedSet = await saveMyColumnSet(name, cols)
      setSets((prev) => {
        if (!prev) return [savedSet]
        const idx = prev.findIndex((s) => s.id === savedSet.id || s.name.toLowerCase() === name.toLowerCase())
        if (idx === -1) return [...prev, savedSet]
        const next = [...prev]
        next[idx] = savedSet
        return next
      })
      setSelectedId(savedSet.id)
      setAutoLoadedLabel(null)
      setNewSetName('')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <details className="rounded-md border border-[var(--border)] p-3" open>
      <summary className="cursor-pointer text-sm font-medium">🔗 Mémoire liée à ton compte</summary>

      {loading && <p className="mt-2 text-sm text-[var(--muted)]">Chargement…</p>}
      {error && !loading && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && !error && (
        <div className="mt-3 flex flex-col gap-3">
          {autoLoadedLabel && (
            <p className="text-sm text-[var(--success,#16a34a)]">
              Jeu « {autoLoadedLabel} » rechargé automatiquement (dernier jeu actif).
            </p>
          )}

          {sets && sets.length === 0 && (
            <p className="text-sm text-[var(--muted)]">
              Aucun jeu de colonnes enregistré sur ton compte pour l'instant.
            </p>
          )}

          {sets && sets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
                className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)]"
              >
                {sets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <Button variant="secondary" disabled={!selectedId || applying} onClick={() => void handleApply()}>
                {applying ? 'Application…' : '✅ Appliquer ce jeu'}
              </Button>
              <Button variant="danger" disabled={!selectedId || deleting} onClick={() => void handleDelete()}>
                {deleting ? 'Suppression…' : '🗑️ Supprimer ce jeu'}
              </Button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="Nom du nouveau jeu"
              value={newSetName}
              onChange={(e) => setNewSetName(e.target.value)}
              className="max-w-xs"
            />
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? 'Enregistrement…' : '💾 Enregistrer les colonnes actuelles sous ce nom'}
            </Button>
          </div>

          {actionError && <p className="text-sm text-[var(--danger)]">Erreur : {actionError}</p>}
        </div>
      )}
    </details>
  )
}
