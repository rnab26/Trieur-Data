import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { useIsAdmin, useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  getMasterColumns,
  listPipelineSessionRows,
  type FilterGroup,
  type PipelineMappingResult,
  type PipelineSessionCreated,
} from '@/lib/api'
import { MasterColumnsPanel } from './MasterColumnsPanel'
import { PipelineImportPanel } from './PipelineImportPanel'
import { PipelineDedupPanel } from './PipelineDedupPanel'
import { PipelineExportPanel } from './PipelineExportPanel'
import { PipelineFilterGroups } from './PipelineFilterGroups'

// Trieur de Data -- MÊME architecture à 4 onglets que la version
// Streamlit (views/tab1_colonnes_maitres.py .. tab4_export.py), portée
// sur l'API REST : "Colonnes maîtres" (réglages qui pilotent tout le
// reste, réutilise MasterColumnsPanel -- une seule notion de colonnes
// maîtres dans toute l'app, jamais une deuxième liste), "Importer +
// mapper", "Filtrer + dédoublonner" et "Exporter". Un onglet à la fois,
// jamais une refonte du principe : on ne mélange pas les étapes, mais on
// ne les réduit pas non plus à un simple assistant linéaire -- chaque
// onglet reste accessible et garde son état pendant qu'on va voir les
// autres, comme dans la version Streamlit d'origine.
type Tab = 'colonnes' | 'import' | 'filtrer' | 'exporter'

const ROWS_PAGE_SIZE = 50
const PREVIEW_COLS_MAX = 8

