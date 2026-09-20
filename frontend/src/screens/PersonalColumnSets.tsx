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

// Jeux de colonnes maîtres personnels, liés au COMPTE -- mirroir de
// views/tab1_colonnes_maitres.py (`_render_account_memory`). Distinct des
// colonnes maîtres de l'environnement gérées juste au-dessus
// (MasterColumnsPanel) : ceci n'est jamais scopé à un org_id, retrouvable
// depuis n'importe quel environnement. Le dernier jeu appliqué est
// auto-chargé une fois au montage (comme `active_master_column_set_id`
// côté profil), pour ne pas avoir à le resélectionner à chaque connexion.
export function PersonalColumnSets({
  onApply,
}: {
  // Appelé avec les colonnes du jeu appliqué, pour les écrire dans les
  // colonnes maîtres RÉELLES de l'environnement (comme l'original
  // Streamlit : "Appliquer" écrivait tout de suite dans
  // st.session_state.master_columns + save_master_columns). Omis si
  // l'utilisateur n'est pas admin de l'environnement -- il peut quand
  // même gérer ses jeux personnels, juste pas les appliquer ici.
  onApply?: (columns: string[]) => Promise<void> | void
}) {
  const [sets, setSets] = useState<UserColumnSet[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selectedId, setSelectedId] = useState<string>('')
  const [workingColumns, setWorkingColumns] = useState<string[]>([])
  const [autoLoadedLabel, setAutoLoadedLabel] = useState<string | null>(null)

  const [applying, setApplying] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const [newCol, setNewCol] = useState('')
  const [newSetName, setNewSetName] = useState('')
  const [saving, setSaving] = useState(false)

  // Chargement des jeux + auto-application du dernier jeu actif (une
  // seule fois, au montage -- pas à chaque re-render).
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
          setWorkingColumns(active.columns)
          setAutoLoadedLabel(active.name)
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
  }, [])

  async function handleApply(id: string) {
    setApplying(true)
    setActionError(null)
    try {
      const applied = await applyMyColumnSet(id)
      setSelectedId(applied.id)
      setWorkingColumns(applied.columns)
      setAutoLoadedLabel(null)
      // Comme l'original : appliquer un jeu l'écrit tout de suite dans les
      // colonnes maîtres réelles de l'environnement, pas seulement dans la
      // mémoire personnelle -- sinon "Appliquer" ne fait visiblement rien.
      if (onApply) await onApply(applied.columns)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setApplying(false)
    }
  }

  async function handleDelete(id: string) {
    const target = sets?.find((s) => s.id === id)
    if (!target) return
    if (!window.confirm(`Supprimer le jeu de colonnes « ${target.name} » ? Cette action est irréversible.`)) {
      return
    }
    setDeleting(true)
    setActionError(null)
    try {
      await deleteMyColumnSet(id)
      setSets((prev) => (prev ? prev.filter((s) => s.id !== id) : prev))
      if (selectedId === id) {
        setSelectedId('')
        setWorkingColumns([])
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeleting(false)
    }
  }

  function moveUp(i: number) {
    if (i === 0) return
    const next = [...workingColumns]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    setWorkingColumns(next)
  }

  function moveDown(i: number) {
    if (i === workingColumns.length - 1) return
    const next = [...workingColumns]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    setWorkingColumns(next)
  }

  function removeAt(i: number) {
    setWorkingColumns((prev) => prev.filter((_, idx) => idx !== i))
  }

  function addColumn() {
    const name = newCol.trim()
    if (!name) return
    if (workingColumns.some((c) => c.toLowerCase() === name.toLowerCase())) {
      setActionError('Cette colonne est déjà dans la liste.')
      return
    }
    setWorkingColumns((prev) => [...prev, name])
    setNewCol('')
  }

  async function handleSaveAs() {
    const name = newSetName.trim()
    if (!name) {
      setActionError('Donne un nom à ce jeu de colonnes.')
      return
    }
    if (workingColumns.length === 0) {
      setActionError('Aucune colonne à enregistrer.')
      return
    }
    setSaving(true)
    setActionError(null)
    try {
      const saved = await saveMyColumnSet(name, workingColumns)
      setSets((prev) => {
        if (!prev) return [saved]
        const idx = prev.findIndex((s) => s.id === saved.id || s.name.toLowerCase() === saved.name.toLowerCase())
        if (idx === -1) return [...prev, saved]
        const next = [...prev]
        next[idx] = saved
        return next
      })
      setSelectedId(saved.id)
      setAutoLoadedLabel(null)
      setNewSetName('')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4 border-t border-[var(--border)] pt-4">
      <div>
        <h2 className="text-base font-semibold">Jeux de colonnes personnels (liés à ton compte)</h2>
        <p className="text-sm text-[var(--muted)]">
          Un « jeu » est une liste de colonnes que tu enregistres une fois sous un nom, pour la
          réutiliser dans n'importe quel environnement -- pratique si tu bascules souvent entre
          "Prélèvement" et "Énergie" par exemple, plutôt que de retaper les colonnes à chaque fois.
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-[var(--muted)]">
          <li>
            <strong>Enregistrer un jeu</strong> : ajuste les colonnes ci-dessous, donne-leur un nom
            et clique « 💾 Enregistrer ». Le jeu est sauvegardé sur ton compte, indépendamment de
            l'environnement actuel.
          </li>
          <li>
            <strong>Appliquer un jeu</strong> : choisis-le dans la liste et clique
            « ✅ Appliquer ce jeu ». Ça écrit immédiatement ces colonnes comme colonnes maîtres de
            l'environnement où tu es actuellement (ci-dessus) -- exactement comme si tu les avais
            retapées à la main.
          </li>
        </ol>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Le dernier jeu appliqué se recharge automatiquement à ta prochaine connexion (mais
          n'écrase pas les colonnes maîtres tout seul -- il faut cliquer « Appliquer »).
        </p>
      </div>

      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && !loading && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && !error && (
        <>
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
                    {s.name} ({s.columns.length} colonnes)
                  </option>
                ))}
              </select>
              <Button
                variant="secondary"
                disabled={!selectedId || applying}
                onClick={() => void handleApply(selectedId)}
              >
                {applying ? 'Application…' : '✅ Appliquer ce jeu'}
              </Button>
              <Button
                variant="danger"
                disabled={!selectedId || deleting}
                onClick={() => selectedId && void handleDelete(selectedId)}
              >
                {deleting ? 'Suppression…' : '🗑️ Supprimer ce jeu'}
              </Button>
            </div>
          )}

          <div>
            <h3 className="mb-2 text-sm font-medium">Colonnes du jeu en cours d'édition</h3>
            {workingColumns.length === 0 && (
              <p className="text-sm text-[var(--muted)]">
                Aucune colonne pour l'instant -- ajoute-en ci-dessous ou applique un jeu existant.
              </p>
            )}
            {workingColumns.length > 0 && (
              <ul className="flex flex-col gap-2">
                {workingColumns.map((col, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="text-sm">{col}</span>
                    <Button variant="secondary" onClick={() => moveUp(i)} disabled={i === 0}>
                      ⬆️
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => moveDown(i)}
                      disabled={i === workingColumns.length - 1}
                    >
                      ⬇️
                    </Button>
                    <Button variant="danger" onClick={() => removeAt(i)}>
                      🗑️
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-2 flex items-center gap-2">
              <Input
                placeholder="Nouvelle colonne"
                value={newCol}
                onChange={(e) => setNewCol(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') addColumn()
                }}
                className="max-w-xs"
              />
              <Button onClick={addColumn} disabled={!newCol.trim()}>
                ➕ Ajouter
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="Nom du nouveau jeu (ex : Prélèvement mensuel)"
              value={newSetName}
              onChange={(e) => setNewSetName(e.target.value)}
              className="max-w-xs"
            />
            <Button onClick={() => void handleSaveAs()} disabled={saving}>
              {saving ? 'Enregistrement…' : '💾 Enregistrer les colonnes actuelles sous ce nom'}
            </Button>
          </div>

          {actionError && <p className="text-sm text-[var(--danger)]">Erreur : {actionError}</p>}
        </>
      )}
    </div>
  )
}
