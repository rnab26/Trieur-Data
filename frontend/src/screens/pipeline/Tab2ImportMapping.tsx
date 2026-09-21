import { useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  ApiError,
  PIPELINE_UNASSIGNED,
  applyPipelineMapping,
  createPipelineSession,
  suggestPipelineMapping,
  type PipelineMappingBySheet,
  type PipelineMappingResult,
  type PipelineSessionCreated,
  type PipelineSheetSummary,
} from '@/lib/api'

const VOLUME_WARNING_THRESHOLD = 600_000

// Onglet 2 -- mirroir FIDÈLE de views/tab2_import_mapping.py (commit
// 635fcde) : import multi-fichiers/multi-onglets, choix des
// fichiers/onglets à inclure, mapping PAR ONGLET (une carte empilée par
// onglet actif, menus + aperçu alignés en grille), auto-assignation dès
// l'import + boutons Auto (global et par onglet), construction de la
// base fusionnée.
//
// Écarts volontaires par rapport au Python, dictés par le contrat API
// déjà en place (voir api/main.py, section "Pipeline Trieur de Data") :
//   - Pas de Google Sheets (URL publique) -- seuls Excel/CSV/PDF sont
//     supportés par POST .../pipeline/sessions.
//   - Pas de mémoire du mapping par "forme de fichier" (remembered
//     mappings / column_fingerprint, section [12] de l'original) :
//     demanderait un nouveau schéma DB non prévu pour ce chantier.
//     L'auto-assignation reste donc "sans mémoire" (toujours
//     auto_assign_columns_fast, jamais un mapping confirmé précédent).
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
  onMapped: (result: PipelineMappingResult) => void
  onResetSession: () => void
  mappingResult: PipelineMappingResult | null
}) {
  const [uploading, setUploading] = useState(false)
  const [uploadElapsedSec, setUploadElapsedSec] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [suggestLoading, setSuggestLoading] = useState<string | 'all' | null>(null)
  const [suggestError, setSuggestError] = useState<string | null>(null)

  // Mapping PAR ONGLET : sheet_key -> {colonne source: colonne maître}.
  const [mapping, setMapping] = useState<PipelineMappingBySheet>({})

  // [3] Onglets décochés par l'utilisateur -- un fichier décoché
  // décoche tous ses onglets. Par défaut (nouvel import), tout est inclus.
  const [excludedSheets, setExcludedSheets] = useState<Set<string>>(new Set())
  const [includeExpanderOpen, setIncludeExpanderOpen] = useState(false)

  const [building, setBuilding] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)

  function sheetFileName(sheetKey: string): string {
    const i = sheetKey.indexOf(' :: ')
    return i === -1 ? sheetKey : sheetKey.slice(0, i)
  }

  const sheetsByFile = useMemo(() => {
    const groups = new Map<string, PipelineSheetSummary[]>()
    for (const s of session?.sheets ?? []) {
      const file = sheetFileName(s.sheet_key)
      const arr = groups.get(file) ?? []
      arr.push(s)
      groups.set(file, arr)
    }
    return groups
  }, [session])

  const activeSheets = useMemo(
    () => (session?.sheets ?? []).filter((s) => !excludedSheets.has(s.sheet_key)),
    [session, excludedSheets],
  )

  // Même plafond que côté serveur (PIPELINE_MAX_UPLOAD_BYTES,
  // api/main.py) -- vérifié ICI avant même l'envoi, pour ne pas faire
  // attendre l'utilisateur sur un upload voué à échouer (un .xlsx trop
  // gros fait planter le serveur en mémoire, voir le message côté API).
  const MAX_UPLOAD_BYTES = 8 * 1024 * 1024

  async function handleFilesChange(files: File[]) {
    if (!files.length) return
    // Enregistré AVANT le contrôle de taille -- sinon un rejet affiche
    // encore l'ancienne sélection (noms/tailles d'un import précédent)
    // à côté du message d'erreur calculé pour la NOUVELLE sélection
    // refusée, ce qui ne correspond à rien de réel (revue Copilot, PR #28).
    setPendingFiles(files)
    const totalBytes = files.reduce((sum, f) => sum + f.size, 0)
    if (totalBytes > MAX_UPLOAD_BYTES) {
      setUploadError(
        `Fichier(s) trop volumineux (${(totalBytes / 1_048_576).toFixed(1)} Mo, max ` +
          `${(MAX_UPLOAD_BYTES / 1_048_576).toFixed(0)} Mo par import) -- utilise le format CSV ` +
          '(bien plus léger que .xlsx pour le même volume) ou importe en plusieurs fois.',
      )
      return
    }
    setUploading(true)
    setUploadElapsedSec(0)
    setUploadError(null)
    setBuildError(null)
    // La création de session envoie tous les fichiers en UN SEUL appel
    // (fusionnés côté serveur) -- il n'y a pas de progression par fichier
    // individuelle connue à l'avance. Chaque carte fichier tourne donc en
    // même temps ; elles passent toutes en succès ou en erreur ensemble,
    // ce qui reflète honnêtement ce que fait réellement l'appel réseau.
    const startedAt = Date.now()
    const interval = window.setInterval(() => {
      setUploadElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    try {
      const data = await createPipelineSession(orgId, files)
      onSessionCreated(data)
      setExcludedSheets(new Set())
      setPendingFiles([])
      // [5] Auto-assignation de TOUS les onglets dès l'import, pour
      // qu'aucun onglet ne reste vide sans avoir à cliquer.
      await loadSuggestion(data.session_id, 'all', data.sheets.map((s) => s.sheet_key))
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      window.clearInterval(interval)
      setUploading(false)
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (uploading) return
    const files = Array.from(e.dataTransfer.files ?? [])
    if (files.length) void handleFilesChange(files)
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} o`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`
    return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
  }

  // Charge la suggestion d'auto-assignation pour TOUS les onglets (dry_run,
  // rien n'est écrit côté serveur), puis ne remplace que les onglets
  // demandés (`only` : une clé précise pour le bouton "Auto" local, "all"
  // pour "Auto-assigner TOUS les onglets" -- limité aux onglets ACTIFS).
  async function loadSuggestion(sessionId: string, only: string | 'all', sheetKeys: string[]) {
    setSuggestLoading(only)
    setSuggestError(null)
    try {
      const data = await suggestPipelineMapping(orgId, sessionId, sheetKeys)
      setMapping((prev) => {
        const next = { ...prev }
        if (only === 'all') {
          for (const [sheetKey, m] of Object.entries(data.suggested_mapping)) {
            next[sheetKey] = m
          }
        } else if (data.suggested_mapping[only]) {
          next[only] = data.suggested_mapping[only]
        }
        return next
      })
    } catch (err) {
      setSuggestError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSuggestLoading(null)
    }
  }

  function toggleFileIncluded(keys: string[], included: boolean) {
    setExcludedSheets((prev) => {
      const next = new Set(prev)
      for (const k of keys) {
        if (included) next.delete(k)
        else next.add(k)
      }
      return next
    })
  }

  function toggleSheetIncluded(sheetKey: string, included: boolean) {
    setExcludedSheets((prev) => {
      const next = new Set(prev)
      if (included) next.delete(sheetKey)
      else next.add(sheetKey)
      return next
    })
  }

  function setSheetColumnMapping(sheetKey: string, srcCol: string, masterCol: string) {
    setMapping((prev) => ({
      ...prev,
      [sheetKey]: { ...(prev[sheetKey] ?? {}), [srcCol]: masterCol },
    }))
  }

  async function handleBuild() {
    if (!session) return
    setBuilding(true)
    setBuildError(null)
    try {
      // Seuls les onglets ACTIFS sont envoyés -- un onglet décoché est
      // absent du mapping, donc exclu de la base fusionnée côté serveur
      // (voir api/main.py:apply_pipeline_mapping).
      const activeMapping: PipelineMappingBySheet = {}
      for (const s of activeSheets) {
        activeMapping[s.sheet_key] = mapping[s.sheet_key] ?? {}
      }
      const data = await applyPipelineMapping(orgId, session.session_id, activeMapping)
      onMapped(data)
    } catch (err) {
      setBuildError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setBuilding(false)
    }
  }

  function reset() {
    onResetSession()
    setMapping({})
    setExcludedSheets(new Set())
    setUploadError(null)
    setSuggestError(null)
    setBuildError(null)
  }

  const anyAssigned = activeSheets.some((s) =>
    Object.values(mapping[s.sheet_key] ?? {}).some((m) => m && m !== PIPELINE_UNASSIGNED),
  )

  const totalSheets = session?.sheets.length ?? 0
  const totalFiles = sheetsByFile.size
  const nActive = activeSheets.length
  const nExcluded = totalSheets - nActive
  const totalRowsActive = activeSheets.reduce((sum, s) => sum + s.row_count, 0)

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">Importer vos fichiers Excel, CSV ou PDF</h2>

      {!session && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--muted)]">
            Déposez un ou plusieurs fichiers Excel, CSV ou PDF (relevé de prélèvements) -- chaque
            fichier peut avoir plusieurs onglets, chacun mappé séparément ci-dessous. Rien n'est
            encore écrit définitivement : cette session reste temporaire (24h) jusqu'à la
            construction de la base.
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls,.pdf"
            multiple
            onChange={(e) => void handleFilesChange(Array.from(e.target.files ?? []))}
            className="hidden"
          />
          <div
            role="button"
            tabIndex={0}
            onClick={() => !uploading && fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !uploading) fileInputRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              if (!uploading) setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
              uploading
                ? 'cursor-not-allowed border-[var(--border)] opacity-60'
                : dragOver
                  ? 'cursor-pointer border-[var(--primary)] bg-[var(--primary)]/5'
                  : 'cursor-pointer border-[var(--border)] hover:border-[var(--primary)]'
            }`}
          >
            <svg
              width="40"
              height="40"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className="text-[var(--muted)]"
              aria-hidden="true"
            >
              <path d="M12 16V4m0 0-4 4m4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="text-sm font-medium">
              Glissez vos fichiers ici, ou <span className="text-[var(--primary)] underline">cliquez pour choisir</span>
            </p>
            <p className="text-xs text-[var(--muted)]">
              Excel, CSV ou PDF (relevé de prélèvements) -- plusieurs fichiers à la fois
            </p>
          </div>
          <p className="text-xs text-[var(--muted)]">
            💡 Pour de très gros volumes (plusieurs millions de lignes), le <strong>CSV</strong> est
            bien plus rapide et léger que le .xlsx.
          </p>
          {pendingFiles.length > 0 && (
            <div className="flex flex-col gap-2 rounded-md border border-[var(--border)] p-3">
              {pendingFiles.map((f, i) => (
                <div key={`${f.name}-${i}`} className="flex items-center gap-3 text-sm">
                  {uploading ? (
                    <span
                      className="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent text-[var(--primary)]"
                      aria-hidden="true"
                    />
                  ) : uploadError ? (
                    <span className="shrink-0 text-[var(--danger)]" aria-hidden="true">
                      ❌
                    </span>
                  ) : (
                    <span className="shrink-0 text-[var(--success,#16a34a)]" aria-hidden="true">
                      ✅
                    </span>
                  )}
                  <span className="truncate">{f.name}</span>
                  <span className="ml-auto shrink-0 text-xs text-[var(--muted)]">{formatFileSize(f.size)}</span>
                </div>
              ))}
              {uploading && (
                <>
                  <p className="flex items-center gap-2 text-xs text-[var(--muted)]">
                    Import en cours… ({uploadElapsedSec}s)
                    {uploadElapsedSec >= 8 && ' -- un gros fichier peut prendre encore quelques instants.'}
                  </p>
                  <p className="text-xs font-medium text-[var(--danger)]">
                    ⚠️ Ne quitte pas cette page (ni une autre appli/onglet) tant que l'import est en
                    cours -- ça coupe l'envoi et il faudra recommencer.
                  </p>
                </>
              )}
            </div>
          )}
          {uploadError && <p className="text-sm text-[var(--danger)]">❌ Erreur : {uploadError}</p>}
        </div>
      )}

      {session && !mappingResult && (
        <div className="flex flex-col gap-4">
          {/* [3] Choisir les fichiers et onglets à inclure */}
          <div className="rounded-md border border-[var(--border)]">
            <button
              type="button"
              onClick={() => setIncludeExpanderOpen((v) => !v)}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium"
            >
              <span>🗂️ Choisir les fichiers et onglets à inclure</span>
              <span className="text-[var(--muted)]">{includeExpanderOpen ? '▲' : '▼'}</span>
            </button>
            {includeExpanderOpen && (
              <div className="flex flex-col gap-2 border-t border-[var(--border)] p-3 text-sm">
                <p className="text-xs text-[var(--muted)]">
                  Décoche ce que tu ne veux pas traiter. Aucun fichier n'est relu.
                </p>
                {[...sheetsByFile.entries()].map(([file, sheets]) => {
                  const keys = sheets.map((s) => s.sheet_key)
                  const fileIncluded = keys.every((k) => !excludedSheets.has(k))
                  return (
                    <div key={file} className="flex flex-col gap-1">
                      <label className="flex items-center gap-2 font-medium">
                        <input
                          type="checkbox"
                          checked={fileIncluded}
                          onChange={(e) => toggleFileIncluded(keys, e.target.checked)}
                        />
                        {file} ({sheets.length} onglet{sheets.length > 1 ? 's' : ''})
                      </label>
                      {sheets.map((s) => {
                        const sheetName = s.sheet_key.includes(' :: ')
                          ? s.sheet_key.split(' :: ', 2)[1]
                          : s.sheet_key
                        return (
                          <label key={s.sheet_key} className="ml-5 flex items-center gap-2 text-[var(--muted)]">
                            <input
                              type="checkbox"
                              checked={!excludedSheets.has(s.sheet_key)}
                              onChange={(e) => toggleSheetIncluded(s.sheet_key, e.target.checked)}
                            />
                            └ {sheetName} — {s.row_count} ligne(s)
                          </label>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {nExcluded > 0 ? (
            <p className="text-sm text-[var(--success,#16a34a)]">
              ✅ {totalSheets} onglet(s) détecté(s) — <strong>{nActive} inclus</strong>, {nExcluded}{' '}
              exclu(s) · {totalFiles} fichier(s) traité(s).
            </p>
          ) : (
            <p className="text-sm text-[var(--success,#16a34a)]">
              ✅ {totalFiles} fichier(s) importé(s), {totalSheets} onglet(s) détecté(s) au total.
            </p>
          )}

          {totalRowsActive > VOLUME_WARNING_THRESHOLD && (
            <p className="text-sm text-[var(--danger)]">
              ⚠️ Volume important : {totalRowsActive.toLocaleString('fr-FR')} lignes au total. En cas
              de souci : importe moins de fichiers/onglets à la fois, exclus les onglets inutiles
              ci-dessus, ou découpe le fichier.
            </p>
          )}

          <div className="border-t border-[var(--border)] pt-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-semibold">Assignation des colonnes</h3>
              <Button
                variant="secondary"
                onClick={() =>
                  session && void loadSuggestion(session.session_id, 'all', session.sheets.map((s) => s.sheet_key))
                }
                disabled={suggestLoading !== null || activeSheets.length === 0}
              >
                🚀 Auto-assigner TOUS les onglets
              </Button>
            </div>
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
            {suggestError && (
              <p className="mb-2 text-sm text-[var(--danger)]">
                Erreur de suggestion : {suggestError} -- tu peux mapper manuellement ci-dessous.
              </p>
            )}

            {activeSheets.length === 0 && (
              <p className="text-sm text-[var(--muted)]">
                ⚠️ Tous les onglets sont exclus. Coche-en au moins un ci-dessus pour continuer.
              </p>
            )}

            <div className="flex flex-col gap-6">
              {activeSheets.map((sheet) => (
                <SheetMappingCard
                  key={sheet.sheet_key}
                  sheet={sheet}
                  masterColumns={masterColumns ?? []}
                  mapping={mapping[sheet.sheet_key] ?? {}}
                  onColumnChange={(src, master) => setSheetColumnMapping(sheet.sheet_key, src, master)}
                  onAuto={() =>
                    session &&
                    void loadSuggestion(session.session_id, sheet.sheet_key, session.sheets.map((s) => s.sheet_key))
                  }
                  autoLoading={suggestLoading === sheet.sheet_key || suggestLoading === 'all'}
                />
              ))}
            </div>
          </div>

          {!anyAssigned && activeSheets.length > 0 && (
            <p className="text-sm text-[var(--muted)]">
              ⚠️ Veuillez assigner au moins une colonne maître avant de construire la base.
            </p>
          )}

          {buildError && <p className="text-sm text-[var(--danger)]">❌ Erreur : {buildError}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void handleBuild()} disabled={!anyAssigned || building}>
              {building ? 'Construction…' : '✅ Construire la base de travail fusionnée'}
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
            ✅ Base construite : {mappingResult.n_rows_updated} ligne(s) fusionnée(s)
            {mappingResult.n_rows_excluded > 0
              ? ` (${mappingResult.n_rows_excluded} ligne(s) d'onglet(s) non assigné(s) ou exclu(s) écartée(s)).`
              : '.'}
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