export function PipelineScreen() {
  const { session: authSession, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()
  const { isAdmin } = useIsAdmin(true)

  const [tab, setTab] = useState<Tab>('import')

  // État de la session pipeline construite (import + mapping confirmés) --
  // partagé entre les onglets Filtrer/Exporter, qui opèrent tous les deux
  // sur le MÊME staging (trieur_data.pipeline_rows), jamais une copie.
  const [pipelineSession, setPipelineSession] = useState<PipelineSessionCreated | null>(null)
  const [buildResult, setBuildResult] = useState<PipelineMappingResult | null>(null)

  const [masterColumns, setMasterColumns] = useState<string[]>([])
  const [masterColumnsError, setMasterColumnsError] = useState<string | null>(null)

  // Filtre multi-critères (groupes OU de critères ET, copie conforme de
  // views/tab3_filtrage_dedup.py -- voir PipelineFilterGroups) +
  // dédoublonnage -- partagés par Filtrer et Exporter (l'export utilise
  // EXACTEMENT le même résultat que ce que l'écran de filtrage affiche,
  // jamais une deuxième logique).
  const [filterGroups, setFilterGroups] = useState<FilterGroup[]>([[]])
  const [dedupConfig, setDedupConfig] = useState<
    { column: string; keep: string } | { column: string; mode: 'manual'; keep_indices: number[] } | null
  >(null)

  const [rowsLoading, setRowsLoading] = useState(false)
  const [rowsLoadingMore, setRowsLoadingMore] = useState(false)
  const [rowsError, setRowsError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [rowsPage, setRowsPage] = useState(1)
  const [rowCount, setRowCount] = useState(0)
  const [filteredCount, setFilteredCount] = useState(0)

  // Ordre + sélection des colonnes à l'export (onglet 4) -- porte TOUTES
  // les colonnes connues, `excludedCols` marque celles à exclure.
  const [colOrder, setColOrder] = useState<string[]>([])
  const [excludedCols, setExcludedCols] = useState<Set<string>>(new Set())

  const rowsColumns = useMemo(() => {
    const cols: string[] = []
    for (const row of rows) {
      for (const key of Object.keys(row)) {
        if (!cols.includes(key)) cols.push(key)
      }
    }
    return cols
  }, [rows])

  const filterGroupsKey = useMemo(() => JSON.stringify(filterGroups), [filterGroups])

  // Fusionne les colonnes nouvellement vues dans l'ordre existant, en fin
  // de liste (jamais de colonne perdue silencieusement) -- une colonne
  // déjà connue garde sa position/son statut inclus/exclu.
  useEffect(() => {
    setColOrder((prev) => {
      const known = new Set(prev)
      const newOnes = rowsColumns.filter((c) => !known.has(c))
      if (newOnes.length === 0 && prev.length === rowsColumns.filter((c) => known.has(c)).length) {
        return prev
      }
      const stillPresent = prev.filter((c) => rowsColumns.includes(c))
      return [...stillPresent, ...newOnes]
    })
  }, [rowsColumns])

  // Colonnes maîtres de l'environnement -- cible du mapping ET des
  // filtres/dédoublonnage. Rechargées après toute modification faite
  // dans l'onglet "Colonnes maîtres" (voir onColumnsChanged).
  const loadMasterColumns = useCallback((orgIdVal: string) => {
    setMasterColumnsError(null)
    return getMasterColumns(orgIdVal)
      .then((data) => setMasterColumns(data.columns))
      .catch((err: unknown) => {
        setMasterColumnsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
  }, [])

  useEffect(() => {
    if (!orgId) return
    void loadMasterColumns(orgId)
  }, [orgId, loadMasterColumns])

  const fetchRows = useCallback(
    async (
      orgIdVal: string,
      sessionId: string,
      targetFilterGroups: FilterGroup[],
      targetPage: number,
      append: boolean,
    ) => {
      if (append) setRowsLoadingMore(true)
      else setRowsLoading(true)
      setRowsError(null)
      try {
        const data = await listPipelineSessionRows(orgIdVal, sessionId, {
          page: targetPage,
          pageSize: ROWS_PAGE_SIZE,
          filterGroups: targetFilterGroups,
        })
        setRows((prev) => (append ? [...prev, ...data.rows] : data.rows))
        setRowsPage(data.page)
        setRowCount(data.row_count)
        setFilteredCount(data.count)
      } catch (err) {
        setRowsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      } finally {
        setRowsLoading(false)
        setRowsLoadingMore(false)
      }
    },
    [],
  )

  // Recharge les lignes dès que la session est construite, que le
  // filtre change, OU que le dédoublonnage change (le serveur le
  // réapplique lui-même -- on relit juste pour refléter le nouveau
  // compte de lignes à l'écran).
  useEffect(() => {
    if (!orgId || !pipelineSession) return
    void fetchRows(orgId, pipelineSession.session_id, filterGroups, 1, false)
    // filterGroupsKey sert de dépendance stable (filterGroups change de
    // référence à chaque frappe côté PipelineFilterGroups) -- filterGroups
    // lui-même reste utilisé dans le corps de l'effet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, pipelineSession, filterGroupsKey, dedupConfig, fetchRows])

  function handleLoadMoreRows() {
    if (!orgId || !pipelineSession) return
    void fetchRows(orgId, pipelineSession.session_id, filterGroups, rowsPage + 1, true)
  }

  function handleBuilt(newSession: PipelineSessionCreated, result: PipelineMappingResult) {
    setPipelineSession(newSession)
    setBuildResult(result)
    setDedupConfig(null)
    setFilterGroups([[]])
    setRows([])
    setRowsPage(1)
    setRowCount(0)
    setFilteredCount(0)
    setColOrder([])
    setExcludedCols(new Set())
    setTab('filtrer')
  }

  function handleImportAnother() {
    setPipelineSession(null)
    setBuildResult(null)
    setTab('import')
  }

  async function onColumnsChanged() {
    if (orgId) await loadMasterColumns(orgId)
  }

  return (
    <div className="mx-auto max-w-5xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Trieur de Data</h1>
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <span>{authSession?.user.email}</span>
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
          <label htmlFor="pipeline-org-switcher" className="text-sm text-[var(--muted)]">
            Environnement
          </label>
          <select
            id="pipeline-org-switcher"
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
            value={orgId ?? ''}
            onChange={(e) => {
              setOrgId(e.target.value)
              handleImportAnother()
            }}
          >
            {orgs.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {orgId && (
        <>
          <nav className="mb-4 flex flex-wrap gap-1 border-b border-[var(--border)]" role="tablist">
            {(
              [
                ['colonnes', 'Colonnes maîtres'],
                ['import', 'Importer'],
                ['filtrer', 'Filtrer'],
                ['exporter', 'Exporter'],
              ] as [Tab, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                type="button"
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
          </nav>

          {/* Chaque onglet reste MONTÉ en permanence (juste masqué via `hidden`)
              tant que orgId ne change pas -- comme st.session_state côté
              Streamlit, qui ne perdait jamais l'import/mapping en cours quand
              on allait consulter un autre onglet. Démonter <PipelineImportPanel>
              à chaque changement d'onglet détruisait son fichier importé/son
              mapping en cours (state local React) -- constaté en réel par
              l'utilisateur : retour sur "Colonnes maîtres" puis retour sur
              "Importer" = fichier à réimporter depuis zéro.

              `key={orgId}` sur les deux panneaux qui gardent un état LOCAL lié
              à une session pipeline (fichier importé, mapping en cours) :
              bug réel constaté (logs Render) -- changer d'environnement en
              cours de mapping laissait le state local (session_id créé sous
              l'ANCIEN org) survivre pendant que la prop `orgId` passait au
              NOUVEL org, donc "Construire" envoyait un org_id qui ne
              correspondait plus à la session -> 404 "session introuvable".
              `key` force React à démonter/remonter ces panneaux (state
              local reparti à zéro) exactement quand orgId change, jamais
              juste en changeant d'onglet. */}
          <div hidden={tab !== 'colonnes'}>
            <MasterColumnsPanel key={orgId} orgId={orgId} isAdmin={isAdmin} onSaved={onColumnsChanged} />
          </div>

          <div hidden={tab !== 'import'}>
            <PipelineImportPanel key={orgId} orgId={orgId} masterColumns={masterColumns} onBuilt={handleBuilt} />
          </div>

          <div hidden={tab !== 'filtrer'}>
            <>
              {!pipelineSession && (
                <p className="text-sm text-[var(--muted)]">
                  Aucune base construite pour l'instant -- importe et mappe d'abord un fichier dans
                  l'onglet "Importer".
                </p>
              )}
              {pipelineSession && buildResult && (
                <div className="flex flex-col gap-4">
                  <p className="text-sm text-[var(--success,#16a34a)]">
                    {buildResult.n_rows_updated} ligne(s) mappée(s) et prête(s) à filtrer/exporter
                    (staging temporaire, 24h).
                  </p>

                  {buildResult.iban_warnings.length > 0 && (
                    <p className="text-sm text-[var(--danger)]">
                      ⚠️{' '}
                      {buildResult.iban_warnings
                        .map((w) => `${w.n_invalid} IBAN(s) suspect(s) sur "${w.column}"`)
                        .join(', ')}{' '}
                      (checksum invalide) -- rien n'est supprimé automatiquement, à vérifier avant
                      l'export final.
                    </p>
                  )}

                  <PipelineFilterGroups
                    orgId={orgId}
                    sessionId={pipelineSession.session_id}
                    masterColumns={masterColumns}
                    groups={filterGroups}
                    onChange={setFilterGroups}
                  />

                  <hr className="border-[var(--border)]" />

                  <PipelineDedupPanel
                    orgId={orgId}
                    sessionId={pipelineSession.session_id}
                    columns={rowsColumns}
                    filterGroups={filterGroups}
                    activeDedup={dedupConfig}
                    onDedupChanged={setDedupConfig}
                  />

                  {rowsLoading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
                  {rowsError && !rowsLoading && (
                    <p className="text-sm text-[var(--danger)]">Erreur : {rowsError}</p>
                  )}
                  {!rowsLoading && !rowsError && rows.length === 0 && (
                    <p className="text-sm text-[var(--muted)]">
                      Aucun résultat pour ce filtre, ou aucune ligne dans cette session.
                    </p>
                  )}

                  {!rowsLoading && !rowsError && rows.length > 0 && (
                    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                      <table className="w-full min-w-max text-sm">
                        <thead>
                          <tr className="bg-[var(--muted-bg)] text-left">
                            {rowsColumns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                              <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                                {c}
                              </th>
                            ))}
                            {rowsColumns.length > PREVIEW_COLS_MAX && (
                              <th className="px-3 py-2 font-medium text-[var(--muted)]">…</th>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row, i) => (
                            <tr key={i} className="border-t border-[var(--border)]">
                              {rowsColumns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                                <td key={c} className="whitespace-nowrap px-3 py-2">
                                  {row[c] == null ? '' : String(row[c])}
                                </td>
                              ))}
                              {rowsColumns.length > PREVIEW_COLS_MAX && (
                                <td className="px-3 py-2 text-[var(--muted)]">…</td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {!rowsLoading && !rowsError && rows.length > 0 && rows.length < filteredCount && (
                    <div className="flex justify-center">
                      <Button variant="secondary" onClick={handleLoadMoreRows} disabled={rowsLoadingMore}>
                        {rowsLoadingMore ? 'Chargement…' : `Charger plus (${rows.length}/${filteredCount})`}
                      </Button>
                    </div>
                  )}

                  <div>
                    <Button variant="secondary" onClick={handleImportAnother}>
                      Importer un autre fichier
                    </Button>
                  </div>
                </div>
              )}
            </>
          </div>

          <div hidden={tab !== 'exporter'}>
            <>
              {!pipelineSession && (
                <p className="text-sm text-[var(--muted)]">
                  Aucune base construite pour l'instant -- importe et mappe d'abord un fichier dans
                  l'onglet "Importer".
                </p>
              )}
              {pipelineSession && filteredCount === 0 && rows.length === 0 && !rowsLoading && (
                <p className="text-sm text-[var(--danger)]">
                  Le résultat filtré est vide -- ajuste le filtre dans l'onglet "Filtrer" avant
                  d'exporter.
                </p>
              )}
              {pipelineSession && (
                <PipelineExportPanel
                  orgId={orgId}
                  sessionId={pipelineSession.session_id}
                  colOrder={colOrder}
                  excludedCols={excludedCols}
                  onColOrderChange={setColOrder}
                  onExcludedColsChange={setExcludedCols}
                  filterGroups={filterGroups}
                  rowCount={rowCount}
                  filteredCount={filteredCount}
                />
              )}
            </>
          </div>

          {masterColumnsError && (
            <p className="mt-4 text-sm text-[var(--danger)]">
              Impossible de charger les colonnes maîtres : {masterColumnsError}
            </p>
          )}
        </>
      )}
    </div>
  )
}
