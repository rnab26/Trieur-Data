import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  ApiError,
  PIPELINE_UNASSIGNED,
  applyPipelineMapping,
  createPipelineSession,
  suggestPipelineMapping,
  type PipelineMappingResult,
  type PipelineSessionCreated,
} from '@/lib/api'

const PREVIEW_COLS_MAX = 8

// Onglet 2 -- mirroir de views/tab2_import_mapping.py : import du fichier,
// résumé (lignes/colonnes), assignation des colonnes source vers les
// colonnes maîtres (auto puis ajustable), construction de la base.
//
// Écarts volontaires par rapport au Python, dictés par le contrat API déjà
// en place (api/main.py, section "Pipeline Trieur de Data") :
//   - UN seul fichier par session (pas de multi-fichiers ni Google Sheets) --
//     POST .../pipeline/sessions ne prend qu'un `file`. Un fichier
//     multi-onglets reste supporté (fusionné en une seule session).
//   - Import PDF (relevés SEPA) supporté par le même endpoint (voir
//     api/main.py:_parse_pipeline_file), donc proposé ici aussi.
//   - Le mapping est GLOBAL à la session (pas par onglet source) -- déjà
//     le choix du backend, documenté dans api/main.py.
export function Tab2ImportMapping({
  orgId,
  masterColumns,
  masterColumnsError,
  session,
  onSessionCreated,
  onMapped,
  onResetSession,
  mappingResult,
}: {
  orgId: string
  masterColumns: string[] | null
  masterColumnsError: string | null
  session: PipelineSessionCreated | null
  onSessionCreated: (session: PipelineSessionCreated) => void
  onMapped: (result: PipelineMappingResult, mapping: Record<string, string>) => void
  onResetSession: () => void
  mappingResult: PipelineMappingResult | null
}) {
  const [uploading, setUploading] = useState(false)
  const [uploadElapsedSec, setUploadElapsedSec] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})

  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)

  async function handleFileChange(file: File | null) {
    if (!file) return
    setUploading(true)
    setUploadElapsedSec(0)
    setUploadError(null)
    setBuildError(null)
    // La création de session lit/écrit le fichier ENTIER de façon
    // synchrone côté serveur -- pas de vraie progression connue à
    // l'avance. Un chrono texte suffit tant que l'attente reste de
    // l'ordre de quelques secondes (voir mesure PROJECT_LOG.md).
    const startedAt = Date.now()
    const interval = window.setInterval(() => {
      setUploadElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    try {
      const data = await createPipelineSession(orgId, file)
      onSessionCreated(data)
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
    } catch (err) {
      setSuggestError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSuggestLoading(false)
    }
  }

  async function handleAutoAssign() {
    if (!session) return
    await loadSuggestion(session.session_id)
  }

  async function handleBuild() {
    if (!session) return
    setBuilding(true)
    setBuildError(null)
    try {
      const data = await applyPipelineMapping(orgId, session.session_id, mapping)
      onMapped(data, mapping)
    } catch (err) {
      setBuildError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBuilding(false)
    }
  }

  function reset() {
    onResetSession()
    setMapping({})
    setUploadError(null)
    setSuggestError(null)
    setBuildError(null)
  }

  const assignedCount = Object.values(mapping).filter((m) => m && m !== PIPELINE_UNASSIGNED).length

  // Le backend garde la PREMIÈRE valeur non vide quand deux colonnes
  // source sont mappées sur la MÊME colonne maître (voir
  // api/pipeline_mapping.py:merge_mapped_row) -- ce n'est donc pas une
  // perte silencieuse comme redouté par une revue précédente, mais on
  // avertit quand même : c'est rarement l'intention et souvent une
  // erreur de manipulation.
  const duplicateMasterCols = (() => {
    const counts = new Map<string, number>()
    for (const m of Object.values(mapping)) {
      if (!m || m === PIPELINE_UNASSIGNED) continue
      counts.set(m, (counts.get(m) ?? 0) + 1)
    }
    return [...counts.entries()].filter(([, n]) => n > 1).map(([col]) => col)
  })()

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">Importer vos fichiers Excel, CSV ou PDF</h2>

      {!session && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--muted)]">
            Déposez un fichier Excel, CSV ou PDF (relevé de prélèvements). Le fichier n'est pas
            encore écrit définitivement : cette session reste temporaire (24h) jusqu'à la
            construction de la base ci-dessous.
          </p>
          <input
            type="file"
            accept=".csv,.xlsx,.xls,.pdf"
            onChange={(e) => void handleFileChange(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <p className="text-xs text-[var(--muted)]">
            💡 Pour de très gros volumes (plusieurs millions de lignes), le <strong>CSV</strong> est
            bien plus rapide et léger que le .xlsx.
          </p>
          {uploading && (
            <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
              <span
                className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                aria-hidden="true"
              />
              Chargement des fichiers… ({uploadElapsedSec}s)
              {uploadElapsedSec >= 8 && ' -- un gros fichier peut prendre encore quelques instants.'}
            </p>
          )}
          {uploadError && <p className="text-sm text-[var(--danger)]">❌ Erreur : {uploadError}</p>}
        </div>
      )}

      {session && !mappingResult && (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-[var(--success,#16a34a)]">
            ✅ {session.row_count} ligne(s) détectée(s) dans {session.columns.length} colonne(s).
          </p>
          {session.unknown_columns.length > 0 && (
            <p className="text-sm text-[var(--muted)]">
              Colonne(s) inconnue(s) des colonnes maîtres : {session.unknown_columns.join(', ')} --
              mappe-les ci-dessous ou laisse "(non assigné)" pour les ignorer.
            </p>
          )}

          {session.preview_rows.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
              <table className="w-full min-w-max text-sm">
                <thead>
                  <tr className="bg-[var(--muted-bg)] text-left">
                    {session.columns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                      <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                        {c}
                      </th>
                    ))}
                    {session.columns.length > PREVIEW_COLS_MAX && (
                      <th className="px-3 py-2 font-medium text-[var(--muted)]">…</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {session.preview_rows.slice(0, 6).map((row, i) => (
                    <tr key={i} className="border-t border-[var(--border)]">
                      {session.columns.slice(0, PREVIEW_COLS_MAX).map((c) => (
                        <td key={c} className="whitespace-nowrap px-3 py-2">
                          {row[c] == null ? '' : String(row[c])}
                        </td>
                      ))}
                      {session.columns.length > PREVIEW_COLS_MAX && (
                        <td className="px-3 py-2 text-[var(--muted)]">…</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="border-t border-[var(--border)] pt-4">
            <h3 className="mb-2 text-base font-semibold">Assignation des colonnes</h3>
            {masterColumnsError && (
              <p className="mb-2 text-sm text-[var(--danger)]">
                Impossible de charger les colonnes maîtres : {masterColumnsError}
              </p>
            )}
            {masterColumns && masterColumns.length === 0 && !masterColumnsError && (
              <p className="mb-2 text-sm text-[var(--muted)]">
                Aucune colonne maître définie pour cet environnement -- va d'abord en créer dans
                l'onglet "1. Colonnes maîtres", sinon tout restera "(non assigné)".
              </p>
            )}

            <Button variant="secondary" onClick={() => void handleAutoAssign()} disabled={suggestLoading}>
              🚀 Auto-assigner
            </Button>

            {suggestLoading && (
              <p className="mt-2 text-sm text-[var(--muted)]">Suggestion automatique du mapping…</p>
            )}
            {suggestError && (
              <p className="mt-2 text-sm text-[var(--danger)]">
                Erreur de suggestion : {suggestError} -- tu peux mapper manuellement ci-dessous.
              </p>
            )}

            {!suggestLoading && (
              <div className="mt-3 flex flex-col gap-2">
                <p className="text-xs text-[var(--muted)]">
                  Colonne maître assignée à chaque colonne source du fichier importé.
                </p>
                {session.columns.map((col) => (
                  <div
                    key={col}
                    className="flex flex-col gap-1 rounded-md border border-[var(--border)] p-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <span className="text-sm font-medium">{col}</span>
                    <select
                      value={mapping[col] ?? PIPELINE_UNASSIGNED}
                      onChange={(e) => setMapping((prev) => ({ ...prev, [col]: e.target.value }))}
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
              ⚠️ {duplicateMasterCols.length === 1 ? 'Colonne maître choisie' : 'Colonnes maîtres choisies'}{' '}
              plusieurs fois : {duplicateMasterCols.join(', ')} -- seule la première colonne source
              non vide sera gardée pour chacune. Vérifie que c'est bien voulu avant de construire.
            </p>
          )}

          {assignedCount === 0 && !suggestLoading && (
            <p className="text-sm text-[var(--muted)]">
              ⚠️ Veuillez assigner au moins une colonne maître avant de construire la base.
            </p>
          )}

          {buildError && <p className="text-sm text-[var(--danger)]">❌ Erreur : {buildError}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void handleBuild()} disabled={assignedCount === 0 || building}>
              {building ? 'Construction…' : '✅ Construire la base de travail'}
            </Button>
            <Button variant="secondary" onClick={reset} disabled={building}>
              Annuler
            </Button>
          </div>
        </div>
      )}

      {session && mappingResult && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--success,#16a34a)]">
            ✅ Base construite : {mappingResult.n_rows_updated} ligne(s) fusionnée(s).
          </p>

          {mappingResult.iban_warnings.length > 0 && (
            <div className="rounded-md border border-[var(--danger)] p-3">
              <p className="text-sm text-[var(--danger)]">
                ⚠️{' '}
                {mappingResult.iban_warnings.reduce((n, w) => n + w.n_invalid, 0)} IBAN(s) avec un
                checksum invalide détecté(s) sur{' '}
                {mappingResult.iban_warnings.map((w) => `${w.column} (${w.n_invalid})`).join(', ')}.
                Rien n'est supprimé automatiquement, mais cela indique souvent une erreur de saisie
                ou un caractère mal reconnu par l'OCR d'un PDF -- à vérifier avant l'export final.
              </p>
            </div>
          )}

          <p className="text-sm text-[var(--muted)]">
            Passe à l'onglet "3. Filtrage &amp; Dedup" pour filtrer et dédoublonner, ou directement
            à "4. Export".
          </p>

          <div>
            <Button variant="secondary" onClick={reset}>
              Importer un autre fichier
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
