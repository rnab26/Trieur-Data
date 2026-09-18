import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  PIPELINE_UNASSIGNED,
  applyPipelineMapping,
  createPipelineSession,
  suggestPipelineMapping,
  type PipelineMappingResult,
  type PipelineSessionCreated,
  type PipelineSheetSuggestion,
} from '@/lib/api'
import { PipelineMappingGrid } from './PipelineMappingGrid'

// Import + mapping -- copie conforme de views/tab2_import_mapping.py :
// import multi-fichiers + Google Sheets DANS LE MÊME BATCH, puis mapping
// des colonnes détectées vers les colonnes maîtres PAR ONGLET (un
// fichier/une feuille = un onglet, mappé et fusionné séparément -- pas
// un mapping unique sur l'union de toutes les colonnes de tous les
// fichiers), pré-rempli par l'auto-assignation (+ mémoire de mapping
// par forme de fichier, propre à chaque onglet -- voir
// api/main.py:apply_pipeline_mapping). "Construire" fusionne les
// onglets inclus avec leur mapping respectif -- les onglets Filtrer/
// Exporter s'activent alors.
export function PipelineImportPanel({
  orgId,
  masterColumns,
  onBuilt,
}: {
  orgId: string
  masterColumns: string[]
  onBuilt: (session: PipelineSessionCreated, result: PipelineMappingResult) => void
}) {
  const [files, setFiles] = useState<File[]>([])
  const [googleSheetUrl, setGoogleSheetUrl] = useState('')

  const [uploading, setUploading] = useState(false)
  const [uploadElapsedSec, setUploadElapsedSec] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [session, setSession] = useState<PipelineSessionCreated | null>(null)

  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const [sheets, setSheets] = useState<PipelineSheetSuggestion[] | null>(null)
  const [mappingBySheet, setMappingBySheet] = useState<Record<string, Record<string, string>>>({})
  const [excludedSheets, setExcludedSheets] = useState<Set<string>>(new Set())

  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  function reset() {
    setFiles([])
    setGoogleSheetUrl('')
    setUploadError(null)
    setSession(null)
    setSuggestError(null)
    setSheets(null)
    setMappingBySheet({})
    setExcludedSheets(new Set())
    setBuildError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleImport() {
    if (files.length === 0 && !googleSheetUrl.trim()) return
    setUploading(true)
    setUploadElapsedSec(0)
    setUploadError(null)
    // Pas de progression réelle connue à l'avance côté serveur (lecture
    // synchrone du/des fichier(s) entier(s)) -- un chrono texte suffit,
    // même patron que ImportPanel/l'ancienne version de cet écran.
    const startedAt = Date.now()
    const interval = window.setInterval(() => {
      setUploadElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    try {
      const data = await createPipelineSession(orgId, files, googleSheetUrl.trim() || undefined)
      setSession(data)
      await loadSuggestion(data.session_id, true)
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      window.clearInterval(interval)
      setUploading(false)
    }
  }

  // Auto-assignation -- pour TOUS les onglets (bouton global, juste
  // après l'import) ou pour UN SEUL onglet ("🚀 Auto" de sa carte) --
  // copie conforme des deux boutons "Auto" de views/tab2_import_mapping.py.
  async function loadSuggestion(sessionId: string, all: true): Promise<void>
  async function loadSuggestion(sessionId: string, all: false, onlySheetKey: string): Promise<void>
  async function loadSuggestion(sessionId: string, all: boolean, onlySheetKey?: string) {
    setSuggestLoading(true)
    setSuggestError(null)
    try {
      const data = await suggestPipelineMapping(orgId, sessionId)
      setSheets(data.sheets)
      setMappingBySheet((prev) => {
        const next = { ...prev }
        for (const s of data.sheets) {
          if (all || s.sheet_key === onlySheetKey) next[s.sheet_key] = s.suggested_mapping
        }
        return next
      })
    } catch (err) {
      setSuggestError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSuggestLoading(false)
    }
  }

  function toggleSheetIncluded(sheetKey: string) {
    setExcludedSheets((prev) => {
      const next = new Set(prev)
      if (next.has(sheetKey)) next.delete(sheetKey)
      else next.add(sheetKey)
      return next
    })
  }

  async function handleBuild() {
    if (!session) return
    setBuilding(true)
    setBuildError(null)
    try {
      const data = await applyPipelineMapping(orgId, session.session_id, mappingBySheet, [...excludedSheets])
      onBuilt(session, data)
    } catch (err) {
      setBuildError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBuilding(false)
    }
  }

  const includedSheets = (sheets ?? []).filter((s) => !excludedSheets.has(s.sheet_key))
  const anyAssigned = includedSheets.some((s) =>
    Object.values(mappingBySheet[s.sheet_key] ?? {}).some((m) => m && m !== PIPELINE_UNASSIGNED),
  )
  const canBuild = anyAssigned && !building && includedSheets.length > 0

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Importer vos fichiers Excel, CSV ou Google Sheets</h2>
        <p className="text-sm text-[var(--muted)]">
          Plusieurs fichiers (Excel, CSV) et/ou un Google Sheets public en une seule fois -- rien
          n'est encore écrit dans la base : cette session reste temporaire (24h) jusqu'à
          confirmation du mapping ci-dessous.
        </p>
        <p className="mt-1 text-xs text-[var(--muted)]">
          Conseil : pour de très gros volumes, préfère un CSV à un .xlsx (lecture plus rapide).
        </p>
      </div>

      {!session && (
        <div className="flex flex-col gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="text-sm"
          />
          {files.length > 0 && (
            <p className="text-sm text-[var(--muted)]">
              {files.length} fichier(s) sélectionné(s) : {files.map((f) => f.name).join(', ')}
            </p>
          )}

          <div>
            <label htmlFor="pipeline-gsheet-url" className="mb-1 block text-sm text-[var(--muted)]">
              URL Google Sheets publique (optionnel, tous ses onglets seront importés avec les
              fichiers ci-dessus)
            </label>
            <Input
              id="pipeline-gsheet-url"
              placeholder="https://docs.google.com/spreadsheets/d/..."
              value={googleSheetUrl}
              onChange={(e) => setGoogleSheetUrl(e.target.value)}
              className="max-w-lg"
            />
          </div>

          <div>
            <Button
              onClick={() => void handleImport()}
              disabled={uploading || (files.length === 0 && !googleSheetUrl.trim())}
            >
              {uploading ? 'Import en cours…' : 'Importer'}
            </Button>
          </div>

          {uploading && (
            <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
              <span
                className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                aria-hidden="true"
              />
              Lecture et mise en attente du/des fichier(s)… ({uploadElapsedSec}s)
              {uploadElapsedSec >= 8 && ' -- un gros volume peut prendre encore quelques instants.'}
            </p>
          )}
          {uploadError && <p className="text-sm text-[var(--danger)]">Erreur : {uploadError}</p>}
        </div>
      )}

      {session && (
        <div className="flex flex-col gap-4">
          <p className="text-sm">
            {sheets ? sheets.length : '…'} onglet(s) détecté(s) — {includedSheets.length} inclus,{' '}
            {excludedSheets.size} exclu(s).
          </p>

          {masterColumns.length === 0 && (
            <p className="text-sm text-[var(--muted)]">
              Aucune colonne maître définie pour cet environnement -- va d'abord en créer dans
              l'onglet "Colonnes maîtres", sinon tout restera "(non assigné)".
            </p>
          )}

          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Assignation des colonnes</h3>
            <Button
              variant="secondary"
              onClick={() => void loadSuggestion(session.session_id, true)}
              disabled={suggestLoading}
            >
              🚀 Auto-assigner TOUS les onglets
            </Button>
          </div>

          {suggestLoading && <p className="text-sm text-[var(--muted)]">Suggestion automatique du mapping…</p>}
          {suggestError && (
            <p className="text-sm text-[var(--danger)]">
              Erreur de suggestion : {suggestError} -- tu peux mapper manuellement ci-dessous.
            </p>
          )}

          {!suggestLoading &&
            sheets?.map((sheet) => {
              const mapping = mappingBySheet[sheet.sheet_key] ?? {}
              const counts = new Map<string, number>()
              for (const m of Object.values(mapping)) {
                if (!m || m === PIPELINE_UNASSIGNED) continue
                counts.set(m, (counts.get(m) ?? 0) + 1)
              }
              const combinedMasterCols = [...counts.entries()].filter(([, n]) => n > 1).map(([col]) => col)
              const excluded = excludedSheets.has(sheet.sheet_key)

              return (
                <div key={sheet.sheet_key} className="rounded-md border border-[var(--border)] p-3">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <label className="flex items-center gap-2 text-sm font-medium">
                      <input type="checkbox" checked={!excluded} onChange={() => toggleSheetIncluded(sheet.sheet_key)} />
                      📄 {sheet.sheet_key}
                    </label>
                    <Button
                      variant="secondary"
                      onClick={() => void loadSuggestion(session.session_id, false, sheet.sheet_key)}
                      disabled={suggestLoading}
                    >
                      🚀 Auto
                    </Button>
                  </div>
                  <p className="mb-2 text-xs text-[var(--muted)]">
                    {sheet.row_count} ligne(s) · {sheet.columns.length} colonne(s) · {sheet.n_duplicates} doublon(s)
                    {sheet.remembered_for_shape && ' · mapping mémorisé réappliqué'}
                  </p>
                  {sheet.unknown_columns.length > 0 && (
                    <p className="mb-2 text-xs text-[var(--muted)]">
                      Colonne(s) inconnue(s) : <span className="font-medium">{sheet.unknown_columns.join(', ')}</span>
                    </p>
                  )}

                  <fieldset disabled={excluded} className={excluded ? 'opacity-50' : ''}>
                    <PipelineMappingGrid
                      columns={sheet.columns}
                      previewRows={sheet.preview_rows}
                      masterColumns={masterColumns}
                      mapping={mapping}
                      onMappingChange={(col, master) =>
                        setMappingBySheet((prev) => ({
                          ...prev,
                          [sheet.sheet_key]: { ...prev[sheet.sheet_key], [col]: master },
                        }))
                      }
                      duplicateMasterCols={combinedMasterCols}
                    />
                  </fieldset>

                  {combinedMasterCols.length > 0 && (
                    <p className="mt-2 text-xs text-[var(--muted)]">
                      {combinedMasterCols.join(', ')} : plusieurs colonnes source assignées -- seront combinées
                      en gardant la première valeur non vide.
                    </p>
                  )}
                </div>
              )
            })}

          {buildError && <p className="text-sm text-[var(--danger)]">Erreur : {buildError}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void handleBuild()} disabled={!canBuild}>
              {building ? 'Construction…' : '✅ Construire la base de travail fusionnée'}
            </Button>
            <Button variant="secondary" onClick={reset} disabled={building}>
              Annuler
            </Button>
            {!anyAssigned && !suggestLoading && (
              <span className="text-sm text-[var(--muted)]">
                Assigne au moins une colonne sur un onglet inclus pour construire.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
