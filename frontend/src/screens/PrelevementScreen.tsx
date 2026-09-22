import { useEffect, useRef, useState } from 'react'
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/lib/AuthContext'
import { useOrgs } from '@/lib/useAccount'
import { PrelevementMandatsPanel } from './PrelevementMandatsPanel'
import { PrelevementRuleRequests, RuleQuestionBlock } from './PrelevementRuleRequests'
import {
  ApiError,
  createPrelevementRuleRequest,
  deletePrelevementColonnesMandatPreset,
  downloadPrelevementFile,
  generatePrelevementMandats,
  getPrelevementRules,
  listPrelevementColonnesMandatPresets,
  listPrelevementRuleRequests,
  patchPrelevementColonnesMandatPreset,
  savePrelevementColonnesMandatPreset,
  savePrelevementMandats,
  savePrelevementRules,
  type ColonneMandat,
  type ColonnesMandatPreset,
  type PrelevementGenerateResult,
  type PrelevementRuleRequest,
  type PrelevementRules,
} from '@/lib/api'

// Libellés courts pour le badge sur chaque règle du panneau ci-dessous
// -- une question en attente (voir pendingQuestions plus bas) prime
// toujours sur ce statut, jamais affichés en même temps.
const STATUT_BADGE: Record<PrelevementRuleRequest['statut'], string> = {
  en_attente: '⏳ Pas encore examinée',
  en_cours: '🔧 En cours de codage',
  valide: '✅ Codée et validée',
}

// Version compacte (juste l'icône) -- utilisée sur les pastilles
// d'attribution de règle par colonne (Modèles tableau, 2026-09-22) où
// STATUT_BADGE serait trop long pour tenir dans une cellule de 168px.
const RULE_STATUT_ICON: Record<PrelevementRuleRequest['statut'], string> = {
  en_attente: '⏳',
  en_cours: '🔧',
  valide: '✅',
}

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

// A, B, C... Z, AA, AB... -- juste des repères visuels façon tableur,
// comme demandé (Raphaël, 2026-09-22 : "les colonnes A, B, C etc"),
// jamais une clé utilisée pour quoi que ce soit côté données.
function lettreExcel(index: number): string {
  let n = index
  let s = ''
  do {
    s = String.fromCharCode(65 + (n % 26)) + s
    n = Math.floor(n / 26) - 1
  } while (n >= 0)
  return s
}

