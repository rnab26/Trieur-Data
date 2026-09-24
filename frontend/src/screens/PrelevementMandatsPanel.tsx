import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  bulkDeletePrelevementMandats,
  bulkUpdatePrelevementMandats,
  exportPrelevementMandats,
  listPrelevementMandats,
  type ColFilters,
  type RecordRow,
} from '@/lib/api'
import { ColumnFilters } from './ColumnFilters'
import { MandatEditDialog } from './MandatEditDialog'

const PAGE_SIZE = 50

function toApiColFilters(filters: ColFilters): ColFilters {
  const out: ColFilters = {}
  for (const [col, f] of Object.entries(filters)) {
    out[col] = { op: f.op, value: f.value.toLowerCase() }
  }
  return out
}

// Vue de consultation des mandats déjà enregistrés en base (bouton
// "Enregistrer dans la base de données" de l'onglet Générer) -- demandée
// par Raphaël (2026-09-22) : mêmes commandes que la Base de données
// générique (recherche, filtres par colonne, édition, modification/
// suppression en masse, export), mais sur les colonnes fixes de
// trieur_data.prelevement_mandats plutôt que sur des colonnes maîtres
// configurables.
export function PrelevementMandatsPanel({ orgId }: { orgId: string }) {
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [colFilters, setColFilters] = useState<ColFilters>({})

  const [rows, setRows] = useState<RecordRow[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [editingRow, setEditingRow] = useState<RecordRow | null>(null)

  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [editField, setEditField] = useState('')
  const [editValue, setEditValue] = useState('')
  const [confirmingEdit, setConfirmingEdit] = useState(false)
  const [bulkEditing, setBulkEditing] = useState(false)
  const [bulkEditError, setBulkEditError] = useState<string | null>(null)

  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const colFiltersKey = JSON.stringify(colFilters)
  const requestIdRef = useRef(0)

  const fetchPage = useCallback(
    async (targetPage: number, targetSearch: string, targetColFilters: ColFilters, append: boolean) => {
      const requestId = ++requestIdRef.current
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const data = await listPrelevementMandats(orgId, {
          page: targetPage,
          pageSize: PAGE_SIZE,
          search: targetSearch,
          colFilters: toApiColFilters(targetColFilters),
        })
        if (requestId !== requestIdRef.current) return
        setRows((prev) => (append ? [...prev, ...data.rows] : data.rows))
        setColumns(data.columns)
        setTotal(data.total)
        setPage(data.page)
        if (!append) setSelectedIds([])
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    },
    [orgId],
  )

  useEffect(() => {
    void fetchPage(1, search, colFilters, false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, colFiltersKey, fetchPage])

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSearch(searchInput.trim())
  }

  function handleLoadMore() {
    void fetchPage(page + 1, search, colFilters, true)
  }

  function refresh() {
    void fetchPage(1, search, colFilters, false)
  }

  function toggleRowSelection(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  function toggleSelectAll() {
    setSelectedIds((prev) => (prev.length === rows.length ? [] : rows.map((r) => String(r._id))))
  }

  async function handleConfirmDelete() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await bulkDeletePrelevementMandats(orgId, selectedIds)
      setConfirmingDelete(false)
      setSelectedIds([])
      refresh()
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleConfirmBulkEdit() {
    if (!editField) return
    setBulkEditing(true)
    setBulkEditError(null)
    const value = editValue.trim() === '' ? '' : editValue
    try {
      await bulkUpdatePrelevementMandats(orgId, selectedIds, editField, value)
      setConfirmingEdit(false)
      setEditOpen(false)
      setEditValue('')
      setSelectedIds([])
      refresh()
    } catch (err) {
      setBulkEditError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBulkEditing(false)
    }
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    setExporting(format)
    setExportError(null)
    try {
      await exportPrelevementMandats(orgId, { format, search, colFilters })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setExporting(null)
    }
  }

  const hasMore = rows.length < total
  const editableColumns = columns.filter((c) => c !== 'Enregistré le')

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Mandats enregistrés</h2>
        <p className="text-sm text-[var(--muted)]">
          Tous les mandats déjà enregistrés dans la base de données pour cet environnement, tous lots
          confondus. Modifiables, filtrables et exportables comme dans la Base de données.
        </p>
      </div>

      <form onSubmit={handleSearchSubmit} className="flex flex-1 min-w-[200px] gap-2">
        <Input
          placeholder="Rechercher un mandat (nom, RUM, IBAN…)"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <Button type="submit" variant="secondary">
          Rechercher
        </Button>
      </form>

      <ColumnFilters columns={columns} filters={colFilters} onChange={setColFilters} />

      {total > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">💾 Exporter ces résultats</span>
          <Button variant="secondary" disabled={exporting !== null} onClick={() => void handleExport('csv')}>
            {exporting === 'csv' ? 'Préparation…' : 'Exporter CSV'}
          </Button>
          <Button variant="secondary" disabled={exporting !== null} onClick={() => void handleExport('xlsx')}>
            {exporting === 'xlsx' ? 'Préparation…' : 'Exporter Excel'}
          </Button>
          <span className="text-xs text-[var(--muted)]">
            Exporte tout l'historique ({total}), avec la recherche/les filtres actuels.
          </span>
        </div>
      )}
      {exportError && <p className="text-sm text-[var(--danger)]">Erreur d'export : {exportError}</p>}

      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && !loading && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && !error && rows.length === 0 && (
        <p className="text-sm text-[var(--muted)]">
          {search || Object.keys(colFilters).length > 0
            ? 'Aucun résultat pour cette recherche/ces filtres.'
            : 'Aucun mandat enregistré pour l\'instant dans cet environnement.'}
        </p>
      )}

      {!loading && !error && selectedIds.length > 0 && (
        <div className="rounded-lg shadow-[var(--ring-card)] bg-[var(--card)] p-3">
          <p className="mb-2 text-sm font-medium">{selectedIds.length} ligne(s) sélectionnée(s).</p>
          <div className="flex flex-wrap items-center gap-2">
            {!confirmingDelete ? (
              <Button variant="danger" onClick={() => setConfirmingDelete(true)}>
                🗑️ Supprimer la sélection ({selectedIds.length})
              </Button>
            ) : (
              <div className="flex flex-1 flex-col gap-2 rounded-md shadow-[inset_0_0_0_1px_var(--danger)] p-2">
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
            <Button variant="secondary" onClick={() => setEditOpen((v) => !v)}>
              ✏️ Modifier un champ
            </Button>
          </div>

          {editOpen && (
            <div className="mt-3 rounded-md shadow-[var(--ring-card)] p-3">
              <p className="mb-2 text-sm text-[var(--muted)]">
                Modifier un champ pour les {selectedIds.length} ligne(s) sélectionnée(s).
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="rounded-md shadow-[var(--ring-card)] bg-[var(--card)] px-2 py-2 text-sm"
                  value={editField || editableColumns[0] || ''}
                  onChange={(e) => setEditField(e.target.value)}
                >
                  {editableColumns.map((col) => (
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
                {!confirmingEdit && (
                  <Button onClick={() => setConfirmingEdit(true)}>
                    Appliquer à {selectedIds.length} ligne(s)
                  </Button>
                )}
              </div>
              {confirmingEdit && (
                <div className="mt-2 flex flex-col gap-2 rounded-md shadow-[inset_0_0_0_1px_var(--danger)] p-2">
                  <p className="text-sm text-[var(--danger)]">
                    Remplace « {editField || editableColumns[0]} » pour {selectedIds.length} mandat(s), sans
                    annulation possible après coup.
                  </p>
                  {bulkEditError && <p className="text-sm text-[var(--danger)]">Erreur : {bulkEditError}</p>}
                  <div className="flex gap-2">
                    <Button disabled={bulkEditing} onClick={() => void handleConfirmBulkEdit()}>
                      {bulkEditing ? 'Application…' : '✅ Confirmer'}
                    </Button>
                    <Button
                      variant="secondary"
                      disabled={bulkEditing}
                      onClick={() => {
                        setConfirmingEdit(false)
                        setBulkEditError(null)
                      }}
                    >
                      Annuler
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg shadow-[var(--ring-card)]">
          <table className="w-full min-w-max text-sm">
            <thead>
              <tr className="bg-[var(--muted-bg)] text-left">
                <th className="px-3 py-2">
                  <label className="flex h-9 w-9 cursor-pointer items-center justify-center">
                    <input
                      type="checkbox"
                      aria-label="Tout sélectionner"
                      className="h-5 w-5"
                      checked={selectedIds.length === rows.length}
                      onChange={toggleSelectAll}
                    />
                  </label>
                </th>
                {columns.map((col) => (
                  <th key={col} className="whitespace-nowrap px-3 py-2 font-medium">
                    {col}
                  </th>
                ))}
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row._id)} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2">
                    <label className="flex h-9 w-9 cursor-pointer items-center justify-center">
                      <input
                        type="checkbox"
                        aria-label={`Sélectionner la ligne ${String(row._id)}`}
                        className="h-5 w-5"
                        checked={selectedIds.includes(String(row._id))}
                        onChange={() => toggleRowSelection(String(row._id))}
                      />
                    </label>
                  </td>
                  {columns.map((col) => (
                    <td key={col} className="whitespace-nowrap px-3 py-2">
                      {row[col] == null ? '' : String(row[col])}
                    </td>
                  ))}
                  <td className="px-3 py-2">
                    <Button variant="secondary" onClick={() => setEditingRow(row)}>
                      Modifier
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!loading && !error && hasMore && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={handleLoadMore} disabled={loadingMore}>
            {loadingMore ? 'Chargement…' : `Charger plus (${rows.length}/${total})`}
          </Button>
        </div>
      )}

      {editingRow && (
        <MandatEditDialog
          orgId={orgId}
          mandat={editingRow}
          columns={editableColumns}
          onClose={() => setEditingRow(null)}
          onSaved={() => {
            setEditingRow(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}
