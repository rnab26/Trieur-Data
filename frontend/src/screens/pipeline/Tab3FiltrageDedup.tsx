import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ColumnFilters } from '@/screens/ColumnFilters'
import {
  ApiError,
  applyPipelineDedupe,
  getPipelineDuplicates,
  listPipelineSessionRows,
  type ColFilters,
  type PipelineDuplicateGroup,
  type PipelineDuplicates,
  type PipelineFilterGroup,
} from '@/lib/api'

const PREVIEW_COLS_MAX = 8
const ROWS_PAGE_SIZE = 50

// Un critère du filtre multi-critères (onglet 3) édité à l'écran -- porte
// un `id` local pour les clés React et le retrait individuel ; converti en
// PipelineFilterGroup (sans id) avant tout appel API, voir apiGroups dans
// PipelineScreen.tsx.
export type UiCriterion = { id: string; column: string; kind: 'departements' | 'valeurs'; values: string[] }
export type UiGroup = { id: string; criteria: UiCriterion[] }

let uidCounter = 0
export function newUid() {
  uidCounter += 1
  return `c${Date.now()}_${uidCounter}`
}

export function emptyCriterion(defaultColumn: string): UiCriterion {
  return { id: newUid(), column: defaultColumn, kind: 'valeurs', values: [] }
}

function describeCriterion(c: UiCriterion): string {
  const vals = c.values.length ? c.values.join(', ') : '(vide)'
  return c.kind === 'departements' ? `${c.column} dept ${vals}` : `${c.column} = ${vals}`
}

function describeGroups(groups: UiGroup[]): string {
  const complete = groups.filter((g) => g.criteria.length > 0 && g.criteria.every((c) => c.column && c.values.length > 0))
  if (complete.length === 0) return '(vide)'
  const strs = complete.map((g) => g.criteria.map(describeCriterion).join(' ET '))
  return strs.length > 1 ? strs.map((s) => `(${s})`).join(' OU ') : strs[0]
}

function CriterionRow({
  criterion,
  masterColumns,
  onChange,
  onRemove,
}: {
  criterion: UiCriterion
  masterColumns: string[]
  onChange: (next: UiCriterion) => void
  onRemove: () => void
}) {
  const isDept = criterion.column === 'CP'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
        value={criterion.column}
        onChange={(e) => {
          const column = e.target.value
          onChange({ ...criterion, column, kind: column === 'CP' ? 'departements' : 'valeurs', values: [] })
        }}
      >
        {masterColumns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      {isDept ? (
        <Input
          className="max-w-xs"
          placeholder="Départements, ex: 02,33,77"
          defaultValue={criterion.values.join(',')}
          onChange={(e) =>
            onChange({
              ...criterion,
              kind: 'departements',
              values: e.target.value
                .split(',')
                .map((p) => p.trim())
                .filter(Boolean)
                .map((p) => p.padStart(2, '0')),
            })
          }
        />
      ) : (
        <Input
          className="max-w-xs"
          placeholder={`Valeur(s) pour ${criterion.column}, séparées par ;`}
          defaultValue={criterion.values.join(';')}
          onChange={(e) =>
            onChange({
              ...criterion,
              kind: 'valeurs',
              values: e.target.value
                .split(';')
                .map((v) => v.trim())
                .filter(Boolean),
            })
          }
        />
      )}
      <Button variant="danger" onClick={onRemove} aria-label="Retirer ce critère">
        🗑️
      </Button>
    </div>
  )
}