// [7] Une carte par onglet actif : titre, résumé, bouton Auto local, puis
// UNE GRILLE ALIGNÉE (menus en ligne 1, aperçu des données en dessous,
// chaque colonne de données alignée sous son menu) -- même structure que
// views/tab2_import_mapping.py (st.columns(n) réutilisé pour les deux
// lignes). Le mapping de cet onglet vit dans son propre état (prop
// `mapping`, jamais fusionné avec les autres onglets).
function SheetMappingCard({
  sheet,
  masterColumns,
  mapping,
  onColumnChange,
  onAuto,
  autoLoading,
}: {
  sheet: PipelineSheetSummary
  masterColumns: string[]
  mapping: Record<string, string>
  onColumnChange: (srcCol: string, masterCol: string) => void
  onAuto: () => void
  autoLoading: boolean
}) {
  const cols = sheet.columns
  const gridTemplate = `repeat(${cols.length}, minmax(150px, 1fr))`

  function optionsFor(srcCol: string): string[] {
    const usedElsewhere = new Set(
      cols
        .filter((c) => c !== srcCol)
        .map((c) => mapping[c])
        .filter((m): m is string => !!m && m !== PIPELINE_UNASSIGNED),
    )
    return [PIPELINE_UNASSIGNED, ...masterColumns.filter((m) => !usedElsewhere.has(m))]
  }

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <h4 className="mb-1 text-sm font-semibold">📄 {sheet.sheet_key}</h4>
      <p className="mb-2 text-xs text-[var(--muted)]">
        {sheet.row_count} ligne(s) | {cols.length} colonne(s) | {sheet.n_duplicates} doublon(s)
      </p>
      <div className="mb-2">
        <Button variant="secondary" onClick={onAuto} disabled={autoLoading}>
          {autoLoading ? 'Auto…' : '🚀 Auto'}
        </Button>
      </div>

      <p className="mb-2 text-xs text-[var(--muted)]">
        Colonne maître (menu) et aperçu des données forment un même tableau : chaque menu est
        aligné, à la même largeur, au-dessus de sa colonne.
      </p>

      <div className="overflow-x-auto rounded-md border border-[var(--border)]">
        <div
          className="grid gap-px bg-[var(--border)]"
          style={{ gridTemplateColumns: gridTemplate, minWidth: `${cols.length * 150}px` }}
        >
          {cols.map((col) => {
            const current = mapping[col] ?? PIPELINE_UNASSIGNED
            const options = optionsFor(col)
            const isInvalid = current !== PIPELINE_UNASSIGNED && !options.includes(current)
            return (
              <div key={col} className="flex flex-col gap-1 bg-[var(--muted-bg)] p-2">
                <span className="truncate text-xs font-medium" title={col}>
                  {col}
                </span>
                <select
                  value={isInvalid ? PIPELINE_UNASSIGNED : current}
                  onChange={(e) => onColumnChange(col, e.target.value)}
                  disabled={autoLoading}
                  className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs disabled:opacity-60"
                >
                  {options.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt === PIPELINE_UNASSIGNED ? '(non assigné)' : opt}
                    </option>
                  ))}
                </select>
              </div>
            )
          })}

          {sheet.preview_rows.slice(0, 6).map((row, i) => (
            <div key={i} className="contents">
              {cols.map((col) => {
                const v = row[col]
                const txt = v == null ? '' : String(v)
                return (
                  <div
                    key={col}
                    className="truncate bg-[var(--card)] px-2 py-1 text-xs"
                    title={txt}
                  >
                    {txt}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
