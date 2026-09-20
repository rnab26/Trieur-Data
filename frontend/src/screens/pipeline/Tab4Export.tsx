import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, exportPipelineSessionRows, listPipelineSessionRows, type ColFilters, type PipelineFilterGroup } from '@/lib/api'

const EXCEL_MAX_ROWS = 1_048_576

// Onglet 4 -- mirroir de views/tab4_export.py : ordre/sélection des
// colonnes à l'export, nom de fichier personnalisable, export CSV/Excel.
//
// Écarts volontaires par rapport au Python :
//   - Pas de bouton "Préparer" séparé du téléchargement : le backend
//     (StreamingResponse, voir api/main.py:export_pipeline_session_rows)
//     génère le fichier à la demande sans le lenteur qui justifiait la
//     mise en cache manuelle côté Streamlit (Excel de plusieurs millions
//     de lignes) -- un seul clic "Exporter" suffit.
//   - Pas de presets d'export nommés (ordre/sélection sauvegardés) : pas
//     d'endpoint backend pour les persister côté pipeline (à la
//     différence des colonnes maîtres/jeux personnels) -- non ajouté ici
//     pour rester dans le contrat d'API déjà en place.
//   - Pas de section "Enregistrer dans la base de données (CRM)" : hors
//     périmètre de ce chantier (écran Base de données exclu).
export function Tab4Export({
  orgId,
  sessionId,
  sessionMapped,
  search,
  colFilters,
  apiGroups,
  refreshKey,
  colOrder,
  setColOrder,
  excludedCols,
  toggleColIncluded,
  moveColUp,
  moveColDown,
  filenameBase,
  setFilenameBase,
}: {
  orgId: string
  sessionId: string | null
  sessionMapped: boolean
  search: string
  colFilters: ColFilters
  apiGroups: PipelineFilterGroup[]
  refreshKey: number
  colOrder: string[]
  setColOrder: Dispatch<SetStateAction<string[]>>
  excludedCols: Set<string>
  toggleColIncluded: (col: string) => void
  moveColUp: (i: number) => void
  moveColDown: (i: number) => void
  filenameBase: string
  setFilenameBase: (v: string) => void
}) {
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [rowCount, setRowCount] = useState(0)

  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Recharge juste le compte + les colonnes détectées (1 ligne suffit) à
  // chaque changement de filtre -- la base réelle reste en staging côté
  // serveur, exportée à la demande, jamais recopiée ici.
  useEffect(() => {
    if (!sessionMapped || !sessionId) return
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    listPipelineSessionRows(orgId, sessionId, { page: 1, pageSize: 1, search, colFilters, groups: apiGroups })
      .then((data) => {
        if (cancelled) return
        setRowCount(data.count)
        const cols: string[] = []
        for (const row of data.rows) {
          for (const key of Object.keys(row)) {
            if (!cols.includes(key)) cols.push(key)
          }
        }
        setColOrder((prev) => {
          const known = new Set(prev)
          const stillPresent = prev.filter((c) => cols.includes(c))
          const newOnes = cols.filter((c) => !known.has(c))
          if (newOnes.length === 0 && stillPresent.length === prev.length) return prev
          return [...stillPresent, ...newOnes]
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, sessionId, sessionMapped, search, JSON.stringify(colFilters), JSON.stringify(apiGroups), refreshKey])

  async function handleExport(format: 'csv' | 'xlsx') {
    if (!sessionId) return
    setExporting(format)
    setExportError(null)
    try {
      const selectedColumns = colOrder.filter((c) => !excludedCols.has(c))
      await exportPipelineSessionRows(orgId, sessionId, {
        format,
        search,
        colFilters,
        groups: apiGroups,
        columns: selectedColumns.length > 0 ? selectedColumns : undefined,
        filenameBase,
      })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setExporting(null)
    }
  }

  if (!sessionMapped) {
    return (
      <div className="flex flex-col gap-3">
        <h2 className="text-base font-semibold">Exporter le résultat filtré</h2>
        <p className="text-sm text-[var(--muted)]">
          ℹ️ Importez, mappez et (si besoin) filtrez dans les onglets précédents avant d'exporter.
        </p>
      </div>
    )
  }

  const includedCount = colOrder.length - excludedCols.size
  const cleanName = filenameBase.trim().replace(/[\\/:*?"<>|]+/g, '_') || 'export'

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">Exporter le résultat filtré</h2>

      {loadError && <p className="text-sm text-[var(--danger)]">Erreur : {loadError}</p>}
      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}

      {!loading && rowCount === 0 && (
        <p className="text-sm text-[var(--danger)]">
          ❌ Impossible d'exporter : aucune donnée à exporter avec le filtre actuel.
        </p>
      )}

      {rowCount > 0 && (
        <>
          <p className="text-sm">{rowCount} ligne(s) prête(s) à l'export.</p>

          {colOrder.length > 0 && (
            <details className="rounded-md border border-[var(--border)] p-3" open={false}>
              <summary className="cursor-pointer text-sm font-medium">
                🔀 Ordre et sélection des colonnes à l'export ({includedCount}/{colOrder.length} incluse(s))
              </summary>
              <p className="mt-2 text-xs text-[var(--muted)]">
                Décoche une colonne pour l'exclure de l'export, utilise les flèches pour changer son ordre
                dans le fichier généré (équivalent du glisser-déposer de l'ancienne version).
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
                    <Button variant="secondary" onClick={() => moveColDown(i)} disabled={i === colOrder.length - 1}>
                      ⬇️
                    </Button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {colOrder.length > 0 && includedCount === 0 && (
            <p className="text-sm text-[var(--danger)]">
              ⚠️ Aucune colonne sélectionnée : inclus-en au moins une pour exporter.
            </p>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium" htmlFor="export-filename">
              Nom du fichier (sans extension)
            </label>
            <Input
              id="export-filename"
              className="max-w-xs"
              value={filenameBase}
              onChange={(e) => setFilenameBase(e.target.value)}
            />
            <p className="mt-1 text-xs text-[var(--muted)]">
              Fichiers générés : <strong>{cleanName}.csv</strong> / <strong>{cleanName}.xlsx</strong>
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-sm font-medium">Export CSV — recommandé (rapide, sans limite)</p>
              <Button
                onClick={() => void handleExport('csv')}
                disabled={exporting !== null || includedCount === 0}
              >
                {exporting === 'csv' ? 'Préparation…' : '💾 Télécharger CSV'}
              </Button>
            </div>
            <div>
              <p className="mb-1 text-sm font-medium">Export Excel</p>
              {rowCount > EXCEL_MAX_ROWS ? (
                <p className="text-sm text-[var(--muted)]">
                  ℹ️ {rowCount.toLocaleString('fr-FR')} lignes : au-delà de la limite d'Excel (~
                  {EXCEL_MAX_ROWS.toLocaleString('fr-FR')} par onglet). Utilise l'export CSV.
                </p>
              ) : (
                <>
                  {rowCount > 100_000 && (
                    <p className="mb-1 text-xs text-[var(--muted)]">
                      ⚠️ Excel est lent au-delà de ~100 000 lignes (~1 min/million). Le CSV est conseillé.
                    </p>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() => void handleExport('xlsx')}
                    disabled={exporting !== null || includedCount === 0}
                  >
                    {exporting === 'xlsx' ? 'Préparation…' : '💾 Télécharger Excel'}
                  </Button>
                </>
              )}
            </div>
          </div>

          {exportError && <p className="text-sm text-[var(--danger)]">Erreur d'export : {exportError}</p>}

          <p className="text-xs text-[var(--muted)]">
            ℹ️ Les fichiers sont encodés en UTF-8. Pour les très gros volumes, préfère le CSV.
          </p>
        </>
      )}
    </div>
  )
}
