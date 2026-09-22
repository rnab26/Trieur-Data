import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import { PrelevementMandatsPanel } from './PrelevementMandatsPanel'
import { PrelevementRuleRequests } from './PrelevementRuleRequests'
import {
  ApiError,
  downloadPrelevementFile,
  generatePrelevementMandats,
  getPrelevementRules,
  savePrelevementMandats,
  savePrelevementRules,
  type PrelevementGenerateResult,
  type PrelevementRules,
} from '@/lib/api'

// Nombre de lignes affichées dans l'aperçu -- au-delà, seul le fichier
// téléchargé (via downloadPrelevementFile) montre tout, pour ne pas
// rendre un tableau de centaines de lignes dans le navigateur mobile.
const PREVIEW_ROW_LIMIT = 20

// Génération des mandats de prélèvement -- reconstruit à partir du
// fichier Excel du père de Raphaël (2026-09-21, voir PROJECT_LOG.md).
// Portée volontairement limitée pour l'instant (demandé explicitement
// par Raphaël) : nettoyer un export CRM brut et sortir un classeur prêt
// pour la banque (OOFF/RCUR/Exclus). L'historique, les doublons, les
// impayés et le relevé bancaire sont un chantier à part (Cockpit,
// "Historique, doublons, impayés et relevé bancaire").
// Nom de l'environnement dans lequel cet écran doit TOUJOURS travailler --
// verrouillé (pas de sélecteur) car les réglages Prélèvement (ICS, frais de
// dossier...) sont stockés par environnement, et pouvoir en choisir un autre
// ici menait à éditer silencieusement le mauvais jeu de réglages (signalé
// par Raphaël, 2026-09-21).
const PRELEVEMENT_ORG_NAME = 'Prélèvement'

