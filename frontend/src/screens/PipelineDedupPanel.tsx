import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  ApiError,
  activatePipelineDedup,
  activatePipelineDedupManual,
  clearPipelineDedup,
  previewPipelineDedup,
  type FilterGroup,
  type PipelineDedupManualGroup,
  type PipelineDedupResult,
} from '@/lib/api'

type DedupConfig = { column: string; keep: string } | { column: string; mode: 'manual'; keep_indices: number[] }

function rowLabel(index: number, data: Record<string, unknown>): string {
  const preview = Object.values(data)
    .filter((v) => v !== null && v !== undefined && String(v).trim() !== '')
    .slice(0, 3)
    .map((v) => String(v))
    .join(' | ')
  return `Ligne ${index} : ${preview}`
}

// Dédoublonnage -- copie conforme de views/tab3_filtrage_dedup.py :
// détection sur une colonne, puis soit une revue MANUELLE groupe par
// groupe (<= DEDUP_GROUP_THRESHOLD groupes -- choix de la ligne à
// garder par groupe, présélection = la plus complète), soit une règle
// GLOBALE (première/plus complète) au-delà. Reste actif (y compris à
// l'export) jusqu'à annulation explicite.
export function PipelineDedupPanel({
  orgId,
  sessionId,
  columns,
  filterGroups,
  activeDedup,
  onDedupChanged,
}: {
  orgId: string
  sessionId: string
  columns: string[]
  filterGroups: FilterGroup[]
  activeDedup: DedupConfig | null
  onDedupChanged: (config: DedupConfig | null) => void
}) {
  const [column, setColumn] = useState(activeDedup?.column ?? '')
  const [keepRule, setKeepRule] = useState<'first' | 'complete'>('first')

  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [nGroups, setNGroups] = useState<number | null>(null)
  const [nRows, setNRows] = useState<number | null>(null)
  const [manualGroups, setManualGroups] = useState<PipelineDedupManualGroup[] | null>(null)
  const [keepSelections, setKeepSelections] = useState<number[]>([])

  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applied, setApplied] = useState<PipelineDedupResult | null>(null)

  const [clearing, setClearing] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  function resetPreview() {
    setNGroups(null)
    setNRows(null)
    setManualGroups(null)
    setKeepSelections([])
    setApplied(null)
  }

  async function handleDetect() {
    if (!column) return
    setPreviewLoading(true)
    setPreviewError(null)
    resetPreview()
    try {
      const data = await previewPipelineDedup(orgId, sessionId, { column, keep: keepRule, filterGroups })
      setNGroups(data.n_duplicate_groups)
      setNRows(data.n_duplicate_rows)
      if (data.manual_review_available) {
        const groups = data.groups as PipelineDedupManualGroup[]
        setManualGroups(groups)
        setKeepSelections(groups.map((g) => g.default_keep_index))
      }
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleApplyManual() {
    if (!column) return
    setApplying(true)
    setApplyError(null)
    try {
      const data = await activatePipelineDedupManual(orgId, sessionId, { column, keepIndices: keepSelections, filterGroups })
      setApplied(data)
      onDedupChanged(data.dedup_config as DedupConfig)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setApplying(false)
    }
  }

  async function handleApplyRule() {
    if (!column) return
    setApplying(true)
    setApplyError(null)
    try {
      const data = await activatePipelineDedup(orgId, sessionId, { column, keep: keepRule, filterGroups })
      setApplied(data)
      onDedupChanged(data.dedup_config as DedupConfig)
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setApplying(false)
    }
  }

  async function handleClear() {
    setClearing(true)
    setClearError(null)
    try {
      await clearPipelineDedup(orgId, sessionId)
      onDedupChanged(null)
      resetPreview()
      setColumn('')
    } catch (err) {
      setClearError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setClearing(false)
    }
  }

  return (
    <details className="rounded-md border border-[var(--border)] p-3" open={!!activeDedup}>
      <summary className="cursor-pointer text-sm font-medium">
        🧹 Dédoublonnage {activeDedup ? `(actif sur "${activeDedup.column}")` : ''}
      </summary>
      <p className="mt-2 text-xs text-[var(--muted)]">
        Détecte les lignes en double sur une colonne, dans le résultat déjà filtré ci-dessus. Reste
        actif (y compris à l'export) jusqu'à ce que tu l'annules.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
          value={column}
          onChange={(e) => {
            setColumn(e.target.value)
            resetPreview()
          }}
        >
          <option value="">Choisir une colonne…</option>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <Button variant="secondary" onClick={() => void handleDetect()} disabled={!column || previewLoading}>
          {previewLoading ? 'Analyse…' : `🔎 Analyser les doublons${column ? ` sur "${column}"` : ''}`}
        </Button>
      </div>

      {previewError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {previewError}</p>}

      {nGroups === 0 && <p className="mt-3 text-sm text-[var(--muted)]">Aucun doublon détecté sur "{column}".</p>}

      {/* Revue manuelle groupe par groupe (<= 50 groupes) -- copie conforme */}
      {manualGroups && manualGroups.length > 0 && !applied && (
        <div className="mt-3 flex flex-col gap-3">
          <p className="text-sm">
            <strong>{manualGroups.length} groupe(s) de doublons</strong> ({nRows} lignes) — la ligne la plus
            complète est présélectionnée ; corrige si besoin.
          </p>
          {manualGroups.map((g, gi) => (
            <div key={gi} className="rounded-md border border-[var(--border)] p-2">
              <p className="text-xs text-[var(--muted)]">
                <strong>{String(g.value)}</strong> — {g.rows.length} lignes
              </p>
              <div className="mt-1 overflow-x-auto">
                <table className="w-full min-w-max text-xs">
                  <tbody>
                    {g.rows.map((r) => (
                      <tr key={r.index} className={r.index === keepSelections[gi] ? 'bg-[var(--muted-bg)]' : ''}>
                        {Object.values(r.data)
                          .slice(0, 6)
                          .map((v, vi) => (
                            <td key={vi} className="whitespace-nowrap px-2 py-1">
                              {v == null ? '' : String(v)}
                            </td>
                          ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <select
                className="mt-2 w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs"
                value={keepSelections[gi] ?? g.default_keep_index}
                onChange={(e) =>
                  setKeepSelections((prev) => prev.map((v, i) => (i === gi ? Number(e.target.value) : v)))
                }
              >
                {g.rows.map((r) => (
                  <option key={r.index} value={r.index}>
                    {rowLabel(r.index, r.data)}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <div>
            <Button onClick={() => void handleApplyManual()} disabled={applying}>
              {applying ? 'Application…' : `✅ Appliquer la sélection (${manualGroups.length} groupe(s))`}
            </Button>
          </div>
        </div>
      )}

      {/* Au-delà du seuil de revue manuelle -- règle globale */}
      {nGroups !== null && nGroups > 0 && !manualGroups && !applied && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-sm text-[var(--danger)]">
            ⚠️ {nGroups} groupes de doublons détectés : au-delà de la limite pour la revue manuelle. Choisis une
            règle automatique appliquée à tous les groupes :
          </p>
          <div className="flex items-center gap-4 text-sm">
            <label className="flex items-center gap-1">
              <input type="radio" checked={keepRule === 'first'} onChange={() => setKeepRule('first')} />
              La première ligne importée
            </label>
            <label className="flex items-center gap-1">
              <input type="radio" checked={keepRule === 'complete'} onChange={() => setKeepRule('complete')} />
              La ligne la plus complète
            </label>
          </div>
          <div>
            <Button onClick={() => void handleApplyRule()} disabled={applying}>
              {applying ? 'Suppression…' : `🗑️ Supprimer les doublons sur "${column}"`}
            </Button>
          </div>
        </div>
      )}

      {applyError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {applyError}</p>}

      {applied && (
        <p className="mt-3 text-sm text-[var(--success,#16a34a)]">
          Dédoublonnage activé : {applied.n_removed} ligne(s) retirée(s) ({applied.n_after}/
          {applied.n_before} conservée(s)).
        </p>
      )}

      {activeDedup && (
        <div className="mt-3">
          <Button variant="secondary" onClick={() => void handleClear()} disabled={clearing}>
            {clearing ? 'Annulation…' : '↩️ Annuler le dédoublonnage'}
          </Button>
          {clearError && <p className="mt-1 text-sm text-[var(--danger)]">Erreur : {clearError}</p>}
        </div>
      )}
    </details>
  )
}
