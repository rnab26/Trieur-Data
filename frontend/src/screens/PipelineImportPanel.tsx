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
} from '@/lib/api'
import { PipelineMappingGrid } from './PipelineMappingGrid'

// Import + mapping -- mirroir des onglets 1-2 Streamlit
// (views/tab2_import_mapping.py) réunis dans le même écran : import
// multi-fichiers + Google Sheets DANS LE MÊME BATCH, puis mapping des
// colonnes détectées vers les colonnes maîtres, pré-rempli par
// l'auto-assignation (+ mémoire de mapping par forme de fichier -- voir
// api/main.py:apply_pipeline_mapping). "Construire" applique le mapping
// et fait passer la session au statut "mapped" -- les onglets Filtrer/
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
  const [rememberedForShape, setRememberedForShape] = useState(false)
  const [mapping, setMapping] = useState<Record<string, string>>({})

  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  function reset() {
    setFiles([])
    setGoogleSheetUrl('')
    setUploadError(null)
    setSession(null)
    setSuggestError(null)
    setRememberedForShape(false)
    setMapping({})
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
      await loadSuggestion(data.session_id)
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      window.clearInterval(interval)
      setUploading(false)
    }
  }

  async function loadSuggestion(sessionId: string) {
    setSuggestLoading(true)
    setSuggestError(null)
    try {
      const data = await suggestPipelineMapping(orgId, sessionId)
      setMapping(data.suggested_mapping)
      setRememberedForShape(data.remembered_for_shape)
    } catch (err) {
      setSuggestError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSuggestLoading(false)
    }
  }

  async function handleBuild() {
    if (!session) return
    setBuilding(true)
    setBuildError(null)
    try {
      const data = await applyPipelineMapping(orgId, session.session_id, mapping)
      onBuilt(session, data)
    } catch (err) {
      setBuildError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBuilding(false)
    }
  }

  const assignedCount = Object.values(mapping).filter((m) => m && m !== PIPELINE_UNASSIGNED).length

  // Le backend garde la DERNIÈRE valeur quand deux colonnes source sont
  // mappées sur la MÊME colonne maître -- on bloque "Construire" tant
  // qu'un même choix est utilisé deux fois, comme avant (revue PR #24).
  const duplicateMasterCols = (() => {
    const counts = new Map<string, number>()
    for (const m of Object.values(mapping)) {
      if (!m || m === PIPELINE_UNASSIGNED) continue
      counts.set(m, (counts.get(m) ?? 0) + 1)
    }
    return [...counts.entries()].filter(([, n]) => n > 1).map(([col]) => col)
  })()

  const canBuild = assignedCount > 0 && duplicateMasterCols.length === 0 && !building

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
          <div>
            <p className="text-sm">
              {session.row_count} ligne(s) détectée(s) dans{' '}
              <span className="font-medium">{session.columns.length}</span> colonne(s).
            </p>
            {session.unknown_columns.length > 0 && (
              <p className="mt-1 text-sm text-[var(--muted)]">
                Colonne(s) inconnue(s) des colonnes maîtres :{' '}
                <span className="font-medium">{session.unknown_columns.join(', ')}</span> -- mappe-les
                ci-dessous ou laisse "(non assigné)" pour les ignorer. Ajoute-les d'abord dans
                l'onglet "Colonnes maîtres" si tu veux les garder.
              </p>
            )}
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">Mapping des colonnes</h3>
              <Button
                variant="secondary"
                onClick={() => void loadSuggestion(session.session_id)}
                disabled={suggestLoading}
              >
                🚀 Auto-assigner toutes les colonnes
              </Button>
            </div>

            {rememberedForShape && !suggestLoading && (
              <p className="mb-2 text-xs text-[var(--muted)]">
                Ce type de fichier a déjà été mappé auparavant -- le mapping mémorisé a été
                réappliqué automatiquement.
              </p>
            )}
            {masterColumns.length === 0 && (
              <p className="mb-2 text-sm text-[var(--muted)]">
                Aucune colonne maître définie pour cet environnement -- va d'abord en créer dans
                l'onglet "Colonnes maîtres", sinon tout restera "(non assigné)".
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
              <PipelineMappingGrid
                columns={session.columns}
                previewRows={session.preview_rows}
                masterColumns={masterColumns}
                mapping={mapping}
                onMappingChange={(col, master) => setMapping((prev) => ({ ...prev, [col]: master }))}
                duplicateMasterCols={duplicateMasterCols}
              />
            )}
          </div>

          {duplicateMasterCols.length > 0 && (
            <p className="text-sm text-[var(--danger)]">
              {duplicateMasterCols.length === 1 ? 'Colonne maître choisie' : 'Colonnes maîtres choisies'}{' '}
              plusieurs fois : {duplicateMasterCols.join(', ')} -- seule la dernière colonne source
              assignée serait gardée, les autres seraient perdues. Choisis une colonne maître
              différente pour chacune avant de construire.
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
    </div>
  )
}
