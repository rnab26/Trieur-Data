import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  PIPELINE_UNASSIGNED,
  applyPipelineMapping,
  createPipelineSession,
  exportPipelineSessionRows,
  getMasterColumns,
  listPipelineSessionRows,
  suggestPipelineMapping,
  type ColFilters,
  type PipelineMappingResult,
  type PipelineSessionCreated,
} from '@/lib/api'
import { ColumnFilters } from './ColumnFilters'

// Trieur de Data -- étape 1 du pipeline (import + mapping des colonnes),
// mirroir simplifié des onglets 1-2 Streamlit (views/tab2_import_mapping.py) :
// UNE étape à la fois plutôt qu'une grille complexe. Une fois le mapping
// construit (étape "done"), filtre/recherche + export réutilisent les mêmes
// composants et la même logique que Base de données (DatabaseScreen.tsx),
// mais portent sur le staging de la session (trieur_data.pipeline_rows, TTL
// 24h), jamais sur les enregistrements permanents. Le dédoublonnage
// (confirmation/import définitif) reste hors périmètre ici -- prochain
// chantier (voir PROJECT_LOG.md).
type Step = 'upload' | 'mapping' | 'done'

const PREVIEW_COLS_MAX = 8
const ROWS_PAGE_SIZE = 50

export function PipelineScreen() {
  const { session: authSession, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()

  const [step, setStep] = useState<Step>('upload')

  const [uploading, setUploading] = useState(false)
  const [uploadElapsedSec, setUploadElapsedSec] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [pipelineSession, setPipelineSession] = useState<PipelineSessionCreated | null>(null)

  const [masterColumns, setMasterColumns] = useState<string[] | null>(null)
  const [masterColumnsError, setMasterColumnsError] = useState<string | null>(null)

  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})

  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)
  const [result, setResult] = useState<PipelineMappingResult | null>(null)

  // Étape "done" -- filtrage/recherche + export sur les lignes en staging
  // de la session (voir listPipelineSessionRows/exportPipelineSessionRows,
  // même principe que DatabaseScreen.tsx pour /records).
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [colFilters, setColFilters] = useState<ColFilters>({})
  const [rowsLoading, setRowsLoading] = useState(false)
  const [rowsLoadingMore, setRowsLoadingMore] = useState(false)
  const [rowsError, setRowsError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [rowsPage, setRowsPage] = useState(1)
  const [rowCount, setRowCount] = useState(0)
  const [filteredCount, setFilteredCount] = useState(0)
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Ordre + sélection des colonnes avant export -- équivalent du
  // glisser-déposer streamlit-sortables de views/tab4_export.py (colonnes
  // incluses/exclues). Native HTML5 drag-and-drop est peu fiable au
  // toucher (usage principal : téléphone) -- flèches haut/bas, comme déjà
  // fait pour l'ordre des colonnes maîtres (MasterColumnsPanel.tsx), même
  // patron dans toute l'app. `colOrder` porte TOUTES les colonnes connues
  // (incluses et exclues) ; `excludedCols` marque celles à exclure.
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

  const colFiltersKey = useMemo(() => JSON.stringify(colFilters), [colFilters])

  // Fusionne les colonnes nouvellement vues dans l'ordre existant, en fin
  // de liste (jamais de colonne perdue silencieusement) -- une colonne
  // déjà connue garde sa position/son statut inclus/exclu tel que
  // l'utilisateur l'a réglé.
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

  function moveColUp(i: number) {
    if (i === 0) return
    setColOrder((prev) => {
      const next = [...prev]
      ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
      return next
    })
  }

  function moveColDown(i: number) {
    setColOrder((prev) => {
      if (i >= prev.length - 1) return prev
      const next = [...prev]
      ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
      return next
    })
  }

  function toggleColIncluded(col: string) {
    setExcludedCols((prev) => {
      const next = new Set(prev)
      if (next.has(col)) next.delete(col)
      else next.add(col)
      return next
    })
  }

  // Paginé comme DatabaseScreen ("Charger plus") depuis la revue PR #24
  // (point #7) : avant, cette page recevait TOUTE la session en une
  // réponse et tronquait juste l'affichage à 50 lignes côté client --
  // un gros fichier (centaines de milliers de lignes) transférait tout
  // pour n'en montrer qu'une fraction. La recherche/les filtres restent
  // appliqués sur toute la session côté serveur (voir api/main.py) --
  // seule la page RENVOYÉE change.
  const fetchRows = useCallback(
    async (
      orgIdVal: string,
      sessionId: string,
      targetSearch: string,
      targetColFilters: ColFilters,
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
          search: targetSearch,
          colFilters: targetColFilters,
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

  useEffect(() => {
    if (step !== 'done' || !orgId || !pipelineSession) return
    void fetchRows(orgId, pipelineSession.session_id, search, colFilters, 1, false)
    // colFiltersKey sert de dépendance stable (colFilters change de
    // référence à chaque frappe côté ColumnFilters) -- colFilters lui-même
    // reste utilisé dans le corps de l'effet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, orgId, pipelineSession, search, colFiltersKey, fetchRows])

  function handleLoadMoreRows() {
    if (!orgId || !pipelineSession) return
    void fetchRows(orgId, pipelineSession.session_id, search, colFilters, rowsPage + 1, true)
  }

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSearch(searchInput.trim())
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    if (!orgId || !pipelineSession) return
    setExporting(format)
    setExportError(null)
    try {
      const selectedColumns = colOrder.filter((c) => !excludedCols.has(c))
      await exportPipelineSessionRows(orgId, pipelineSession.session_id, {
        format,
        search,
        colFilters,
        columns: selectedColumns.length > 0 ? selectedColumns : undefined,
      })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setExporting(null)
    }
  }

  // Colonnes maîtres de l'environnement -- cible du mapping, mêmes
  // réglages que l'onglet "Colonnes maîtres" de la Base de données (une
  // seule source de vérité, voir api.ts).
  useEffect(() => {
    if (!orgId) return
    let cancelled = false
    setMasterColumnsError(null)
    getMasterColumns(orgId)
      .then((data) => {
        if (!cancelled) setMasterColumns(data.columns)
      })
      .catch((err: unknown) => {
        if (!cancelled) setMasterColumnsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  function reset() {
    setStep('upload')
    setPipelineSession(null)
    setUploadError(null)
    setSuggestError(null)
    setMapping({})
    setResult(null)
    setBuildError(null)
    setSearch('')
    setSearchInput('')
    setColFilters({})
    setRows([])
    setRowsPage(1)
    setRowCount(0)
    setFilteredCount(0)
    setRowsError(null)
    setExportError(null)
    setColOrder([])
    setExcludedCols(new Set())
  }

  async function handleFileChange(orgIdVal: string, file: File | null) {
    if (!file) return
    setUploading(true)
    setUploadElapsedSec(0)
    setUploadError(null)
    setResult(null)
    // La création de session lit/écrit le fichier ENTIER de façon
    // synchrone côté serveur (voir api/main.py:create_pipeline_session_endpoint)
    // -- pas de vraie progression connue à l'avance (contrairement à la
    // barre par lot de ChantierCard.tsx). Un chrono texte suffit tant que
    // l'attente reste de l'ordre de quelques secondes ; mesuré en local
    // sur un CSV de 50 000 lignes le 2026-09-18 (voir PROJECT_LOG.md) --
    // le parsing/staging pur reste sous la seconde, le vrai temps observé
    // en prod dépend surtout des allers-retours réseau vers Supabase.
    const startedAt = Date.now()
    const interval = window.setInterval(() => {
      setUploadElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    try {
      const data = await createPipelineSession(orgIdVal, file)
      setPipelineSession(data)
      setStep('mapping')
      await loadSuggestion(orgIdVal, data.session_id)
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      window.clearInterval(interval)
      setUploading(false)
    }
  }

  async function loadSuggestion(orgIdVal: string, sessionId: string) {
    setSuggestLoading(true)
    setSuggestError(null)
    try {
      const data = await suggestPipelineMapping(orgIdVal, sessionId)
      setMapping(data.suggested_mapping)
    } catch (err) {
      setSuggestError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSuggestLoading(false)
    }
  }

  async function handleBuild() {
    if (!orgId || !pipelineSession) return
    setBuilding(true)
    setBuildError(null)
    try {
      const data = await applyPipelineMapping(orgId, pipelineSession.session_id, mapping)
      setResult(data)
      setStep('done')
    } catch (err) {
      setBuildError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBuilding(false)
    }
  }

  const assignedCount = Object.values(mapping).filter((m) => m && m !== PIPELINE_UNASSIGNED).length

  // Le backend garde la DERNIÈRE valeur quand deux colonnes source sont
  // mappées sur la MÊME colonne maître (limite documentée de
  // apply_pipeline_mapping, voir api/main.py) -- ça perd silencieusement
  // les données de la première colonne source. Plutôt que de laisser ça
  // se produire sans prévenir, on bloque "Construire" tant qu'un même
  // choix est utilisé deux fois (revue PR #24, point #4).
  const duplicateMasterCols = useMemo(() => {
    const counts = new Map<string, number>()
    for (const m of Object.values(mapping)) {
      if (!m || m === PIPELINE_UNASSIGNED) continue
      counts.set(m, (counts.get(m) ?? 0) + 1)
    }
    return [...counts.entries()].filter(([, n]) => n > 1).map(([col]) => col)
  }, [mapping])

  const canBuild = assignedCount > 0 && duplicateMasterCols.length === 0 && !building

  return (
    <div className="mx-auto max-w-3xl p-4">
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
              reset()
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
          {/* Fil d'étapes -- une seule active à la fois, jamais de contrôle
              d'une étape non atteinte affiché en même temps. */}
          <div className="mb-4 flex items-center gap-2 text-sm text-[var(--muted)]">
            <span className={step === 'upload' ? 'font-semibold text-[var(--foreground)]' : ''}>
              1. Importer
            </span>
            <span>→</span>
            <span className={step === 'mapping' ? 'font-semibold text-[var(--foreground)]' : ''}>
              2. Mapper les colonnes
            </span>
            <span>→</span>
            <span className={step === 'done' ? 'font-semibold text-[var(--foreground)]' : ''}>
              3. Construit
            </span>
          </div>

          {step === 'upload' && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-[var(--muted)]">
                Importe un fichier Excel ou CSV. Il n'est pas encore écrit dans la base : cette
                session reste temporaire (24h) jusqu'à confirmation du mapping.
              </p>
              <input
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => void handleFileChange(orgId, e.target.files?.[0] ?? null)}
                className="text-sm"
              />
              {uploading && (
                <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
                  <span
                    className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                    aria-hidden="true"
                  />
                  Lecture et mise en attente du fichier… ({uploadElapsedSec}s)
                  {uploadElapsedSec >= 8 && ' -- un gros fichier peut prendre encore quelques instants.'}
                </p>
              )}
              {uploadError && <p className="text-sm text-[var(--danger)]">Erreur : {uploadError}</p>}
            </div>
          )}

          {step === 'mapping' && pipelineSession && (
            <div className="flex flex-col gap-4">
              <div>
                <p className="text-sm">
                  {pipelineSession.row_count} ligne(s) détectée(s) dans{' '}
                  <span className="font-medium">{pipelineSession.columns.length}</span> colonne(s).
                </p>
                {pipelineSession.unknown_columns.length > 0 && (
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    Colonne(s) inconnue(s) des colonnes maîtres :{' '}
                    {pipelineSession.unknown_columns.join(', ')} -- mappe-les ci-dessous ou laisse
                    "(non assigné)" pour les ignorer.
                  </p>
                )}
              </div>

              {pipelineSession.preview_rows.length > 0 && (
                <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
                  <table className="w-full min-w-max text-sm">
                    <thead>
                      <tr className="bg-[var(--muted-bg)] text-left">
                        {pipelineSession.columns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                          <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                            {c}
                          </th>
                        ))}
                        {pipelineSession.columns.length > PREVIEW_COLS_MAX && (
                          <th className="px-3 py-2 font-medium text-[var(--muted)]">…</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {pipelineSession.preview_rows.slice(0, 5).map((row, i) => (
                        <tr key={i} className="border-t border-[var(--border)]">
                          {pipelineSession.columns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                            <td key={c} className="whitespace-nowrap px-3 py-2">
                              {row[c] == null ? '' : String(row[c])}
                            </td>
                          ))}
                          {pipelineSession.columns.length > PREVIEW_COLS_MAX && (
                            <td className="px-3 py-2 text-[var(--muted)]">…</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div>
                <h2 className="mb-2 text-base font-semibold">Mapping des colonnes</h2>
                {masterColumnsError && (
                  <p className="mb-2 text-sm text-[var(--danger)]">
                    Impossible de charger les colonnes maîtres : {masterColumnsError}
                  </p>
                )}
                {masterColumns && masterColumns.length === 0 && !masterColumnsError && (
                  <p className="mb-2 text-sm text-[var(--muted)]">
                    Aucune colonne maître définie pour cet environnement -- va d'abord en créer
                    dans "Base de données → Colonnes maîtres", sinon tout restera "(non assigné)".
                  </p>
                )}
                {suggestLoading && (
                  <p className="mb-2 text-sm text-[var(--muted)]">Suggestion automatique du mapping…</p>
                )}
                {suggestError && (
                  <p className="mb-2 text-sm text-[var(--danger)]">
                    Erreur de suggestion : {suggestError} -- tu peux mapper manuellement ci-dessous.
                  </p>
                )}

                {!suggestLoading && (
                  <div className="flex flex-col gap-2">
                    {pipelineSession.columns.map((col) => (
                      <div
                        key={col}
                        className="flex flex-col gap-1 rounded-md border border-[var(--border)] p-3 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <span className="text-sm font-medium">{col}</span>
                        <select
                          value={mapping[col] ?? PIPELINE_UNASSIGNED}
                          onChange={(e) =>
                            setMapping((prev) => ({ ...prev, [col]: e.target.value }))
                          }
                          className={
                            'w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm sm:w-56 ' +
                            (duplicateMasterCols.includes(mapping[col] ?? '')
                              ? 'border-[var(--danger)]'
                              : 'border-[var(--border)]')
                          }
                        >
                          <option value={PIPELINE_UNASSIGNED}>(non assigné)</option>
                          {(masterColumns ?? []).map((mc) => (
                            <option key={mc} value={mc}>
                              {mc}
                            </option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {duplicateMasterCols.length > 0 && (
                <p className="text-sm text-[var(--danger)]">
                  {duplicateMasterCols.length === 1 ? 'Colonne maître choisie' : 'Colonnes maîtres choisies'}{' '}
                  plusieurs fois : {duplicateMasterCols.join(', ')} -- seule la dernière colonne source
                  assignée serait gardée, les autres seraient perdues. Choisis une colonne maître différente
                  pour chacune avant de construire.
                </p>
              )}

              {buildError && <p className="text-sm text-[var(--danger)]">Erreur : {buildError}</p>}

              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => void handleBuild()} disabled={!canBuild}>
                  {building ? 'Construction…' : 'Construire'}
                </Button>
                <Button variant="secondary" onClick={reset} disabled={building}>
                  Annuler
                </Button>
                {assignedCount === 0 && !suggestLoading && (
                  <span className="text-sm text-[var(--muted)]">
                    Assigne au moins une colonne pour construire.
                  </span>
                )}
              </div>
            </div>
          )}

          {step === 'done' && result && pipelineSession && (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-[var(--success,#16a34a)]">
                {result.n_rows_updated} ligne(s) mappée(s) et prête(s) pour la suite du pipeline.
              </p>
              <p className="text-sm text-[var(--muted)]">
                Le dédoublonnage/import définitif n'est pas encore disponible ici -- prochaine étape
                à venir. En attendant, filtre et exporte ces lignes en staging (24h).
              </p>

              <form onSubmit={handleSearchSubmit} className="flex flex-wrap gap-2">
                <Input
                  placeholder="Rechercher…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="max-w-xs"
                />
                <Button type="submit" variant="secondary">
                  Rechercher
                </Button>
              </form>

              <ColumnFilters columns={rowsColumns} filters={colFilters} onChange={setColFilters} />

              {colOrder.length > 0 && (
                <details className="rounded-md border border-[var(--border)] p-3">
                  <summary className="cursor-pointer text-sm font-medium">
                    🔀 Ordre et sélection des colonnes à l'export ({colOrder.length - excludedCols.size}/
                    {colOrder.length} incluse(s))
                  </summary>
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Décoche une colonne pour l'exclure de l'export, utilise les flèches pour changer
                    son ordre dans le fichier généré.
                  </p>
                  <ul className="mt-2 flex flex-col gap-1">
                    {colOrder.map((col, i) => (
                      <li key={col} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={!excludedCols.has(col)}
                          onChange={() => toggleColIncluded(col)}
                          aria-label={`Inclure la colonne ${col} dans l'export`}
                        />
                        <span className={`flex-1 text-sm ${excludedCols.has(col) ? 'text-[var(--muted)] line-through' : ''}`}>
                          {col}
                        </span>
                        <Button variant="secondary" onClick={() => moveColUp(i)} disabled={i === 0}>
                          ⬆️
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => moveColDown(i)}
                          disabled={i === colOrder.length - 1}
                        >
                          ⬇️
                        </Button>
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">💾 Exporter ces résultats</span>
                <Button
                  variant="secondary"
                  disabled={exporting !== null || filteredCount === 0 || colOrder.length === excludedCols.size}
                  onClick={() => void handleExport('csv')}
                >
                  {exporting === 'csv' ? 'Préparation…' : 'Exporter CSV'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={exporting !== null || filteredCount === 0 || colOrder.length === excludedCols.size}
                  onClick={() => void handleExport('xlsx')}
                >
                  {exporting === 'xlsx' ? 'Préparation…' : 'Exporter Excel'}
                </Button>
                <span className="text-xs text-[var(--muted)]">
                  {filteredCount} / {rowCount} ligne(s), avec la recherche/les filtres actuels.
                </span>
              </div>
              {colOrder.length > 0 && colOrder.length === excludedCols.size && (
                <p className="text-sm text-[var(--danger)]">
                  Toutes les colonnes sont exclues -- inclus-en au moins une pour exporter.
                </p>
              )}
              {exportError && (
                <p className="text-sm text-[var(--danger)]">Erreur d'export : {exportError}</p>
              )}

              {rowsLoading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
              {rowsError && !rowsLoading && (
                <p className="text-sm text-[var(--danger)]">Erreur : {rowsError}</p>
              )}
              {!rowsLoading && !rowsError && rows.length === 0 && (
                <p className="text-sm text-[var(--muted)]">
                  {search || Object.keys(colFilters).length > 0
                    ? 'Aucun résultat pour cette recherche/ces filtres.'
                    : 'Aucune ligne dans cette session.'}
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
                <Button variant="secondary" onClick={reset}>
                  Importer un autre fichier
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
