import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  deleteSavedView,
  listSavedViews,
  saveSavedView,
  type ColFilter,
  type ColFilters,
  type SavedView,
} from '@/lib/api'

// Vues enregistrées : sauvegarder/rappeler une combinaison recherche +
// filtres par colonne + colonnes affichées, sous un nom -- mirroir de
// views/tab_database.py:_render_saved_views. Liées au compte (chaque
// utilisateur garde ses propres vues), pas à l'environnement seul.
export function SavedViews({
  orgId,
  search,
  colFilters,
  visibleCols,
  onApply,
}: {
  orgId: string
  search: string
  colFilters: ColFilters
  visibleCols: string[]
  onApply: (view: { search: string; colFilters: ColFilters; visibleCols: string[] }) => void
}) {
  const [open, setOpen] = useState(false)
  const [views, setViews] = useState<SavedView[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    listSavedViews(orgId)
      .then((data) => {
        if (!cancelled) setViews(data)
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
  }, [orgId, open])

  async function handleSave() {
    const name = newName.trim()
    if (!name) {
      setSaveError('Donne un nom à cette vue.')
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const view = await saveSavedView(orgId, { name, search, colFilters, visibleCols })
      setViews((prev) => {
        const others = (prev ?? []).filter((v) => v.name !== view.name)
        return [...others, view].sort((a, b) => a.name.localeCompare(b.name))
      })
      setNewName('')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(view: SavedView) {
    if (!window.confirm(`Supprimer la vue « ${view.name} » ? Cette action est irréversible.`)) {
      return
    }
    setDeletingId(view.id)
    setActionError(null)
    try {
      await deleteSavedView(orgId, view.id)
      setViews((prev) => (prev ?? []).filter((v) => v.id !== view.id))
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeletingId(null)
    }
  }

  function handleApply(view: SavedView) {
    // Compat vues enregistrées avant l'ajout des opérateurs (valeur =
    // simple chaîne, pas encore {op, value}) -- même compatibilité que
    // views/tab_database.py:_render_client_list.
    const normalized: ColFilters = {}
    for (const [col, f] of Object.entries(view.col_filters || {})) {
      if (typeof f === 'string') {
        normalized[col] = { op: 'contient', value: f }
      } else {
        normalized[col] = f as ColFilter
      }
    }
    onApply({
      search: view.search || '',
      colFilters: normalized,
      visibleCols: view.visible_cols || [],
    })
  }

  return (
    <div className="mb-4 rounded-lg border border-[var(--border)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium"
      >
        <span>👁️ Vues enregistrées</span>
        <span className="text-[var(--muted)]">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-[var(--border)] p-3">
          {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
          {error && !loading && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}

          {!loading && !error && views && views.length === 0 && (
            <p className="text-sm text-[var(--muted)]">Aucune vue enregistrée pour l'instant.</p>
          )}

          {!loading && !error && views && views.length > 0 && (
            <ul className="mb-3 flex flex-col gap-2">
              {views.map((v) => (
                <li key={v.id} className="flex items-center gap-2">
                  <span className="flex-1 truncate text-sm" title={v.name}>
                    {v.name}
                  </span>
                  <Button variant="secondary" onClick={() => handleApply(v)}>
                    Appliquer
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => void handleDelete(v)}
                    disabled={deletingId === v.id}
                  >
                    {deletingId === v.id ? 'Suppression…' : 'Supprimer'}
                  </Button>
                </li>
              ))}
            </ul>
          )}

          {actionError && <p className="mb-2 text-sm text-[var(--danger)]">Erreur : {actionError}</p>}

          <div className="border-t border-[var(--border)] pt-3">
            <p className="mb-2 text-xs text-[var(--muted)]">
              Enregistre la recherche, les filtres par colonne et les colonnes affichées actuels.
            </p>
            <div className="flex items-center gap-2">
              <Input
                placeholder="Nom de la vue"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void handleSave()
                }}
                className="max-w-xs"
              />
              <Button onClick={() => void handleSave()} disabled={saving || !newName.trim()}>
                {saving ? 'Enregistrement…' : '💾 Enregistrer la vue actuelle'}
              </Button>
            </div>
            {saveError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