export function Tab3FiltrageDedup({
  orgId,
  sessionId,
  sessionMapped,
  masterColumns,
  groups,
  setGroups,
  apiGroups,
  search,
  setSearch,
  colFilters,
  setColFilters,
  refreshKey,
  onDedupeApplied,
}: {
  orgId: string
  sessionId: string | null
  sessionMapped: boolean
  masterColumns: string[] | null
  groups: UiGroup[]
  setGroups: (next: UiGroup[]) => void
  apiGroups: PipelineFilterGroup[]
  search: string
  setSearch: (v: string) => void
  colFilters: ColFilters
  setColFilters: (v: ColFilters) => void
  refreshKey: number
  onDedupeApplied: () => void
}) {
  const [searchInput, setSearchInput] = useState(search)

  const [rowsLoading, setRowsLoading] = useState(false)
  const [rowsLoadingMore, setRowsLoadingMore] = useState(false)
  const [rowsError, setRowsError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [rowsPage, setRowsPage] = useState(1)
  const [rowCount, setRowCount] = useState(0)
  const [filteredCount, setFilteredCount] = useState(0)

  const [dupCol, setDupCol] = useState('(aucune)')
  const [dupLoading, setDupLoading] = useState(false)
  const [dupError, setDupError] = useState<string | null>(null)
  const [dupAnalysis, setDupAnalysis] = useState<PipelineDuplicates | null>(null)
  const [groupChoices, setGroupChoices] = useState<Record<string, string>>({})
  const [groupPreviews, setGroupPreviews] = useState<Record<string, Record<string, unknown>[]>>({})
  const [keepRule, setKeepRule] = useState<'first' | 'complete'>('complete')

  const [dedupeConfirming, setDedupeConfirming] = useState(false)
  const [dedupeApplying, setDedupeApplying] = useState(false)
  const [dedupeError, setDedupeError] = useState<string | null>(null)
  const [dedupeSuccess, setDedupeSuccess] = useState<string | null>(null)

  const colFiltersKey = useMemo(() => JSON.stringify(colFilters), [colFilters])
  const groupsKey = useMemo(() => JSON.stringify(apiGroups), [apiGroups])

  const rowsColumns = useMemo(() => {
    const cols: string[] = []
    for (const row of rows) {
      for (const key of Object.keys(row)) {
        if (!cols.includes(key)) cols.push(key)
      }
    }
    return cols
  }, [rows])

  const fetchRows = useCallback(
    async (targetPage: number, append: boolean) => {
      if (!sessionId) return
      if (append) setRowsLoadingMore(true)
      else setRowsLoading(true)
      setRowsError(null)
      try {
        const data = await listPipelineSessionRows(orgId, sessionId, {
          page: targetPage,
          pageSize: ROWS_PAGE_SIZE,
          search,
          colFilters,
          groups: apiGroups,
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [orgId, sessionId, search, colFiltersKey, groupsKey],
  )

  useEffect(() => {
    if (!sessionMapped || !sessionId) return
    void fetchRows(1, false)
    // colFiltersKey/groupsKey servent de dépendances stables (les objets
    // changent de référence à chaque frappe) -- colFilters/apiGroups
    // eux-mêmes restent utilisés dans le corps de fetchRows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionMapped, sessionId, search, colFiltersKey, groupsKey, refreshKey, fetchRows])

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSearch(searchInput.trim())
  }

  function addGroup() {
    setGroups([...groups, { id: newUid(), criteria: [emptyCriterion(masterColumns?.[0] ?? '')] }])
  }

  function removeGroup(gi: number) {
    if (groups.length <= 1) return
    setGroups(groups.filter((_, i) => i !== gi))
  }

  function addCriterion(gi: number) {
    const next = [...groups]
    next[gi] = { ...next[gi], criteria: [...next[gi].criteria, emptyCriterion(masterColumns?.[0] ?? '')] }
    setGroups(next)
  }

  function updateCriterion(gi: number, ci: number, crit: UiCriterion) {
    const next = [...groups]
    const critList = [...next[gi].criteria]
    critList[ci] = crit
    next[gi] = { ...next[gi], criteria: critList }
    setGroups(next)
  }

  function removeCriterion(gi: number, ci: number) {
    const next = [...groups]
    const critList = next[gi].criteria.filter((_, i) => i !== ci)
    if (critList.length === 0 && next.length > 1) {
      next.splice(gi, 1)
    } else {
      next[gi] = { ...next[gi], criteria: critList }
    }
    setGroups(next)
  }

  async function handleAnalyzeDuplicates() {
    if (!sessionId || dupCol === '(aucune)') return
    setDupLoading(true)
    setDupError(null)
    setDupAnalysis(null)
    setGroupChoices({})
    setGroupPreviews({})
    setDedupeSuccess(null)
    try {
      const data = await getPipelineDuplicates(orgId, sessionId, { column: dupCol, search, colFilters, groups: apiGroups })
      setDupAnalysis(data)
      if (data.group_count > 0 && data.group_count <= data.group_threshold) {
        const choices: Record<string, string> = {}
        for (const g of data.groups) choices[g.value ?? ''] = g.suggested_keep_id
        setGroupChoices(choices)
        // Aperçu réel des lignes de chaque groupe -- une requête par
        // groupe, filtrée sur la valeur exacte de `column` (même
        // filtre actif en plus) : les lignes reviennent dans le même
        // ordre que `row_ids` (même parcours côté serveur), donc
        // l'index i correspond à group.row_ids[i].
        const previews: Record<string, Record<string, unknown>[]> = {}
        await Promise.all(
          data.groups.map(async (g: PipelineDuplicateGroup) => {
            if (g.value == null) return
            try {
              const page = await listPipelineSessionRows(orgId, sessionId, {
                page: 1,
                pageSize: Math.min(g.row_ids.length, 200),
                search,
                colFilters: { ...colFilters, [dupCol]: { op: 'égal à', value: g.value } },
                groups: apiGroups,
              })
              previews[g.value] = page.rows
            } catch {
              // Aperçu best-effort : en cas d'échec, on garde le
              // choix par id (voir fallback d'affichage ci-dessous).
            }
          }),
        )
        setGroupPreviews(previews)
      }
    } catch (err) {
      setDupError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDupLoading(false)
    }
  }

  async function handleApplyDedupe(mode: 'rule' | 'manual') {
    if (!sessionId || dupCol === '(aucune)' || !dupAnalysis) return
    setDedupeApplying(true)
    setDedupeError(null)
    try {
      const keepIds = mode === 'manual' ? dupAnalysis.groups.map((g) => groupChoices[g.value ?? '']) : []
      const result = await applyPipelineDedupe(orgId, sessionId, {
        column: dupCol,
        mode,
        keep: keepRule,
        keepIds,
        search,
        colFilters,
        groups: apiGroups,
      })
      setDedupeSuccess(`✅ Doublons supprimés sur '${dupCol}' (${result.n_removed} ligne(s) retirée(s) définitivement).`)
      setDupAnalysis(null)
      setDedupeConfirming(false)
      onDedupeApplied()
    } catch (err) {
      setDedupeError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDedupeApplying(false)
    }
  }

  if (!sessionMapped) {
    return (
      <div className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Filtrer la base de travail</h2>
        <p className="text-sm text-[var(--muted)]">
          ℹ️ Importez et mappez un fichier dans l'onglet "2. Import et Mapping" avant de filtrer.
        </p>
      </div>
    )
  }

  const cols = masterColumns ?? []
  const groupsDescription = describeGroups(groups)

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">Filtrer la base de travail</h2>
      <p className="text-sm">
        Base actuelle : <strong>{rowCount}</strong> ligne(s) importée(s)
      </p>

      <div>
        <p className="text-sm font-medium">Filtrer par un ou plusieurs critères</p>
        <p className="mb-2 text-xs text-[var(--muted)]">
          Plusieurs groupes = <strong>OU</strong> entre eux ; plusieurs critères dans un groupe ={' '}
          <strong>ET</strong>. Ex : tout le 34, plus le 71 seulement pour Lyon.
        </p>

        {cols.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">
            Aucune colonne maître définie -- va d'abord en créer dans l'onglet "1. Colonnes maîtres".
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {groups.map((group, gi) => (
              <div key={group.id}>
                {gi > 0 && (
                  <div className="my-1 text-center text-sm font-semibold text-[var(--muted)]">OU</div>
                )}
                <div className="rounded-md border border-[var(--border)] p-3">
                  <div className="flex flex-col gap-2">
                    {group.criteria.map((crit, ci) => (
                      <CriterionRow
                        key={crit.id}
                        criterion={crit}
                        masterColumns={cols}
                        onChange={(next) => updateCriterion(gi, ci, next)}
                        onRemove={() => removeCriterion(gi, ci)}
                      />
                    ))}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Button variant="secondary" onClick={() => addCriterion(gi)}>
                      ➕ Critère (ET)
                    </Button>
                    {groups.length > 1 && (
                      <Button variant="ghost" onClick={() => removeGroup(gi)}>
                        Retirer ce groupe
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))}
            <div>
              <Button variant="secondary" onClick={addGroup}>
                ➕ Ajouter un groupe (OU)
              </Button>
            </div>
            <p className="text-xs text-[var(--muted)]">Filtre actuel : {groupsDescription}</p>
          </div>
        )}
      </div>

      <form onSubmit={handleSearchSubmit} className="flex flex-wrap gap-2 border-t border-[var(--border)] pt-3">
        <span className="self-center text-xs text-[var(--muted)]">
          En plus (recherche libre / filtres par colonne) :
        </span>
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
      <ColumnFilters columns={cols.length > 0 ? cols : rowsColumns} filters={colFilters} onChange={setColFilters} />

      <p className="text-sm">
        Résultat filtré : <strong>{filteredCount}</strong> ligne(s) conservée(s) sur <strong>{rowCount}</strong>{' '}
        au total
      </p>

      {dedupeSuccess && <p className="text-sm text-[var(--success,#16a34a)]">{dedupeSuccess}</p>}

      {rowsLoading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {rowsError && !rowsLoading && <p className="text-sm text-[var(--danger)]">Erreur : {rowsError}</p>}
      {!rowsLoading && !rowsError && rows.length === 0 && (
        <p className="text-sm text-[var(--muted)]">
          {search || filteredCount === 0 ? 'Aucun résultat pour ce filtre.' : 'Aucune ligne dans cette session.'}
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
          <Button variant="secondary" onClick={() => void fetchRows(rowsPage + 1, true)} disabled={rowsLoadingMore}>
            {rowsLoadingMore ? 'Chargement…' : `Charger plus (${rows.length}/${filteredCount})`}
          </Button>
        </div>
      )}

      <div className="border-t border-[var(--border)] pt-4">
        <label className="mb-1 block text-sm font-medium" htmlFor="dup-col">
          Colonne pour détecter les doublons (ex: TELEPHONE MOBILE)
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <select
            id="dup-col"
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
            value={dupCol}
            onChange={(e) => {
              setDupCol(e.target.value)
              setDupAnalysis(null)
              setDedupeSuccess(null)
            }}
          >
            <option value="(aucune)">(aucune)</option>
            {cols.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <Button
            variant="secondary"
            disabled={dupCol === '(aucune)' || dupLoading}
            onClick={() => void handleAnalyzeDuplicates()}
          >
            {dupLoading ? 'Analyse…' : `🔎 Analyser les doublons sur '${dupCol}'`}
          </Button>
        </div>
        {dupError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {dupError}</p>}

        {dupAnalysis && dupAnalysis.group_count === 0 && (
          <p className="mt-2 text-sm text-[var(--muted)]">ℹ️ Aucun doublon détecté sur '{dupCol}'.</p>
        )}

        {dupAnalysis && dupAnalysis.group_count > 0 && dupAnalysis.group_count <= dupAnalysis.group_threshold && (
          <div className="mt-3 flex flex-col gap-3">
            <p className="text-sm">
              <strong>{dupAnalysis.group_count} groupe(s) de doublons</strong> ({dupAnalysis.duplicate_row_count}{' '}
              lignes) -- la ligne la plus complète est présélectionnée ; corrige si besoin.
            </p>
            {dupAnalysis.groups.map((g) => {
              const key = g.value ?? ''
              const preview = key ? groupPreviews[key] : undefined
              return (
                <div key={g.row_ids.join(',')} className="rounded-md border border-[var(--border)] p-3">
                  <p className="mb-1 text-sm">
                    <strong>{g.value ?? '(vide)'}</strong> — {g.row_ids.length} lignes
                  </p>
                  {preview && preview.length > 0 && (
                    <div className="mb-2 overflow-x-auto rounded border border-[var(--border)]">
                      <table className="w-full min-w-max text-xs">
                        <thead>
                          <tr className="bg-[var(--muted-bg)] text-left">
                            {Object.keys(preview[0])
                              .slice(0, PREVIEW_COLS_MAX)
                              .map((c) => (
                                <th key={c} className="whitespace-nowrap px-2 py-1 font-medium">
                                  {c}
                                </th>
                              ))}
                          </tr>
                        </thead>
                        <tbody>
                          {preview.map((row, i) => (
                            <tr key={i} className="border-t border-[var(--border)]">
                              {Object.keys(preview[0])
                                .slice(0, PREVIEW_COLS_MAX)
                                .map((c) => (
                                  <td key={c} className="whitespace-nowrap px-2 py-1">
                                    {row[c] == null ? '' : String(row[c])}
                                  </td>
                                ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <label className="mb-1 block text-xs text-[var(--muted)]">Ligne à conserver</label>
                  <select
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm sm:w-auto"
                    value={groupChoices[key] ?? g.suggested_keep_id}
                    onChange={(e) => setGroupChoices((prev) => ({ ...prev, [key]: e.target.value }))}
                  >
                    {g.row_ids.map((id, i) => (
                      <option key={id} value={id}>
                        {preview && preview[i]
                          ? `Ligne ${i + 1} : ${Object.values(preview[i])
                              .filter((v) => v != null && v !== '')
                              .slice(0, 3)
                              .join(' | ')}`
                          : `Ligne ${i + 1}${id === g.suggested_keep_id ? ' (la plus complète)' : ''}`}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })}

            {!dedupeConfirming ? (
              <div>
                <Button onClick={() => setDedupeConfirming(true)}>
                  ✅ Appliquer la sélection ({dupAnalysis.group_count} groupe(s))
                </Button>
              </div>
            ) : (
              <div className="rounded-md border border-[var(--danger)] p-3">
                <p className="text-sm text-[var(--danger)]">
                  ⚠️ Suppression définitive : contrairement à l'ancienne version, cette suppression
                  ne peut plus être annulée une fois confirmée (le staging est modifié directement en
                  base). {dupAnalysis.duplicate_row_count - dupAnalysis.group_count} ligne(s) seront
                  supprimées, une par groupe étant conservée.
                </p>
                <div className="mt-2 flex gap-2">
                  <Button variant="danger" onClick={() => void handleApplyDedupe('manual')} disabled={dedupeApplying}>
                    {dedupeApplying ? 'Suppression…' : 'Confirmer la suppression définitive'}
                  </Button>
                  <Button variant="secondary" onClick={() => setDedupeConfirming(false)} disabled={dedupeApplying}>
                    Annuler
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {dupAnalysis && dupAnalysis.group_count > dupAnalysis.group_threshold && (
          <div className="mt-3 flex flex-col gap-3">
            <p className="text-sm text-[var(--danger)]">
              ⚠️ {dupAnalysis.group_count} groupes de doublons détectés : au-delà de la limite de{' '}
              {dupAnalysis.group_threshold} groupes pour la revue manuelle. Choisis une règle automatique
              appliquée à tous les groupes :
            </p>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2">
                <input type="radio" checked={keepRule === 'first'} onChange={() => setKeepRule('first')} />
                La première ligne importée
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" checked={keepRule === 'complete'} onChange={() => setKeepRule('complete')} />
                La ligne la plus complète (le moins de champs vides)
              </label>
            </div>

            {!dedupeConfirming ? (
              <div>
                <Button variant="danger" onClick={() => setDedupeConfirming(true)}>
                  🗑️ Supprimer les doublons sur '{dupCol}'
                </Button>
              </div>
            ) : (
              <div className="rounded-md border border-[var(--danger)] p-3">
                <p className="text-sm text-[var(--danger)]">
                  ⚠️ Suppression définitive et non annulable : {dupAnalysis.duplicate_row_count} ligne(s)
                  concernée(s) par des doublons, la règle choisie s'applique à TOUS les groupes.
                </p>
                <div className="mt-2 flex gap-2">
                  <Button variant="danger" onClick={() => void handleApplyDedupe('rule')} disabled={dedupeApplying}>
                    {dedupeApplying ? 'Suppression…' : 'Confirmer la suppression définitive'}
                  </Button>
                  <Button variant="secondary" onClick={() => setDedupeConfirming(false)} disabled={dedupeApplying}>
                    Annuler
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}

        {dedupeError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {dedupeError}</p>}
      </div>
    </div>
  )
}
