import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useIsAdmin, useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  exportRecords,
  getMasterColumns,
  listRecords,
  type ColFilters,
  type RecordRow,
} from '@/lib/api'
import { RecordEditDialog } from './RecordEditDialog'
import { ImportPanel } from './ImportPanel'
import { MasterColumnsPanel } from './MasterColumnsPanel'
import { ColumnFilters } from './ColumnFilters'
import { SavedViews } from './SavedViews'
import { DashboardPanel } from './DashboardPanel'
import { DedupAlertsPanel } from './DedupAlertsPanel'
import { BulkActions } from './BulkActions'

const PAGE_SIZE = 50

// Les filtres par colonne sont déjà normalisés (opérateur + valeur non
// vide, ou "vide"/"non vide") par ColumnFilters -- on ne fait ici que
// mettre la valeur en minuscules avant de l'envoyer à l'API, comme le
// fait views/tab_database.py:_render_client_list avant de construire
// `col_filters` (la comparaison côté serveur, _matches_filter, ne
// re-normalise pas la casse de son côté).
function toApiColFilters(filters: ColFilters): ColFilters {
  const out: ColFilters = {}
  for (const [col, f] of Object.entries(filters)) {
    out[col] = { op: f.op, value: f.value.toLowerCase() }
  }
  return out
}

type Tab = 'clients' | 'import' | 'columns'

