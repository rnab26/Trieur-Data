import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, bulkDeleteRecords, bulkUpdateRecords } from '@/lib/api'

// Barre d'actions groupées sur la sélection multiple du tableau -- mirroir
// de views/tab_database.py:_render_client_list (bloc "selected_ids") :
// suppression à deux étapes (voir views/_ui.py:confirm_delete_button --
// un clic isolé n'affiche que l'avertissement, un second clic explicite
// confirme, "Annuler" disponible) et modification d'UN SEUL champ pour
// toute la sélection.
export function BulkActions({
  orgId,
  selectedIds,
  masterColumns,
  onDone,
  onClearSelection,
}: {
  orgId: string
  selectedIds: string[]
  masterColumns: string[]
  onDone: () => void
  onClearSelection: () => void
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteResult, setDeleteResult] = useState<string | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [editField, setEditField] = useState<string>(masterColumns[0] ?? '')
  const [editValue, setEditValue] = useState('')
  const [confirmingEdit, setConfirmingEdit] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [editResult, setEditResult] = useState<string | null>(null)

  async function handleConfirmDelete() {
    setDeleting(true)
    setDeleteError(null)
    setDeleteResult(null)
    try {
      const res = await bulkDeleteRecords(orgId, selectedIds)
      setDeleteResult(`${res.n_deleted} client(s) supprimé(s).`)
      setConfirmingDelete(false)
      onClearSelection()
      onDone()
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleConfirmEdit() {
    if (!editField) return
    setEditing(true)
    setEditError(null)
    setEditResult(null)
    // Une chaîne vide efface le champ (comme
    // views/tab_database.py:_render_bulk_edit_form) -- toute autre valeur,
    // y compris "0" ou "false", est envoyée telle quelle : jamais
    // convertie en None avant l'API (voir bulkUpdateRecords).
    const value = editValue.trim() === '' ? '' : editValue
    try {
      const res = await bulkUpdateRecords(orgId, selectedIds, editField, value)
      setEditResult(`${res.n_updated}/${res.n_requested} client(s) modifié(s).`)
      setConfirmingEdit(false)
      setEditOpen(false)
      setEditValue('')
      onClearSelection()
      onDone()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setEditing(false)
    }
  }

  if (selectedIds.length === 0) return null

  return (
    <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <p className="mb-2 text-sm font-medium">
        {selectedIds.length} ligne(s) sélectionnée(s).
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {!confirmingDelete ? (
          <Button variant="danger" onClick={() => setConfirmingDelete(true)}>
            🗑️ Supprimer la sélection ({selectedIds.length})
          </Button>
        ) : (
          <div className="flex flex-1 flex-col gap-2 rounded-md border border-[var(--danger)] p-2">
            <p className="text-sm text-[var(--danger)]">
              Suppression définitive, impossible à annuler après coup.
            </p>
            {deleteError && <p className="text-sm text-[var(--danger)]">Erreur : {deleteError}</p>}
            <div className="flex gap-2">
              <Button variant="danger" disabled={deleting} onClick={() => void handleConfirmDelete()}>
                {deleting ? 'Suppression…' : '✅ Oui, supprimer'}
              </Button>
              <Button
                variant="secondary"
                disabled={deleting}
                onClick={() => {
                  setConfirmingDelete(false)
                  setDeleteError(null)
                }}
              >
                Annuler
              </Button>
            </div>
          </div>
        )}

        {masterColumns.length > 0 && (
          <Button variant="secondary" onClick={() => setEditOpen((v) => !v)}>
            ✏️ Modifier un champ
          </Button>
        )}
      </div>

      {deleteResult && <p className="mt-2 text-sm text-[var(--success,#16a34a)]">{deleteResult}</p>}

      {editOpen && (
        <div className="mt-3 rounded-md border border-[var(--border)] p-3">
          <p className="mb-2 text-sm text-[var(--muted)]">
            Modifier un champ pour les {selectedIds.length} ligne(s) sélectionnée(s).
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
              value={editField}
              onChange={(e) => setEditField(e.target.value)}
            >
              {masterColumns.map((col) => (
                <option key={col} value={col}>
                  {col}
                </option>
              ))}
            </select>
            <Input
              placeholder="Nouvelle valeur (laisser vide pour effacer le champ)"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="max-w-xs"
            />
            {!confirmingEdit ? (
              <Button onClick={() => setConfirmingEdit(true)} disabled={!editField}>
                Appliquer à {selectedIds.length} ligne(s)
              </Button>
            ) : null}
          </div>

          {confirmingEdit && (
            <div className="mt-2 flex flex-col gap-2 rounded-md border border-[var(--danger)] p-2">
              <p className="text-sm text-[var(--danger)]">
                Remplace « {editField} » pour {selectedIds.length} client(s), sans annulation possible
                après coup.
              </p>
              {editError && <p className="text-sm text-[var(--danger)]">Erreur : {editError}</p>}
              <div className="flex gap-2">
                <Button disabled={editing} onClick={() => void handleConfirmEdit()}>
                  {editing ? 'Application…' : '✅ Confirmer'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={editing}
                  onClick={() => {
                    setConfirmingEdit(false)
                    setEditError(null)
                  }}
                >
                  Annuler
                </Button>
              </div>
            </div>
          )}

          {editResult && <p className="mt-2 text-sm text-[var(--success,#16a34a)]">{editResult}</p>}
        </div>
      )}
    </div>
  )
}
