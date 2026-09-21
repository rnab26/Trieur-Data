import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  generatePrelevementMandats,
  getPrelevementRules,
  savePrelevementRules,
  type PrelevementGenerateResult,
  type PrelevementRules,
} from '@/lib/api'

// Génération des mandats de prélèvement -- reconstruit à partir du
// fichier Excel du père de Raphaël (2026-09-21, voir PROJECT_LOG.md).
// Portée volontairement limitée pour l'instant (demandé explicitement
// par Raphaël) : nettoyer un export CRM brut et sortir un classeur prêt
// pour la banque (OOFF/RCUR/Exclus). L'historique, les doublons, les
// impayés et le relevé bancaire sont un chantier à part (Cockpit,
// "Historique, doublons, impayés et relevé bancaire").
export function PrelevementScreen() {
  const { session, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()

  const [rules, setRules] = useState<PrelevementRules | null>(null)
  const [rulesError, setRulesError] = useState<string | null>(null)
  const [ics, setIcs] = useState('')
  const [nature, setNature] = useState<'CORE' | 'B2B'>('CORE')
  const [delayDays, setDelayDays] = useState(3)
  const [fraisSetupEur, setFraisSetupEur] = useState(20)
  const [savingRules, setSavingRules] = useState(false)
  const [rulesSaved, setRulesSaved] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [result, setResult] = useState<PrelevementGenerateResult | null>(null)

  useEffect(() => {
    if (!orgId) return
    let cancelled = false
    setRules(null)
    setRulesError(null)
    setResult(null)
    getPrelevementRules(orgId)
      .then((data) => {
        if (cancelled) return
        setRules(data)
        setIcs(data.ics ?? '')
        setNature(data.nature)
        setDelayDays(data.delay_days)
        setFraisSetupEur(data.frais_setup_eur)
      })
      .catch((err: unknown) => {
        if (!cancelled) setRulesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  async function handleSaveRules() {
    if (!orgId) return
    setSavingRules(true)
    setRulesError(null)
    setRulesSaved(false)
    try {
      const updated = await savePrelevementRules(orgId, {
        ics: ics.trim() || null,
        nature,
        delayDays,
        fraisSetupEur,
      })
      setRules(updated)
      setRulesSaved(true)
    } catch (err) {
      setRulesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingRules(false)
    }
  }

  function handleFileSelected(file: File | null) {
    setSelectedFile(file)
    setResult(null)
    setGenerateError(null)
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (generating) return
    const file = e.dataTransfer.files?.[0]
    if (file) handleFileSelected(file)
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} o`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`
    return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
  }

  async function handleGenerate() {
    if (!orgId || !selectedFile) return
    setGenerating(true)
    setGenerateError(null)
    setResult(null)
    try {
      const counts = await generatePrelevementMandats(orgId, selectedFile)
      setResult(counts)
      setSelectedFile(null) // vide la sélection, pour ne pas relancer par erreur sur le même fichier
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Prélèvement — Génération des mandats</h1>
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <span>{session?.user.email}</span>
          <Button variant="secondary" onClick={() => void signOut()}>
            Se déconnecter
          </Button>
        </div>
      </header>

      <p className="mb-4 text-sm text-[var(--muted)]">
        Dépose l'export CRM brut, télécharge un classeur prêt (4 onglets : Mandat avec tout, First et
        RCUR en détail, Exclus avec la raison). Un mandat par produit actif du client, jamais un
        montant groupé. Ne couvre pas encore l'historique/les doublons/les impayés/le relevé bancaire
        — voir le chantier séparé dans le Cockpit.
      </p>

      {orgsError && (
        <p className="mb-4 text-sm text-[var(--danger)]">
          Impossible de charger les environnements : {orgsError}
        </p>
      )}

      {orgs && orgs.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label htmlFor="prelevement-org-switcher" className="text-sm text-[var(--muted)]">
            Environnement
          </label>
          <select
            id="prelevement-org-switcher"
            className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
            value={orgId ?? ''}
            onChange={(e) => setOrgId(e.target.value)}
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
          <Card className="mb-4">
            <CardContent className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">Réglages</h2>
              {rules === null && !rulesError && (
                <p className="text-sm text-[var(--muted)]">Chargement…</p>
              )}
              {rulesError && <p className="text-sm text-[var(--danger)]">{rulesError}</p>}
              {rules !== null && (
                <>
                  <div>
                    <label htmlFor="prelevement-ics" className="mb-1 block text-sm text-[var(--muted)]">
                      Numéro ICS (laissé vide pour l'instant si tu ne l'as pas)
                    </label>
                    <Input
                      id="prelevement-ics"
                      value={ics}
                      onChange={(e) => setIcs(e.target.value)}
                      placeholder="Ex. FR12ZZZ123456"
                    />
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <div>
                      <label htmlFor="prelevement-nature" className="mb-1 block text-sm text-[var(--muted)]">
                        Nature
                      </label>
                      <select
                        id="prelevement-nature"
                        className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
                        value={nature}
                        onChange={(e) => setNature(e.target.value as 'CORE' | 'B2B')}
                      >
                        <option value="CORE">CORE (particuliers)</option>
                        <option value="B2B">B2B (entreprises)</option>
                      </select>
                    </div>
                    <div>
                      <label htmlFor="prelevement-delay" className="mb-1 block text-sm text-[var(--muted)]">
                        Délai minimum avant le 1er prélèvement (jours)
                      </label>
                      <Input
                        id="prelevement-delay"
                        type="number"
                        min={0}
                        className="w-24"
                        value={delayDays}
                        onChange={(e) => setDelayDays(Number(e.target.value) || 0)}
                      />
                    </div>
                    <div>
                      <label htmlFor="prelevement-frais" className="mb-1 block text-sm text-[var(--muted)]">
                        Frais de dossier par produit, au 1er prélèvement (€)
                      </label>
                      <Input
                        id="prelevement-frais"
                        type="number"
                        min={0}
                        step="0.01"
                        className="w-24"
                        value={fraisSetupEur}
                        onChange={(e) => setFraisSetupEur(Number(e.target.value) || 0)}
                      />
                    </div>
                  </div>
                  <div>
                    <Button onClick={() => void handleSaveRules()} disabled={savingRules}>
                      {savingRules ? 'Enregistrement…' : 'Enregistrer les réglages'}
                    </Button>
                    {rulesSaved && !savingRules && (
                      <span className="ml-2 text-sm text-[var(--muted)]">Enregistré ✓</span>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">Générer les mandats</h2>
              <div>
                <p className="mb-1 text-sm text-[var(--muted)]">
                  1. Choisis le fichier export CRM (.csv ou .xlsx)
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={(e) => handleFileSelected(e.target.files?.[0] ?? null)}
                  className="hidden"
                />
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => !generating && fileInputRef.current?.click()}
                  onKeyDown={(e) => {
                    if ((e.key === 'Enter' || e.key === ' ') && !generating) fileInputRef.current?.click()
                  }}
                  onDragOver={(e) => {
                    e.preventDefault()
                    if (!generating) setDragOver(true)
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${
                    generating
                      ? 'cursor-not-allowed border-[var(--border)] opacity-60'
                      : dragOver
                        ? 'cursor-pointer border-[var(--primary)] bg-[var(--primary)]/5'
                        : 'cursor-pointer border-[var(--border)] hover:border-[var(--primary)]'
                  }`}
                >
                  <svg
                    width="36"
                    height="36"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className="text-[var(--muted)]"
                    aria-hidden="true"
                  >
                    <path d="M12 16V4m0 0-4 4m4-4 4 4" strokeLinecap="round" strokeLinejoin="round" />
                    <path
                      d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {selectedFile ? (
                    <p className="text-sm font-medium">
                      {selectedFile.name}{' '}
                      <span className="text-[var(--muted)]">({formatFileSize(selectedFile.size)})</span>
                    </p>
                  ) : (
                    <p className="text-sm font-medium">
                      Glisse le fichier ici, ou{' '}
                      <span className="text-[var(--primary)] underline">clique pour choisir</span>
                    </p>
                  )}
                  <p className="text-xs text-[var(--muted)]">Excel (.xlsx) ou CSV -- un seul fichier</p>
                </div>
              </div>
              <div>
                <Button onClick={() => void handleGenerate()} disabled={generating || !selectedFile}>
                  {generating ? 'Génération…' : '2. Générer et télécharger'}
                </Button>
              </div>
              {generateError && <p className="text-sm text-[var(--danger)]">{generateError}</p>}
              {result && (
                <p className="text-sm text-[var(--foreground)]">
                  ✅ {result.ooffCount} mandat(s) First, {result.rcurCount} mandat(s) RCUR,{' '}
                  {result.exclusCount} ligne(s) exclue(s) (voir l'onglet "Exclus" du fichier
                  téléchargé pour la raison de chacune).
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
