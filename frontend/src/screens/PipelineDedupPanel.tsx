import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  ApiError,
  activatePipelineDedup,
  clearPipelineDedup,
  previewPipelineDedup,
  type ColFilters,
  type PipelineDedupResult,
} from '@/lib/api'

// Dédoublonnage -- mirroir de views/tab3_filtrage_dedup.py, MÉCANISME
// SÉPARÉ des filtres par colonne (opère sur le résultat déjà filtré par
// recherche/colonnes). Une fois activé, reste actif tant qu'il n'est pas
// explicitement annulé -- réappliqué à /rows ET /export (voir
// api/main.py:apply_pipeline_dedup) pour qu'un export ne "dé-déduplique"
// jamais silencieusement.
export function PipelineDedupPanel({
  orgId,
  sessionId,
  columns,
  search,
  colFilters,
  activeDedup,
  onDedupChanged,
}: {
  orgId: string
  sessionId: string
  columns: string[]
  search: string
  colFilters: ColFilters
  activeDedup: { column: string; keep: string } | null
  onDedupChanged: (config: { column: string; keep: string } | null) => void
}) {
  const [column, setColumn] = useState(activeDedup?.column ?? '')
  const [keep, setKeep] = useState<'first' | 'complete'>(
    (activeDedup?.keep as 'first' | 'complete') ?? 'first',
  )

  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{
    n_duplicate_groups: number
    n_duplicate_rows: number
    groups: { value: unknown; n_rows: number }[]
  } | null>(null)

  const [applying, setApplying] = useState(false)
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applied, setApplied] = useState<PipelineDedupResult | null>(null)

  const [clearing, setClearing] = useState(false)
  const [clearError, setClearError] = useState<string | null>(null)

  async function handlePreview() {
    if (!column) return
    setPreviewLoading(true)
    setPreviewError(null)
    setApplied(null)
    try {
      const data = await previewPipelineDedup(orgId, sessionId, { column, keep, search, colFilters })
      setPreview(data)
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleActivate() {
    if (!column) return
    setApplying(true)
    setApplyError(null)
    try {
      const data = await activatePipelineDedup(orgId, sessionId, { column, keep, search, colFilters })
      setApplied(data)
      onDedupChanged(data.dedup_config)
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
      setPreview(null)
      setApplied(null)
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
            setPreview(null)
            setApplied(null)
          }}
        >
          <option value="">Choisir une colonne…</option>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
          value={keep}
          onChange={(e) => setKeep(e.target.value as 'first' | 'complete')}
          title="Quelle ligne garder par groupe de doublons"
        >
          <option value="first">Garder la première ligne</option>
          <option value="complete">Garder la ligne la plus complète</option>
        </select>
        <Button variant="secondary" onClick={() => void handlePreview()} disabled={!column || previewLoading}>
          {previewLoading ? 'Analyse…' : 'Détecter les doublons'}
        </Button>
      </div>

      {previewError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {previewError}</p>}

      {preview && !applied && (
        <div className="mt-3 flex flex-col gap-2">
          {preview.n_duplicate_groups === 0 ? (
            <p className="text-sm text-[var(--muted)]">Aucun doublon détecté sur "{column}".</p>
          ) : (
            <>
              <p className="text-sm">
                {preview.n_duplicate_groups} groupe(s) de doublons, {preview.n_duplicate_rows} ligne(s)
                concernée(s) au total.
              </p>
              <ul className="max-h-40 overflow-y-auto text-xs text-[var(--muted)]">
                {preview.groups.slice(0, 20).map((g, i) => (
                  <li key={i}>
                    {String(g.value ?? '(vide)')} -- {g.n_rows} ligne(s)
                  </li>
                ))}
              </ul>
              <div>
                <Button onClick={() => void handleActivate()} disabled={applying}>
                  {applying ? 'Activation…' : 'Activer le dédoublonnage'}
                </Button>
              </div>
            </>
          )}
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
            {clearing ? 'Annulation…' : 'Annuler le dédoublonnage'}
          </Button>
          {clearError && <p className="mt-1 text-sm text-[var(--danger)]">Erreur : {clearError}</p>}
        </div>
      )}
    </details>
  )
}