export function PrelevementScreen() {
  const { session, signOut } = useAuth()
  const { orgs, orgsError } = useOrgs()
  const orgId = orgs?.find((o) => o.name === PRELEVEMENT_ORG_NAME)?.id ?? null

  const [tab, setTab] = useState<'generer' | 'mandats'>('generer')

  const [rules, setRules] = useState<PrelevementRules | null>(null)
  const [rulesError, setRulesError] = useState<string | null>(null)
  const [ics, setIcs] = useState('')
  const [nature, setNature] = useState<'CORE' | 'B2B'>('CORE')
  const [delayDays, setDelayDays] = useState(3)
  const [fraisSetupEur, setFraisSetupEur] = useState(20)
  // Frais par produit + libellés de périodicité (Raphaël, 2026-09-22) --
  // réglables directement dans l'écran, jamais codés en dur (voir
  // trieur/prelevement.py). Toujours des listes COMPLÈTES en mémoire
  // (pré-remplies par l'API tant que rien n'a été personnalisé), même
  // convention que les colonnes maîtres : "Enregistrer" renvoie
  // l'intégralité, pas un correctif partiel.
  const [fraisParProduit, setFraisParProduit] = useState<Record<string, number>>({})
  const [periodicites, setPeriodicites] = useState<Record<string, string>>({})
  const [newPeriodiciteCode, setNewPeriodiciteCode] = useState('')
  const [newPeriodiciteTexte, setNewPeriodiciteTexte] = useState('')
  const [savingRules, setSavingRules] = useState(false)
  const [rulesSaved, setRulesSaved] = useState(false)
  const [rulesExplainOpen, setRulesExplainOpen] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [result, setResult] = useState<PrelevementGenerateResult | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedCount, setSavedCount] = useState<number | null>(null)

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
        setFraisParProduit(data.frais_par_produit)
        setPeriodicites(data.periodicites)
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
        fraisParProduit,
        periodicites,
      })
      setRules(updated)
      setFraisParProduit(updated.frais_par_produit)
      setPeriodicites(updated.periodicites)
      setRulesSaved(true)
    } catch (err) {
      setRulesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingRules(false)
    }
  }

  function updateFraisProduit(produit: string, value: number) {
    setFraisParProduit((prev) => ({ ...prev, [produit]: value }))
  }

  function updatePeriodiciteTexte(code: string, texte: string) {
    setPeriodicites((prev) => ({ ...prev, [code]: texte }))
  }

  function removePeriodicite(code: string) {
    if (!window.confirm(`Supprimer le libellé de périodicité « ${code} » ?`)) return
    setPeriodicites((prev) => {
      const next = { ...prev }
      delete next[code]
      return next
    })
  }

  function addPeriodicite() {
    const code = newPeriodiciteCode.trim().toLowerCase()
    const texte = newPeriodiciteTexte.trim()
    if (!code || !texte) return
    if (code in periodicites) {
      setRulesError('Ce code de périodicité existe déjà.')
      return
    }
    setPeriodicites((prev) => ({ ...prev, [code]: texte }))
    setNewPeriodiciteCode('')
    setNewPeriodiciteTexte('')
  }

  function handleFilesSelected(files: File[]) {
    if (!files.length) return
    // Ajoute aux fichiers déjà choisis (pas de remplacement) -- permet de
    // glisser plusieurs lots l'un après l'autre, demandé par Raphaël pour
    // pouvoir importer plusieurs exports CRM d'un coup (ex. un par mois).
    setSelectedFiles((prev) => [...prev, ...files])
    setResult(null)
    setGenerateError(null)
  }

  function handleRemoveFile(index: number) {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    if (generating) return
    handleFilesSelected(Array.from(e.dataTransfer.files ?? []))
  }

  function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} o`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`
    return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
  }

  async function handleGenerate() {
    if (!orgId || selectedFiles.length === 0) return
    setGenerating(true)
    setGenerateError(null)
    setResult(null)
    setSaveError(null)
    setSavedCount(null)
    try {
      const counts = await generatePrelevementMandats(orgId, selectedFiles)
      setResult(counts)
      setSelectedFiles([]) // vide la sélection, pour ne pas relancer par erreur sur les mêmes fichiers
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setGenerateError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleSaveToDatabase() {
    if (!orgId || !result || result.mandats.length === 0) return
    if (
      !window.confirm(
        `Enregistrer ${result.mandats.length} mandat(s) dans la base de données, environnement « ${PRELEVEMENT_ORG_NAME} » ?`,
      )
    ) {
      return
    }
    setSaving(true)
    setSaveError(null)
    try {
      const saved = await savePrelevementMandats(orgId, result.mandats)
      setSavedCount(saved.n_saved)
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={'mx-auto p-4 ' + (tab === 'mandats' ? 'max-w-6xl' : 'max-w-2xl')}>
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Prélèvement</h1>
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <span>{session?.user.email}</span>
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

      {orgs && orgs.length > 0 && (
        <p className="mb-4 flex items-center gap-2 text-sm text-[var(--muted)]">
          Environnement <span className="font-medium text-[var(--foreground)]">{PRELEVEMENT_ORG_NAME}</span>{' '}
          (verrouillé -- les réglages/mandats ci-dessous sont propres à cet environnement)
        </p>
      )}

      {orgs && orgs.length > 0 && !orgId && (
        <p className="mb-4 text-sm text-[var(--danger)]">
          Aucun accès à l'environnement "{PRELEVEMENT_ORG_NAME}" -- demande l'accès avant de continuer.
        </p>
      )}

      {orgId && (
        <div className="mb-4 flex gap-2 border-b border-[var(--border)]">
          {(
            [
              ['generer', 'Générer des mandats'],
              ['mandats', 'Mandats enregistrés'],
            ] as [typeof tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={
                'px-3 py-2 text-sm font-medium ' +
                (tab === key
                  ? 'border-b-2 border-[var(--primary)] text-[var(--foreground)]'
                  : 'text-[var(--muted)] hover:text-[var(--foreground)]')
              }
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {orgId && tab === 'mandats' && <PrelevementMandatsPanel orgId={orgId} />}

      {orgId && tab === 'generer' && (
        <>
          <p className="mb-4 text-sm text-[var(--muted)]">
            Dépose l'export CRM brut, télécharge un classeur prêt (4 onglets : Mandat avec tout, First et
            RCUR en détail, Exclus avec la raison). Un mandat par produit actif du client, jamais un
            montant groupé. Ne couvre pas encore l'historique/les doublons/les impayés/le relevé bancaire
            — voir le chantier séparé dans le Cockpit.
          </p>

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
                  </div>

                  {rules && rules.produits_connus.length > 0 && (
                    <div>
                      <p className="mb-2 text-sm text-[var(--muted)]">
                        Frais de dossier par produit, au 1er prélèvement (€) -- réglable produit par
                        produit, amené à évoluer avec l'activité.
                      </p>
                      <table className="w-full max-w-sm text-sm">
                        <tbody>
                          {rules.produits_connus.map((produit) => (
                            <tr key={produit} className="border-t border-[var(--border)] first:border-t-0">
                              <td className="truncate py-1 pr-2" title={produit}>
                                {produit}
                              </td>
                              <td className="py-1">
                                <div className="flex items-center gap-1">
                                  <Input
                                    type="number"
                                    min={0}
                                    step="0.01"
                                    className="h-8 w-20 px-2 py-1"
                                    value={fraisParProduit[produit] ?? fraisSetupEur}
                                    onChange={(e) => updateFraisProduit(produit, Number(e.target.value) || 0)}
                                  />
                                  <span className="text-xs text-[var(--muted)]">€</span>
                                  {fraisParProduit[produit] !== undefined &&
                                    fraisParProduit[produit] !== fraisSetupEur && (
                                      <button
                                        type="button"
                                        title={`Revenir à ${fraisSetupEur}€ (valeur par défaut)`}
                                        onClick={() => updateFraisProduit(produit, fraisSetupEur)}
                                        className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
                                      >
                                        ↺
                                      </button>
                                    )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <div>
                    <p className="mb-2 text-sm text-[var(--muted)]">
                      Libellés de périodicité -- ajoute/renomme/supprime un code de périodicité et son
                      explication affichée dans le mandat.
                    </p>
                    <table className="w-full max-w-md text-sm">
                      <tbody>
                        {Object.entries(periodicites).map(([code, texte]) => (
                          <tr key={code} className="border-t border-[var(--border)] first:border-t-0">
                            <td className="w-28 truncate py-1 pr-2 text-xs text-[var(--muted)]" title={code}>
                              {code}
                            </td>
                            <td className="py-1">
                              <Input
                                className="h-8 px-2 py-1"
                                value={texte}
                                onChange={(e) => updatePeriodiciteTexte(code, e.target.value)}
                              />
                            </td>
                            <td className="py-1 pl-1">
                              <button
                                type="button"
                                onClick={() => removePeriodicite(code)}
                                className="text-[var(--danger)]"
                                title="Supprimer"
                              >
                                🗑️
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Input
                        placeholder="Code (ex. bimensuelle)"
                        className="h-8 max-w-[10rem] px-2 py-1"
                        value={newPeriodiciteCode}
                        onChange={(e) => setNewPeriodiciteCode(e.target.value)}
                      />
                      <Input
                        placeholder="Explication (ex. Tous les 15 jours)"
                        className="h-8 max-w-xs px-2 py-1"
                        value={newPeriodiciteTexte}
                        onChange={(e) => setNewPeriodiciteTexte(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') addPeriodicite()
                        }}
                      />
                      <Button
                        variant="secondary"
                        onClick={addPeriodicite}
                        disabled={!newPeriodiciteCode.trim() || !newPeriodiciteTexte.trim()}
                      >
                        ➕ Ajouter
                      </Button>
                    </div>
                  </div>

                  <div>
                    <Button onClick={() => void handleSaveRules()} disabled={savingRules}>
                      {savingRules ? 'Enregistrement…' : 'Enregistrer les réglages'}
                    </Button>
                    {rulesSaved && !savingRules && (
                      <span className="ml-2 text-sm text-[var(--muted)]">Enregistré ✓</span>
                    )}
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      S'enregistre uniquement au clic ci-dessus -- pas automatique, mais persiste après ce
                      clic (rechargement de page compris).
                    </p>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {rules !== null && rules.explication.length > 0 && (
            <div className="mb-4 rounded-lg border border-[var(--border)]">
              <button
                type="button"
                onClick={() => setRulesExplainOpen((v) => !v)}
                className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium"
              >
                <span>📋 Règles appliquées par le moteur</span>
                <span className="text-[var(--muted)]">{rulesExplainOpen ? '▲' : '▼'}</span>
              </button>
              {rulesExplainOpen && (
                <div className="flex flex-col gap-3 border-t border-[var(--border)] p-3">
                  <p className="text-xs text-[var(--muted)]">
                    Ce que le code applique réellement à chaque génération -- pour repérer une
                    future erreur ou décider qu'une règle doit changer. Reflète tes réglages
                    ci-dessus (frais, délai).
                  </p>
                  {rules.explication.map((r, i) => (
                    <div key={i}>
                      <p className="text-sm font-medium text-[var(--foreground)]">{r.titre}</p>
                      <p className="text-sm text-[var(--muted)]">{r.detail}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <PrelevementRuleRequests orgId={orgId} />

          <Card>
            <CardContent className="flex flex-col gap-3">
              <h2 className="text-sm font-semibold">Générer les mandats</h2>
              <div>
                <p className="mb-1 text-sm text-[var(--muted)]">
                  1. Choisis un ou plusieurs fichiers export CRM (.csv ou .xlsx)
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  multiple
                  onChange={(e) => handleFilesSelected(Array.from(e.target.files ?? []))}
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
                  <p className="text-sm font-medium">
                    Glisse le/les fichier(s) ici, ou{' '}
                    <span className="text-[var(--primary)] underline">clique pour choisir</span>
                  </p>
                  <p className="text-xs text-[var(--muted)]">Excel (.xlsx) ou CSV -- plusieurs fichiers possibles</p>
                </div>
                {selectedFiles.length > 0 && (
                  <div className="mt-3 flex flex-col gap-2 rounded-md border border-[var(--border)] p-3">
                    <p className="text-sm font-medium text-[var(--foreground)]">
                      ✅ {selectedFiles.length} fichier{selectedFiles.length > 1 ? 's' : ''} sélectionné
                      {selectedFiles.length > 1 ? 's' : ''}
                    </p>
                    {selectedFiles.map((f, i) => (
                      <div key={`${f.name}-${i}`} className="flex items-center gap-2 text-sm">
                        <span className="truncate">{f.name}</span>
                        <span className="shrink-0 text-xs text-[var(--muted)]">({formatFileSize(f.size)})</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveFile(i)}
                          disabled={generating}
                          className="ml-auto shrink-0 text-xs text-[var(--danger)] underline disabled:opacity-60"
                        >
                          Retirer
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <Button onClick={() => void handleGenerate()} disabled={generating || selectedFiles.length === 0}>
                  {generating ? 'Génération…' : '2. Générer un aperçu'}
                </Button>
              </div>
              {generateError && <p className="text-sm text-[var(--danger)]">{generateError}</p>}
              {result && (
                <div className="flex flex-col gap-3 rounded-md border border-[var(--border)] p-3">
                  <p className="text-sm font-medium text-[var(--foreground)]">
                    Résumé du traitement
                  </p>
                  <table className="w-full max-w-md text-sm">
                    <tbody>
                      <tr>
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Fichier(s) lu(s)</td>
                        <td className="py-0.5 text-right font-medium text-[var(--foreground)]">
                          {result.summary.nFichiers}
                        </td>
                      </tr>
                      <tr>
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Lignes client au total</td>
                        <td className="py-0.5 text-right font-medium text-[var(--foreground)]">
                          {result.summary.nLignes}
                        </td>
                      </tr>
                      <tr>
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Lignes exclues</td>
                        <td
                          className={
                            'py-0.5 text-right font-medium ' +
                            (result.summary.nExclus > 0 ? 'text-[var(--danger)]' : 'text-[var(--foreground)]')
                          }
                        >
                          {result.summary.nExclus}
                        </td>
                      </tr>
                      {result.summary.exclusions.map((e, i) => (
                        <tr key={i}>
                          <td className="py-0.5 pl-4 text-xs text-[var(--muted)]">↳ {e.raison}</td>
                          <td className="py-0.5 text-right text-xs font-medium text-[var(--danger)]">{e.n}</td>
                        </tr>
                      ))}
                      <tr>
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Mandats First (1er prélèvement)</td>
                        <td className="py-0.5 text-right font-medium text-[var(--success)]">
                          {result.summary.nFirst}
                        </td>
                      </tr>
                      <tr>
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Mandats RCUR (récurrent)</td>
                        <td className="py-0.5 text-right font-medium text-[var(--success)]">
                          {result.summary.nRcur}
                        </td>
                      </tr>
                      {result.summary.nFusions > 0 && (
                        <tr>
                          <td className="pr-4 py-0.5 text-[var(--muted)]">Fusionnés MYJURIS+IMMO</td>
                          <td className="py-0.5 text-right font-medium text-[var(--foreground)]">
                            {result.summary.nFusions}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  {result.summary.exclusions.length > 0 && (
                    <p className="text-xs text-[var(--muted)]">
                      Voir aussi l'onglet "Exclus" du fichier téléchargé, client par client.
                    </p>
                  )}

                  {result.telephonesManquants.length > 0 && (
                    <div className="rounded-md border border-[var(--danger)] bg-[var(--danger)]/10 p-3">
                      <p className="text-sm font-medium text-[var(--danger)]">
                        ⚠️ {result.telephonesManquants.length} mandat
                        {result.telephonesManquants.length > 1 ? 's' : ''} SANS numéro de téléphone
                        (ni Téléphone ni Mobile trouvés) -- envoyé{result.telephonesManquants.length > 1 ? 's' : ''}{' '}
                        quand même, à vérifier avant l'envoi en banque :
                      </p>
                      <ul className="mt-1 list-disc pl-5 text-sm text-[var(--foreground)]">
                        {result.telephonesManquants.map((t, i) => (
                          <li key={i}>
                            {t.referenceClient} — {t.nom} ({t.motif})
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {result.mandats.length > 0 ? (
                    <div>
                      <p className="mb-1 text-sm font-medium text-[var(--foreground)]">
                        Aperçu ({Math.min(result.mandats.length, PREVIEW_ROW_LIMIT)} sur{' '}
                        {result.mandats.length} mandat{result.mandats.length > 1 ? 's' : ''})
                      </p>
                      <div className="overflow-x-auto rounded-md border border-[var(--border)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border)] bg-[var(--muted-bg,transparent)]">
                              {Object.keys(result.mandats[0]).map((col) => (
                                <th key={col} className="whitespace-nowrap px-2 py-1 text-left font-medium">
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {result.mandats.slice(0, PREVIEW_ROW_LIMIT).map((row, i) => (
                              <tr key={i} className="border-b border-[var(--border)] last:border-b-0">
                                {Object.keys(result.mandats[0]).map((col) => (
                                  <td key={col} className="whitespace-nowrap px-2 py-1">
                                    {row[col] ?? ''}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-[var(--muted)]">Aucun mandat généré sur ce lot.</p>
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    <Button onClick={() => downloadPrelevementFile(result)}>
                      3. Télécharger le classeur (.xlsx)
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => void handleSaveToDatabase()}
                      disabled={saving || result.mandats.length === 0}
                    >
                      {saving ? 'Enregistrement…' : 'Enregistrer dans la base de données'}
                    </Button>
                    {savedCount !== null && !saving && (
                      <span className="text-sm text-[var(--foreground)]">
                        ✅ {savedCount} mandat(s) enregistré(s)
                      </span>
                    )}
                  </div>
                  {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