// Une cellule d'en-tête de colonne, réordonnable par glisser-déposer
// HORIZONTAL (Raphaël, 2026-09-22 : "un tableau Excel vraiment dans
// l'aperçu" -- remplace l'ancienne liste verticale). La poignée ⠿ est
// la seule zone qui déclenche le drag, pour que cocher/décocher la
// case au doigt ne déclenche jamais un glissement accidentel.
function SortableColonneMandatCell({
  colonne,
  lettre,
  note,
  removable,
  attributionLabel,
  onToggleVisible,
  onRemove,
  onRename,
  onOpenAttribute,
}: {
  colonne: ColonneMandat
  lettre: string
  note: string
  removable: boolean
  // Seule une colonne personnalisée (removable) peut être liée à une
  // règle -- "Attribuer en connectant les règles disponibles sur les
  // colonnes" (Raphaël, 2026-09-22, "Modèles tableau"). null tant
  // qu'aucune règle n'est liée.
  attributionLabel: string | null
  onToggleVisible: () => void
  onRemove: () => void
  // Seule une colonne personnalisée (removable) peut être renommée --
  // le nom d'une colonne canonique est la clé attendue par le
  // générateur, jamais éditable (Raphaël, 2026-09-22).
  onRename: (nouveauNom: string) => boolean
  onOpenAttribute: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: colonne.cle,
  })
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState(colonne.cle)

  function startRename() {
    setDraftName(colonne.cle)
    setRenaming(true)
  }

  function commitRename() {
    const ok = onRename(draftName.trim())
    if (ok) setRenaming(false)
  }

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.5 : 1 }}
      className={
        'flex w-40 flex-shrink-0 flex-col border-r border-b border-[var(--border)] bg-[var(--card)] ' +
        (colonne.visible ? '' : 'opacity-50')
      }
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--muted-bg)] px-1.5 py-0.5">
        <span className="text-[0.65rem] font-bold text-[var(--muted)]">{lettre}</span>
        <span
          {...attributes}
          {...listeners}
          className="touch-none cursor-grab select-none px-1 text-[var(--muted)]"
          aria-label={`Glisser pour réordonner la colonne ${colonne.cle}`}
        >
          ⠿
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1 p-1.5">
        {renaming ? (
          <Input
            autoFocus
            className="h-7 px-2 py-0.5 text-xs"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') setRenaming(false)
            }}
            onBlur={commitRename}
          />
        ) : (
          <span className={'text-xs font-medium ' + (colonne.visible ? '' : 'line-through')}>{colonne.cle}</span>
        )}
        <p className="text-[0.65rem] leading-tight text-[var(--muted)]">{note}</p>
        {removable && (
          <button
            type="button"
            onClick={onOpenAttribute}
            className={
              'rounded px-1 py-0.5 text-left text-[0.65rem] leading-tight ' +
              (attributionLabel
                ? 'bg-[var(--muted-bg)] text-[var(--primary)]'
                : 'text-[var(--primary)] hover:underline')
            }
          >
            {attributionLabel ?? '🔗 Attribuer une règle'}
          </button>
        )}
        <div className="mt-auto flex items-center gap-1.5 pt-1">
          <label className="flex items-center gap-1 text-[0.65rem] text-[var(--muted)]">
            <input type="checkbox" checked={colonne.visible} onChange={onToggleVisible} />
            visible
          </label>
          {removable && !renaming && (
            <>
              <button
                type="button"
                onClick={startRename}
                className="ml-auto px-0.5 text-[var(--muted)] hover:text-[var(--foreground)]"
                aria-label={`Renommer la colonne ${colonne.cle}`}
              >
                ✏️
              </button>
              <button
                type="button"
                onClick={onRemove}
                className="px-0.5 text-[var(--danger)] hover:opacity-70"
                aria-label={`Supprimer la colonne ${colonne.cle}`}
              >
                🗑️
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

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
  // Ordre/visibilité des colonnes du fichier de mandats (père de
  // Raphaël, 2026-09-22, "ORDRE DES COLONNES + MODIFICATIONS") --
  // réglable ici, sans repasser par une session Claude. Même convention
  // que frais_par_produit/periodicites : liste toujours complète en
  // mémoire, remplacement en masse à l'enregistrement.
  const [colonnesMandat, setColonnesMandat] = useState<ColonneMandat[]>([])
  // Sert seulement à savoir quelle colonne est supprimable (canonique =
  // jamais) -- voir "colonnes_mandat_canoniques" dans PrelevementRules.
  const [colonnesMandatCanoniques, setColonnesMandatCanoniques] = useState<string[]>([])
  // D'où vient la valeur de chaque colonne canonique (Raphaël,
  // 2026-09-22 : "je sais à quelle colonne s'attribue ces règles") --
  // affiché sous le nom dans l'aperçu, source unique côté API.
  const [colonnesMandatNotes, setColonnesMandatNotes] = useState<Record<string, string>>({})
  // Jeux de colonnes réutilisables (Raphaël, 2026-09-22 : "comme on
  // avait sur Streamlit") -- indépendant du chargement des réglages
  // (rules), pour ne pas coupler deux ressources qui n'ont rien à voir
  // niveau backend.
  const [colonnesMandatPresets, setColonnesMandatPresets] = useState<ColonnesMandatPreset[]>([])
  const [newPresetName, setNewPresetName] = useState('')
  const [savingPreset, setSavingPreset] = useState(false)
  const [deletingPresetId, setDeletingPresetId] = useState<string | null>(null)
  const [presetError, setPresetError] = useState<string | null>(null)
  // "📊✏️ Modèles tableau ⚙️" (Raphaël, 2026-09-22) -- toute l'édition
  // des colonnes (grille + modèles + attribution de règles) repliée
  // dans une seule box cliquable, comme le reste des réglages de cet
  // écran (jamais ouverte par défaut, "ça pollue visuellement").
  const [modelesOpen, setModelesOpen] = useState(false)
  // Le modèle actuellement chargé dans la grille de travail -- fixé par
  // "Sélectionner", pour que "💾 Enregistrer" (dans le panneau) sache
  // QUEL modèle mettre à jour, sans redemander un nom.
  const [activePresetId, setActivePresetId] = useState<string | null>(null)
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null)
  const [editingPresetName, setEditingPresetName] = useState('')
  const [savingPresetColonnes, setSavingPresetColonnes] = useState(false)
  // Attribution d'une règle à une colonne personnalisée (Raphaël,
  // 2026-09-22 : "attribuer en connectant les règles disponibles sur
  // les colonnes... créer une nouvelle règle au-dessus d'une colonne").
  const [attributingCle, setAttributingCle] = useState<string | null>(null)
  // Titre éditable (Raphaël, 2026-09-22 : "il faut pouvoir donner un
  // titre en gras à cette règle") -- pré-rempli avec le nom de la
  // colonne, mais modifiable.
  const [newRuleForColumnTitre, setNewRuleForColumnTitre] = useState('')
  const [newRuleForColumnText, setNewRuleForColumnText] = useState('')
  const [creatingRuleForColumn, setCreatingRuleForColumn] = useState(false)
  const [ruleAttributionError, setRuleAttributionError] = useState<string | null>(null)
  const [ruleAttributedNotice, setRuleAttributedNotice] = useState(false)
  const [newPeriodiciteCode, setNewPeriodiciteCode] = useState('')
  const [newPeriodiciteTexte, setNewPeriodiciteTexte] = useState('')
  const [savingRules, setSavingRules] = useState(false)
  const [rulesSaved, setRulesSaved] = useState(false)
  const [rulesExplainOpen, setRulesExplainOpen] = useState(false)
  // Formulaire de demande de modification directement SOUS la règle
  // concernée (Raphaël, 2026-09-22 : "que ça repasse en bas, ça
  // embrouille -- laisse-le juste en dessous, les demandes ne passent
  // en bas [dans la liste] que pour de nouvelles règles"). `openRuleIdx`
  // = index dans rules.explication du formulaire actuellement ouvert
  // (un seul à la fois), le texte tapé et l'état d'envoi lui sont
  // propres. `ruleRequestsRefreshKey` fait recharger la liste du
  // dessous (PrelevementRuleRequests) après un ajout depuis ici, sans
  // dupliquer sa logique de récupération.
  const [openRuleIdx, setOpenRuleIdx] = useState<number | null>(null)
  // Titre éditable (Raphaël, 2026-09-22 : "il faut pouvoir donner un
  // titre en gras à cette règle") -- pré-rempli avec le nom de la règle
  // modifiée, mais modifiable : utile dès qu'on demande une 2e/3e
  // précision sur la même règle et qu'on veut la distinguer dans la
  // liste ("Exclusions, 2e partie" par exemple).
  const [ruleFormTitre, setRuleFormTitre] = useState('')
  const [ruleFormText, setRuleFormText] = useState('')
  const [ruleFormSubmitting, setRuleFormSubmitting] = useState(false)
  const [ruleFormError, setRuleFormError] = useState<string | null>(null)
  // Index de la règle dont la dernière demande envoyée affiche le
  // message de succès -- un index (jamais le titre) : le titre envoyé
  // peut maintenant différer de r.titre puisqu'il est modifiable.
  const [ruleFormSentIdx, setRuleFormSentIdx] = useState<number | null>(null)
  const [ruleRequestsRefreshKey, setRuleRequestsRefreshKey] = useState(0)
  // Réglages repliés par défaut (Raphaël, 2026-09-22 : "ça pollue
  // visuellement") -- même bascule que "Règles appliquées par le
  // moteur" juste en dessous.
  const [reglagesOpen, setReglagesOpen] = useState(false)
  // Toutes les demandes de règles de l'environnement, chargées ici (en
  // plus de PrelevementRuleRequests qui les affiche en historique) pour
  // calculer le badge de statut et la question en attente à côté de
  // chaque règle du panneau "Règles appliquées". Réinterrogé toutes les
  // 20s tant que l'écran est ouvert -- pas un vrai flux temps réel
  // (Supabase Realtime n'est pas câblé dans cette appli), mais assez
  // pour voir un ✅ Validé apparaître sans recharger la page.
  const [ruleRequestsAll, setRuleRequestsAll] = useState<PrelevementRuleRequest[]>([])

  useEffect(() => {
    if (!orgId) return
    const org = orgId
    let cancelled = false
    function load() {
      listPrelevementRuleRequests(org)
        .then((data) => {
          if (!cancelled) setRuleRequestsAll(data)
        })
        .catch(() => {
          // Silencieux : ce n'est qu'un indicateur secondaire (badge de
          // statut) -- une erreur réseau ponctuelle ne doit pas bloquer
          // le reste de l'écran ni afficher une alerte de plus.
        })
    }
    load()
    const interval = setInterval(load, 20000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [orgId, ruleRequestsRefreshKey])

  // Une question en attente est une ACTION à faire, jamais cachée
  // derrière un panneau replié -- bug réel signalé par Raphaël (son
  // père ne voyait rien du tout, y compris le badge rouge, parce que
  // "Règles appliquées par le moteur" reste replié par défaut et qu'il
  // fallait cliquer dessus AVANT même d'arriver à "Historique des
  // demandes" en dessous). Déroule ce panneau tout seul dès qu'une
  // question attend une réponse.
  useEffect(() => {
    if (ruleRequestsAll.some((r) => r.questions.some((q) => !q.answered_at))) {
      setRulesExplainOpen(true)
    }
  }, [ruleRequestsAll])

  function latestRuleRequestFor(titre: string): PrelevementRuleRequest | undefined {
    const key = titre.trim().toLowerCase()
    const matches = ruleRequestsAll.filter((r) => r.titre.trim().toLowerCase() === key)
    if (matches.length === 0) return undefined
    return matches.reduce((a, b) => (a.created_at > b.created_at ? a : b))
  }

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
        setColonnesMandat(data.colonnes_mandat)
        setColonnesMandatCanoniques(data.colonnes_mandat_canoniques)
        setColonnesMandatNotes(data.colonnes_mandat_notes)
      })
      .catch((err: unknown) => {
        if (!cancelled) setRulesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  useEffect(() => {
    if (!orgId) return
    let cancelled = false
    listPrelevementColonnesMandatPresets(orgId)
      .then((data) => {
        if (!cancelled) setColonnesMandatPresets(data)
      })
      .catch(() => {
        // Silencieux : un jeu de colonnes est un raccourci, pas une donnée
        // critique -- une erreur réseau ponctuelle ne doit pas bloquer le
        // reste des réglages ni ajouter une alerte de plus à l'écran.
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  // "Sélectionner" (Raphaël, 2026-09-22) : applique ce modèle à la
  // grille de travail ET mémorise lequel, pour que "💾 Enregistrer"
  // sache où réenregistrer les colonnes ensuite.
  function selectColonnesMandatPreset(preset: ColonnesMandatPreset) {
    setColonnesMandat(preset.colonnes)
    setActivePresetId(preset.id)
  }

  async function handleSaveColonnesMandatPreset() {
    if (!orgId) return
    const name = newPresetName.trim()
    if (!name) return
    setSavingPreset(true)
    setPresetError(null)
    try {
      const saved = await savePrelevementColonnesMandatPreset(orgId, name, colonnesMandat)
      setColonnesMandatPresets((prev) => {
        const idx = prev.findIndex((p) => p.id === saved.id)
        if (idx === -1) return [...prev, saved].sort((a, b) => a.name.localeCompare(b.name))
        const next = [...prev]
        next[idx] = saved
        return next
      })
      setActivePresetId(saved.id)
      setNewPresetName('')
    } catch (err) {
      setPresetError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingPreset(false)
    }
  }

  // "✏️ Modifier" -- renomme un modèle existant, colonnes inchangées.
  function startRenamePreset(preset: ColonnesMandatPreset) {
    setEditingPresetId(preset.id)
    setEditingPresetName(preset.name)
  }

  async function commitRenamePreset(id: string) {
    if (!orgId) return
    const name = editingPresetName.trim()
    if (!name) return
    setPresetError(null)
    try {
      const updated = await patchPrelevementColonnesMandatPreset(orgId, id, { name })
      setColonnesMandatPresets((prev) =>
        prev.map((p) => (p.id === id ? updated : p)).sort((a, b) => a.name.localeCompare(b.name)),
      )
      setEditingPresetId(null)
    } catch (err) {
      setPresetError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  // "💾 Enregistrer" du panneau -- met à jour les colonnes du modèle
  // SÉLECTIONNÉ (jamais les réglages réels du générateur : ça reste le
  // rôle du bouton "Enregistrer les réglages", séparé, en dehors de ce
  // panneau).
  async function handleSaveActivePresetColonnes() {
    if (!orgId || !activePresetId) return
    setSavingPresetColonnes(true)
    setPresetError(null)
    try {
      const updated = await patchPrelevementColonnesMandatPreset(orgId, activePresetId, {
        colonnes: colonnesMandat,
      })
      setColonnesMandatPresets((prev) => prev.map((p) => (p.id === activePresetId ? updated : p)))
    } catch (err) {
      setPresetError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingPresetColonnes(false)
    }
  }

  async function handleDeleteColonnesMandatPreset(id: string) {
    if (!orgId) return
    setDeletingPresetId(id)
    setPresetError(null)
    try {
      await deletePrelevementColonnesMandatPreset(orgId, id)
      setColonnesMandatPresets((prev) => prev.filter((p) => p.id !== id))
      if (activePresetId === id) setActivePresetId(null)
    } catch (err) {
      setPresetError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setDeletingPresetId(null)
    }
  }

  // Attribution d'une règle à une colonne personnalisée (Raphaël,
  // 2026-09-22, "Modèles tableau") -- soit une demande déjà en file
  // (pas encore validée), soit une nouvelle, créée ici même : même
  // mécanisme que le formulaire "+ Nouvelle règle" déjà utilisé
  // ailleurs sur cet écran (submitRuleForm), donc automatiquement
  // visible dans "Règles appliquées par le moteur > + nouvelles règles".
  function toggleAttribute(cle: string) {
    setAttributingCle((prev) => (prev === cle ? null : cle))
    setNewRuleForColumnTitre(`Colonne "${cle}"`)
    setNewRuleForColumnText('')
    setRuleAttributionError(null)
  }

  function pickExistingRuleForColumn(cle: string, requestId: string) {
    setColonnesMandat((prev) => prev.map((c) => (c.cle === cle ? { ...c, rule_request_id: requestId } : c)))
    setAttributingCle(null)
  }

  async function submitNewRuleForColumn(cle: string) {
    const titre = newRuleForColumnTitre.trim()
    const demande = newRuleForColumnText.trim()
    if (!orgId || !titre || !demande) return
    setCreatingRuleForColumn(true)
    setRuleAttributionError(null)
    try {
      const created = await createPrelevementRuleRequest(orgId, titre, demande)
      setColonnesMandat((prev) => prev.map((c) => (c.cle === cle ? { ...c, rule_request_id: created.id } : c)))
      setRuleRequestsRefreshKey((k) => k + 1)
      setAttributingCle(null)
      setNewRuleForColumnText('')
      setRuleAttributedNotice(true)
      setTimeout(() => setRuleAttributedNotice(false), 4000)
    } catch (err) {
      setRuleAttributionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setCreatingRuleForColumn(false)
    }
  }

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
        colonnesMandat,
      })
      setRules(updated)
      setFraisParProduit(updated.frais_par_produit)
      setPeriodicites(updated.periodicites)
      setColonnesMandat(updated.colonnes_mandat)
      setColonnesMandatCanoniques(updated.colonnes_mandat_canoniques)
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

  // Réordonner/masquer une colonne du fichier de mandats -- glisser-
  // déposer (Raphaël, 2026-09-22 : "plus pratique" que des flèches).
  function reorderColonneMandat(activeCle: string, overCle: string) {
    if (activeCle === overCle) return
    setColonnesMandat((prev) => {
      const from = prev.findIndex((c) => c.cle === activeCle)
      const to = prev.findIndex((c) => c.cle === overCle)
      if (from === -1 || to === -1) return prev
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }

  function toggleColonneMandatVisible(cle: string) {
    setColonnesMandat((prev) => prev.map((c) => (c.cle === cle ? { ...c, visible: !c.visible } : c)))
  }

  // "➕ ajouter une colonne" (Raphaël, 2026-09-22) : une colonne libre,
  // sans source dans le CRM -- toujours vide au générateur, à remplir à
  // la main après export (décision explicite, pas une valeur inventée).
  const [newColonneMandat, setNewColonneMandat] = useState('')

  function addColonneMandat() {
    const nom = newColonneMandat.trim()
    if (!nom) return
    if (colonnesMandat.some((c) => c.cle.toLowerCase() === nom.toLowerCase())) {
      setRulesError('Une colonne porte déjà ce nom.')
      return
    }
    setColonnesMandat((prev) => [...prev, { cle: nom, visible: true }])
    setNewColonneMandat('')
  }

  function removeColonneMandatPersonnalisee(cle: string) {
    setColonnesMandat((prev) => prev.filter((c) => c.cle !== cle))
  }

  // "pouvoir la renommer après coup" (Raphaël, 2026-09-22) -- seul le
  // nom change, position et visibilité restent celles de la ligne.
  // Retourne false (et affiche l'erreur) si le nouveau nom est vide ou
  // déjà pris, pour que la ligne reste en édition plutôt que de
  // silencieusement perdre la saisie.
  function renameColonneMandatPersonnalisee(ancienCle: string, nouveauCle: string): boolean {
    if (!nouveauCle) {
      setRulesError('Nom de colonne vide.')
      return false
    }
    if (
      nouveauCle.toLowerCase() !== ancienCle.toLowerCase() &&
      colonnesMandat.some((c) => c.cle.toLowerCase() === nouveauCle.toLowerCase())
    ) {
      setRulesError('Une colonne porte déjà ce nom.')
      return false
    }
    setColonnesMandat((prev) => prev.map((c) => (c.cle === ancienCle ? { ...c, cle: nouveauCle } : c)))
    return true
  }

  // distance: 5 -- laisse le temps à un simple tap (cocher la case, par
  // exemple) de se distinguer d'un vrai glissement, au doigt comme à la
  // souris.
  // Contrainte "delay" plutôt que "distance" (Raphaël, 2026-09-22 :
  // "je ne peux pas enregistrer l'ordre que j'ai réorganisé") -- la
  // grille défile horizontalement (overflow-x-auto) ; avec une
  // contrainte de distance, les tout premiers pixels d'un geste tactile
  // sont capturés par le défilement natif du conteneur avant que
  // dnd-kit ait la main, donc le glissement ne démarre jamais sur
  // téléphone (le clic "Enregistrer" n'a alors rien de nouveau à
  // enregistrer). Un appui maintenu 150ms laisse le temps à dnd-kit de
  // prendre la main avant tout défilement.
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { delay: 150, tolerance: 8 } }))

  function handleColonneMandatDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (over && active.id !== over.id) reorderColonneMandat(String(active.id), String(over.id))
  }

  function openRuleForm(index: number, titreParDefaut: string) {
    setOpenRuleIdx((prev) => (prev === index ? null : index))
    setRuleFormTitre(titreParDefaut)
    setRuleFormText('')
    setRuleFormError(null)
  }

  async function submitRuleForm(index: number) {
    const titre = ruleFormTitre.trim()
    const demande = ruleFormText.trim()
    if (!orgId || !titre || !demande) return
    setRuleFormSubmitting(true)
    setRuleFormError(null)
    try {
      await createPrelevementRuleRequest(orgId, titre, demande)
      setOpenRuleIdx(null)
      setRuleFormText('')
      setRuleFormSentIdx(index)
      setRuleRequestsRefreshKey((k) => k + 1)
      setTimeout(() => setRuleFormSentIdx(null), 4000)
    } catch (err) {
      setRuleFormError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setRuleFormSubmitting(false)
    }
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
            Dépose l'export CRM brut, télécharge un classeur prêt (4 onglets : Mandat avec tout, FRST et
            RCUR en détail, Exclus avec la raison). Un mandat par produit actif du client, jamais un
            montant groupé. Ne couvre pas encore l'historique/les doublons/les impayés/le relevé bancaire
            — voir le chantier séparé dans le Cockpit.
          </p>

          <Card className="mb-4">
            <CardContent className="flex flex-col gap-3">
              <button
                type="button"
                onClick={() => setReglagesOpen((v) => !v)}
                className="flex w-full items-center justify-between text-sm font-semibold"
              >
                <span>Réglages</span>
                <span className="text-xs font-normal text-[var(--muted)]">{reglagesOpen ? '▲' : '▼'}</span>
              </button>
              {reglagesOpen && (
                <>
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

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {rules && rules.produits_connus.length > 0 && (
                    <div>
                      <p className="mb-1 text-xs text-[var(--muted)]">
                        Frais de dossier par produit (€), au 1er prélèvement.
                      </p>
                      <table className="w-full text-sm">
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
                    <p className="mb-1 text-xs text-[var(--muted)]">
                      Libellés de périodicité -- ajoute/renomme/supprime.
                    </p>
                    <table className="w-full text-sm">
                      <tbody>
                        {Object.entries(periodicites).map(([code, texte]) => (
                          <tr key={code} className="border-t border-[var(--border)] first:border-t-0">
                            <td className="w-20 truncate py-1 pr-1 text-xs text-[var(--muted)]" title={code}>
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
                  </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
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

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-[var(--foreground)]">
                        Colonnes du fichier de mandats -- ordre, visibilité, modèles et règles.
                      </p>
                      <Button variant="secondary" onClick={() => setModelesOpen((v) => !v)}>
                        📊✏️ Modèles tableau <span aria-hidden="true">⚙️</span>
                      </Button>
                    </div>

                    {modelesOpen && (
                      <div className="rounded-md border border-[var(--border)] bg-[var(--card)] shadow-sm">
                        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2.5">
                          <span className="text-sm font-bold">🗂️✏️ Modèles tableau</span>
                          <button
                            type="button"
                            onClick={() => setModelesOpen(false)}
                            aria-label="Fermer"
                            className="px-1 text-[var(--muted)] hover:text-[var(--foreground)]"
                          >
                            ✕
                          </button>
                        </div>

                        {/* Modèles enregistrés (Raphaël, 2026-09-22 : "comme on
                            avait sur Streamlit") -- nommer/modifier/supprimer un
                            modèle, "Sélectionner" pour l'appliquer à la grille
                            de travail ci-dessous ET mémoriser le choix. */}
                        <div className="flex flex-col gap-2 border-b border-[var(--border)] px-4 py-3">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold uppercase tracking-wide text-[var(--muted)]">
                              Modèles enregistrés
                            </span>
                          </div>

                          {colonnesMandatPresets.length === 0 && (
                            <p className="text-xs text-[var(--muted)]">Aucun modèle enregistré pour l'instant.</p>
                          )}
                          {colonnesMandatPresets.length > 0 && (
                            <ul className="flex flex-col gap-1.5">
                              {colonnesMandatPresets.map((p) =>
                                editingPresetId === p.id ? (
                                  <li key={p.id} className="flex items-center gap-2">
                                    <Input
                                      autoFocus
                                      className="h-8 flex-1 px-2 py-1 text-sm"
                                      value={editingPresetName}
                                      onChange={(e) => setEditingPresetName(e.target.value)}
                                      onKeyDown={(e) => {
                                        if (e.key === 'Enter') void commitRenamePreset(p.id)
                                        if (e.key === 'Escape') setEditingPresetId(null)
                                      }}
                                    />
                                    <Button onClick={() => void commitRenamePreset(p.id)}>OK</Button>
                                    <Button variant="secondary" onClick={() => setEditingPresetId(null)}>
                                      Annuler
                                    </Button>
                                  </li>
                                ) : (
                                  <li
                                    key={p.id}
                                    className={
                                      'flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm ' +
                                      (p.id === activePresetId
                                        ? 'border-[var(--primary)] bg-[var(--muted-bg)]'
                                        : 'border-[var(--border)]')
                                    }
                                  >
                                    <span className="flex-1 font-medium">{p.name}</span>
                                    <span className="text-xs text-[var(--muted)]">
                                      {p.colonnes.filter((c) => c.visible).length} colonnes
                                    </span>
                                    <Button
                                      variant={p.id === activePresetId ? 'primary' : 'secondary'}
                                      onClick={() => selectColonnesMandatPreset(p)}
                                    >
                                      {p.id === activePresetId ? '✓ Sélectionné' : 'Sélectionner'}
                                    </Button>
                                    <button
                                      type="button"
                                      onClick={() => startRenamePreset(p)}
                                      aria-label={`Modifier le modèle ${p.name}`}
                                      className="rounded-md border border-[var(--border)] px-2 py-1 text-xs hover:bg-[var(--muted-bg)]"
                                    >
                                      ✏️
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => void handleDeleteColonnesMandatPreset(p.id)}
                                      disabled={deletingPresetId === p.id}
                                      aria-label={`Supprimer le modèle ${p.name}`}
                                      className="rounded-md border border-[var(--danger)] px-2 py-1 text-xs text-[var(--danger)] hover:bg-[var(--muted-bg)]"
                                    >
                                      🗑️
                                    </button>
                                  </li>
                                ),
                              )}
                            </ul>
                          )}

                          <div className="mt-1 flex items-center gap-2">
                            <Input
                              placeholder="Nom du nouveau modèle (ex. Export banque)"
                              className="h-8 flex-1 px-2 py-1"
                              value={newPresetName}
                              onChange={(e) => setNewPresetName(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') void handleSaveColonnesMandatPreset()
                              }}
                            />
                            <Button
                              variant="secondary"
                              onClick={() => void handleSaveColonnesMandatPreset()}
                              disabled={savingPreset || !newPresetName.trim()}
                            >
                              {savingPreset ? 'Création…' : '✏️ Créer un nouveau modèle'}
                            </Button>
                          </div>
                          {presetError && <p className="text-xs text-[var(--danger)]">Erreur : {presetError}</p>}
                        </div>

                        {/* Façon tableur (Raphaël, 2026-09-22 : "un tableau Excel
                            vraiment dans l'aperçu") -- lettres A, B, C... en repère
                            visuel au-dessus de chaque colonne, quelques lignes
                            vides très légères en dessous pour montrer la forme du
                            fichier sans données réelles. */}
                        <div className="flex flex-col gap-3 px-4 py-3">
                          <span className="text-xs font-bold uppercase tracking-wide text-[var(--muted)]">
                            Colonnes du modèle en cours d'édition -- glisse ⠿ pour réordonner, décoche
                            pour masquer.
                          </span>

                          <div className="overflow-x-auto rounded-md border border-[var(--border)]">
                            <DndContext
                              sensors={dndSensors}
                              collisionDetection={closestCenter}
                              onDragEnd={handleColonneMandatDragEnd}
                            >
                              <SortableContext
                                items={colonnesMandat.map((c) => c.cle)}
                                strategy={horizontalListSortingStrategy}
                              >
                                <div className="flex">
                                  {colonnesMandat.map((c, i) => {
                                    const attributedReq = c.rule_request_id
                                      ? ruleRequestsAll.find((r) => r.id === c.rule_request_id)
                                      : undefined
                                    const attributionLabel = c.rule_request_id
                                      ? attributedReq
                                        ? `${RULE_STATUT_ICON[attributedReq.statut]} ${attributedReq.titre}`
                                        : '🔗 règle liée'
                                      : null
                                    return (
                                      <SortableColonneMandatCell
                                        key={c.cle}
                                        colonne={c}
                                        lettre={lettreExcel(i)}
                                        note={
                                          colonnesMandatNotes[c.cle] ??
                                          'Colonne personnalisée -- toujours vide, à remplir après export.'
                                        }
                                        removable={!colonnesMandatCanoniques.includes(c.cle)}
                                        attributionLabel={attributionLabel}
                                        onToggleVisible={() => toggleColonneMandatVisible(c.cle)}
                                        onRemove={() => removeColonneMandatPersonnalisee(c.cle)}
                                        onRename={(nouveauNom) =>
                                          renameColonneMandatPersonnalisee(c.cle, nouveauNom)
                                        }
                                        onOpenAttribute={() => toggleAttribute(c.cle)}
                                      />
                                    )
                                  })}
                                </div>
                              </SortableContext>
                            </DndContext>
                            {[0, 1, 2].map((ligne) => (
                              <div key={ligne} className="flex opacity-30">
                                {colonnesMandat.map((c) => (
                                  <div
                                    key={c.cle}
                                    className="h-5 w-40 flex-shrink-0 border-r border-b border-[var(--border)]"
                                  />
                                ))}
                              </div>
                            ))}
                          </div>

                          {attributingCle && (
                            <div className="flex flex-col gap-2 rounded-md border border-[var(--border)] bg-[var(--muted-bg)] p-3">
                              <span className="text-xs font-bold">
                                Attribuer une règle à la colonne « {attributingCle} »
                              </span>
                              <div className="flex flex-wrap gap-1.5">
                                {ruleRequestsAll
                                  .filter((r) => r.statut !== 'valide')
                                  .map((r) => (
                                    <button
                                      key={r.id}
                                      type="button"
                                      onClick={() => pickExistingRuleForColumn(attributingCle, r.id)}
                                      className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-xs hover:border-[var(--primary)]"
                                    >
                                      {RULE_STATUT_ICON[r.statut]} {r.titre}
                                    </button>
                                  ))}
                                {ruleRequestsAll.filter((r) => r.statut !== 'valide').length === 0 && (
                                  <span className="text-xs text-[var(--muted)]">
                                    Aucune règle en attente pour l'instant.
                                  </span>
                                )}
                              </div>
                              <div className="h-px bg-[var(--border)]" />
                              <span className="text-xs text-[var(--muted)]">
                                Aucune règle ne correspond ? Décris-la, elle sera codée à la prochaine session.
                              </span>
                              <Input
                                className="h-8 px-2 py-1 font-bold"
                                placeholder="Titre de la règle"
                                value={newRuleForColumnTitre}
                                onChange={(e) => setNewRuleForColumnTitre(e.target.value)}
                              />
                              <div className="flex items-center gap-2">
                                <Input
                                  placeholder="Ex. TVA à 20% si société assujettie"
                                  className="h-8 flex-1 px-2 py-1"
                                  value={newRuleForColumnText}
                                  onChange={(e) => setNewRuleForColumnText(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') void submitNewRuleForColumn(attributingCle)
                                  }}
                                />
                                <Button
                                  onClick={() => void submitNewRuleForColumn(attributingCle)}
                                  disabled={
                                    creatingRuleForColumn ||
                                    !newRuleForColumnTitre.trim() ||
                                    !newRuleForColumnText.trim()
                                  }
                                >
                                  {creatingRuleForColumn ? 'Création…' : '➕ Créer la règle'}
                                </Button>
                              </div>
                              {ruleAttributionError && (
                                <p className="text-xs text-[var(--danger)]">Erreur : {ruleAttributionError}</p>
                              )}
                            </div>
                          )}

                          {ruleAttributedNotice && (
                            <div className="rounded-md border border-[var(--success)] bg-[var(--muted-bg)] p-2.5 text-xs text-[var(--success)]">
                              ✅ Règle créée -- visible dans "Règles appliquées par le moteur &rsaquo; + nouvelles
                              règles" et traitée à la prochaine session Claude Code. Une fois codée, elle rejoint
                              "Règles appliquées" automatiquement, comme les autres.
                            </div>
                          )}

                          <div className="flex items-center gap-2">
                            <Input
                              placeholder="Nom de la nouvelle colonne (ex. Code société)"
                              className="h-8 max-w-xs px-2 py-1"
                              value={newColonneMandat}
                              onChange={(e) => setNewColonneMandat(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') addColonneMandat()
                              }}
                            />
                            <Button
                              variant="secondary"
                              onClick={addColonneMandat}
                              disabled={!newColonneMandat.trim()}
                            >
                              ➕ Ajouter une colonne
                            </Button>
                          </div>
                          <p className="text-xs text-[var(--muted)]">
                            Une colonne ajoutée est toujours vide dans le fichier généré (aucune source dans le
                            CRM) -- à remplir toi-même après export, ou attribue-lui une règle ci-dessus.
                          </p>

                          <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] pt-3">
                            {!activePresetId && (
                              <span className="text-xs text-[var(--muted)]">
                                Sélectionne ou crée un modèle pour pouvoir l'enregistrer avec ces colonnes.
                              </span>
                            )}
                            <Button
                              onClick={() => void handleSaveActivePresetColonnes()}
                              disabled={!activePresetId || savingPresetColonnes}
                            >
                              {savingPresetColonnes ? 'Enregistrement…' : '💾 Enregistrer'}
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}
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
                <span className="flex items-center gap-2">
                  <span>📋 Règles appliquées par le moteur</span>
                  {ruleRequestsAll.some((r) => r.questions.some((q) => !q.answered_at)) ? (
                    <span className="rounded-full bg-[var(--danger)] px-2 py-0.5 text-xs font-bold text-white">
                      🔴 Réponse attendue
                    </span>
                  ) : (
                    ruleRequestsAll.some((r) => r.statut !== 'valide') && (
                      <span className="rounded-full bg-[var(--primary)] px-2 py-0.5 text-xs font-medium text-[var(--primary-foreground)]">
                        {ruleRequestsAll.filter((r) => r.statut !== 'valide').length} en cours
                      </span>
                    )
                  )}
                </span>
                <span className="text-[var(--muted)]">{rulesExplainOpen ? '▲' : '▼'}</span>
              </button>
              {rulesExplainOpen && (
                <div className="flex flex-col gap-3 border-t border-[var(--border)] p-3">
                  <p className="text-xs text-[var(--muted)]">
                    Ce que le code applique réellement à chaque génération -- pour repérer une
                    future erreur ou décider qu'une règle doit changer. Reflète tes réglages
                    ci-dessus (frais, délai).
                  </p>
                  {rules.explication.map((r, i) => {
                    const latestReq = latestRuleRequestFor(r.titre)
                    const pendingQuestions = latestReq?.questions.filter((q) => !q.answered_at) ?? []
                    return (
                    <div key={i}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="flex items-center gap-2">
                          <p className="text-sm font-bold text-[var(--foreground)]">{r.titre}</p>
                          {pendingQuestions.length > 0 ? (
                            <span className="rounded-md bg-[var(--danger)] px-2 py-0.5 text-xs font-bold text-white">
                              🔴 Ta réponse est nécessaire
                            </span>
                          ) : (
                            latestReq && (
                              <span className="text-xs font-medium text-[var(--muted)]">
                                {STATUT_BADGE[latestReq.statut]}
                              </span>
                            )
                          )}
                        </span>
                        <button
                          type="button"
                          onClick={() => openRuleForm(i, r.titre)}
                          className="text-xs text-[var(--primary)] hover:underline"
                        >
                          {openRuleIdx === i ? 'Annuler' : '✏️ Demander une modification'}
                        </button>
                      </div>
                      <p className="text-sm text-[var(--muted)]">{r.detail}</p>

                      {orgId && latestReq && pendingQuestions.map((q) => (
                        <RuleQuestionBlock
                          key={q.id}
                          orgId={orgId}
                          requestId={latestReq.id}
                          question={q}
                          onAnswered={() => setRuleRequestsRefreshKey((k) => k + 1)}
                        />
                      ))}

                      {ruleFormSentIdx === i && openRuleIdx !== i && (
                        <p className="mt-1 text-xs text-[var(--success)]">
                          ✅ Demande enregistrée, visible dans "Demandes de modification de règles"
                          ci-dessous.
                        </p>
                      )}

                      {openRuleIdx === i && (
                        <div className="mt-2 flex flex-col gap-2 rounded-md border border-[var(--border)] p-2">
                          <Input
                            className="font-bold"
                            placeholder="Titre de la règle"
                            value={ruleFormTitre}
                            onChange={(e) => setRuleFormTitre(e.target.value)}
                          />
                          <textarea
                            autoFocus
                            className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] p-2 text-sm"
                            rows={2}
                            placeholder="Changement souhaité pour cette règle, en détail..."
                            value={ruleFormText}
                            onChange={(e) => setRuleFormText(e.target.value)}
                          />
                          {ruleFormError && (
                            <p className="text-xs text-[var(--danger)]">Erreur : {ruleFormError}</p>
                          )}
                          <div>
                            <Button
                              onClick={() => void submitRuleForm(i)}
                              disabled={ruleFormSubmitting || !ruleFormTitre.trim() || !ruleFormText.trim()}
                            >
                              {ruleFormSubmitting ? 'Enregistrement…' : 'Envoyer la demande'}
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                    )
                  })}

                  {orgId && <PrelevementRuleRequests orgId={orgId} refreshKey={ruleRequestsRefreshKey} />}
                </div>
              )}
            </div>
          )}

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
                        <td className="pr-4 py-0.5 text-[var(--muted)]">Mandats FRST (1er prélèvement)</td>
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
                          <td className="pr-4 py-0.5 text-[var(--muted)]">Mandats fusionnés (produits cumulés)</td>
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
