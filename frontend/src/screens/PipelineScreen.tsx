import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  PIPELINE_UNASSIGNED,
  applyPipelineMapping,
  createPipelineSession,
  getMasterColumns,
  suggestPipelineMapping,
  type PipelineMappingResult,
  type PipelineSessionCreated,
} from '@/lib/api'

// Trieur de Data -- étape 1 du pipeline (import + mapping des colonnes),
// mirroir simplifié des onglets 1-2 Streamlit (views/tab2_import_mapping.py) :
// UNE étape à la fois plutôt qu'une grille complexe. Le filtrage/dédoublonnage
// et l'export (onglets 3+) sont volontairement hors périmètre ici -- suite à
// faire dans un prochain chantier (voir PROJECT_LOG.md).
type Step = 'upload' | 'mapping' | 'done'

const PREVIEW_COLS_MAX = 8

export function PipelineScreen() {
  const { session: authSession, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()

  const [step, setStep] = useState<Step>('upload')

  const [uploading, setUploading] = useState(false)
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
  }

  async function handleFileChange(orgIdVal: string, file: File | null) {
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setResult(null)
    try {
      const data = await createPipelineSession(orgIdVal, file)
      setPipelineSession(data)
      setStep('mapping')
      await loadSuggestion(orgIdVal, data.session_id)
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
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
  const canBuild = assignedCount > 0 && !building

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
              {uploading && <p className="text-sm text-[var(--muted)]">Lecture du fichier…</p>}
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
                          className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm sm:w-56"
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

          {step === 'done' && result && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-[var(--success,#16a34a)]">
                {result.n_rows_updated} ligne(s) mappée(s) et prête(s) pour la suite du pipeline.
              </p>
              <p className="text-sm text-[var(--muted)]">
                Filtrage/dédoublonnage et export ne sont pas encore disponibles ici -- prochaine
                étape à venir.
              </p>
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