export function DatabaseScreen() {
  const { session, signOut } = useAuth()

  const { orgs, orgsError, orgId, setOrgId } = useOrgs()
  const { isAdmin } = useIsAdmin()

  const [tab, setTab] = useState<Tab>('clients')

  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [colFilters, setColFilters] = useState<ColFilters>({})
  const [visibleCols, setVisibleCols] = useState<string[] | null>(null)

  const [rows, setRows] = useState<RecordRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Incrémenté après tout import/modification/suppression qui change
  // l'état résumé par le tableau de bord (nombre de clients, dernier
  // import) -- pousse DashboardPanel à recharger sans dépendre du même
  // fetch que la liste (le tableau de bord doit rester juste même si la
  // recherche/les filtres ne renvoient aucune ligne).
  const [dashboardKey, setDashboardKey] = useState(0)

  const [editingId, setEditingId] = useState<string | null>(null)

  // Sélection multiple (bulk delete/bulk edit) -- réinitialisée à chaque
  // changement de lot chargé (nouvel environnement, nouvelle recherche,
  // nouveaux filtres, page suivante) : une position sélectionnée avant
  // n'a plus le même sens dans un lot différent.
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  const [masterColumns, setMasterColumnsState] = useState<string[]>([])
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Colonnes maîtres de l'environnement -- utilisées pour restreindre le
  // champ proposé en modification en masse (BulkActions) aux vraies clés
  // déclarées, même limite que views/tab_database.py:_render_bulk_edit_form.
  useEffect(() => {
    if (!orgId) return
    let cancelled = false
    getMasterColumns(orgId)
      .then((data) => {
        if (!cancelled) setMasterColumnsState(data.columns)
      })
      .catch(() => {
        // Pas bloquant : sans colonnes maîtres connues, "Modifier un
        // champ" reste simplement masqué (voir BulkActions).
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  const columns = useMemo(() => {
    const cols: string[] = []
    for (const row of rows) {
      for (const key of Object.keys(row)) {
        if (key !== '_id' && !cols.includes(key)) cols.push(key)
      }
    }
    return cols
  }, [rows])

  // Colonnes affichées : toutes par défaut, personnalisable (voir plus
  // bas), rappelable via une vue enregistrée -- même principe que
  // views/tab_database.py:_render_client_list (multiselect "Colonnes
  // affichées"). `null` veut dire "pas encore personnalisé" -> toutes.
  // Sanitize une sélection périmée (colonne qui n'existe plus dans le
  // lot chargé) sans jamais planter l'affichage.
  useEffect(() => {
    setVisibleCols((prev) => {
      if (prev === null) return prev
      const next = prev.filter((c) => columns.includes(c))
      return next.length === prev.length ? prev : next
    })
  }, [columns])
  const effectiveVisibleCols = visibleCols === null ? columns : visibleCols

  const colFiltersKey = useMemo(() => JSON.stringify(colFilters), [colFilters])

  const fetchPage = useCallback(
    async (
      targetOrgId: string,
      targetPage: number,
      targetSearch: string,
      targetColFilters: ColFilters,
      append: boolean,
    ) => {
      if (append) setLoadingMore(true)
      else setLoading(true)
      setError(null)
      try {
        const data = await listRecords(targetOrgId, {
          page: targetPage,
          pageSize: PAGE_SIZE,
          search: targetSearch,
          colFilters: toApiColFilters(targetColFilters),
        })
        setRows((prev) => (append ? [...prev, ...data.rows] : data.rows))
        setTotal(data.total)
        setPage(data.page)
        // Le lot chargé change (nouvelle page, nouvelle recherche...) :
        // une sélection sur d'anciennes positions n'a plus de sens --
        // même règle que côté Streamlit (clear_stale_widgets après une
        // mutation du lot affiché).
        if (!append) setSelectedIds([])
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [],
  )

  // Rechargement complet (nouvel environnement, nouvelle recherche ou
  // nouveaux filtres par colonne).
  useEffect(() => {
    if (!orgId) return
    void fetchPage(orgId, 1, search, colFilters, false)
    // colFiltersKey sert de dépendance stable (colFilters change de
    // référence à chaque frappe côté ColumnFilters) -- colFilters
    // lui-même reste utilisé dans le corps de l'effet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, search, colFiltersKey, fetchPage])

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSearch(searchInput.trim())
  }

  function handleLoadMore() {
    if (!orgId) return
    void fetchPage(orgId, page + 1, search, colFilters, true)
  }

  function handleRecordSaved() {
    setEditingId(null)
    if (orgId) void fetchPage(orgId, 1, search, colFilters, false)
    setDashboardKey((k) => k + 1)
  }

  function handleApplySavedView(view: { search: string; colFilters: ColFilters; visibleCols: string[] }) {
    setSearchInput(view.search)
    setSearch(view.search)
    setColFilters(view.colFilters)
    setVisibleCols(view.visibleCols.length > 0 ? view.visibleCols : null)
  }

  function handleBulkActionDone() {
    if (!orgId) return
    void fetchPage(orgId, 1, search, colFilters, false)
    setDashboardKey((k) => k + 1)
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    if (!orgId) return
    setExporting(format)
    setExportError(null)
    try {
      await exportRecords(orgId, {
        format,
        search,
        colFilters,
        visibleCols: effectiveVisibleCols,
        knownCols: columns,
      })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setExporting(null)
    }
  }

  function toggleRowSelection(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  function toggleSelectAll() {
    setSelectedIds((prev) => (prev.length === rows.length ? [] : rows.map((r) => String(r._id))))
  }

  const hasMore = rows.length < total

  return (
    <div className="mx-auto max-w-6xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Base de données</h1>
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <span>{session?.user.email}</span>
          <Button variant="secondary" onClick={() => void signOut()}>
            Se déconnecter
          </Button>
        </div>
      </header>

      {orgsError && (
        <p className="mb-4 text-sm text-[var(--danger)]">
          Impossible de charger les environnements : {orgsError}
        </p>
      )}

      {orgs && orgs.length === 0 && !orgsError && (
        <p className="text-sm text-[var(--muted)]">
          Ton compte n'a accès à aucun environnement pour l'instant. Contacte l'administrateur.
        </p>
      )}

      {orgs && orgs.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label htmlFor="org-switcher" className="text-sm text-[var(--muted)]">
            Environnement
          </label>
          <select
            id="org-switcher"
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
            value={orgId ?? ''}
            onChange={(e) => setOrgId(e.target.value)}
          >
            {orgs.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>

          {tab === 'clients' && (
            <form onSubmit={handleSearchSubmit} className="flex flex-1 min-w-[200px] gap-2">
              <Input
                placeholder="Rechercher un client…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
              />
              <Button type="submit" variant="secondary">
                Rechercher
              </Button>
            </form>
          )}
        </div>
      )}

      {orgId && (
        <div className="mb-4 flex gap-2 border-b border-[var(--border)]">
          {([
            ['clients', 'Clients'],
            ['import', 'Importer'],
            ['columns', 'Colonnes maîtres'],
          ] as [Tab, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={
                'px-3 py-2 text-sm font-medium ' +
                (tab === key
                  ? 'border-b-2 border-[var(--primary)] text-[var(--foreground)]'
                  : 'text-[var(--muted)] hover:text-[var(--foreground)]')
              }
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {orgId && tab === 'import' && (
        <ImportPanel
          orgId={orgId}
          isAdmin={isAdmin}
          onImported={() => {
            void fetchPage(orgId, 1, search, colFilters, false)
            setDashboardKey((k) => k + 1)
          }}
        />
      )}

      {orgId && tab === 'columns' && <MasterColumnsPanel orgId={orgId} isAdmin={isAdmin} />}

      {orgId && tab === 'clients' && (
        <>
          <DashboardPanel orgId={orgId} refreshKey={dashboardKey} />

          <DedupAlertsPanel
            orgId={orgId}
            refreshKey={dashboardKey}
            onResolved={() => setDashboardKey((k) => k + 1)}
          />

          <ColumnFilters columns={columns} filters={colFilters} onChange={setColFilters} />

          <SavedViews
            orgId={orgId}
            search={search}
            colFilters={colFilters}
            visibleCols={effectiveVisibleCols}
            onApply={handleApplySavedView}
          />

          {columns.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--border)] p-3">
              <span className="text-sm font-medium">Colonnes affichées</span>
              {columns.map((col) => (
                <label key={col} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
                    checked={effectiveVisibleCols.includes(col)}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setVisibleCols((prev) => {
                        const base = prev === null ? columns : prev
                        const next = checked ? [...base, col] : base.filter((c) => c !== col)
                        // Aucune colonne sélectionnée : toutes affichées
                        // par défaut, comme côté Streamlit -- `null`
                        // retombe sur `columns` via effectiveVisibleCols.
                        return next.length === 0 ? null : next
                      })
                    }}
                  />
                  {col}
                </label>
              ))}
            </div>
          )}

          {total > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">💾 Exporter ces résultats</span>
              <Button
                variant="secondary"
                disabled={exporting !== null}
                onClick={() => void handleExport('csv')}
              >
                {exporting === 'csv' ? 'Préparation…' : 'Exporter CSV'}
              </Button>
              <Button
                variant="secondary"
                disabled={exporting !== null}
                onClick={() => void handleExport('xlsx')}
              >
                {exporting === 'xlsx' ? 'Préparation…' : 'Exporter Excel'}
              </Button>
              <span className="text-xs text-[var(--muted)]">
                Exporte tout l'environnement ({total}), avec la recherche/les filtres actuels.
              </span>
            </div>
          )}
          {exportError && (
            <p className="mb-4 text-sm text-[var(--danger)]">Erreur d'export : {exportError}</p>
          )}

          {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}

          {error && !loading && (
            <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>
          )}

          {!loading && !error && rows.length === 0 && (
            <p className="text-sm text-[var(--muted)]">
              {search || Object.keys(colFilters).length > 0
                ? 'Aucun résultat pour cette recherche/ces filtres.'
                : 'Aucun client importé pour l\'instant dans cet environnement.'}
            </p>
          )}

          {!loading && !error && rows.length > 0 && (
            <BulkActions
              orgId={orgId}
              selectedIds={selectedIds}
              masterColumns={masterColumns}
              onDone={handleBulkActionDone}
              onClearSelection={() => setSelectedIds([])}
            />
          )}

          {!loading && !error && rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
              <table className="w-full min-w-max text-sm">
                <thead>
                  <tr className="bg-[var(--muted-bg)] text-left">
                    <th className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label="Tout sélectionner"
                        checked={selectedIds.length === rows.length}
                        onChange={toggleSelectAll}
                      />
                    </th>
                    {effectiveVisibleCols.map((col) => (
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
                        <input
                          type="checkbox"
                          aria-label={`Sélectionner la ligne ${String(row._id)}`}
                          checked={selectedIds.includes(String(row._id))}
                          onChange={() => toggleRowSelection(String(row._id))}
                        />
                      </td>
                      {effectiveVisibleCols.map((col) => (
                        <td key={col} className="whitespace-nowrap px-3 py-2">
                          {row[col] == null ? '' : String(row[col])}
                        </td>
                      ))}
                      <td className="px-3 py-2">
                        <Button variant="secondary" onClick={() => setEditingId(String(row._id))}>
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
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" onClick={handleLoadMore} disabled={loadingMore}>
                {loadingMore ? 'Chargement…' : `Charger plus (${rows.length}/${total})`}
              </Button>
            </div>
          )}
        </>
      )}

      {editingId && orgId && (
        <RecordEditDialog
          orgId={orgId}
          recordId={editingId}
          onClose={() => setEditingId(null)}
          onSaved={handleRecordSaved}
        />
      )}
    </div>
  )
}
