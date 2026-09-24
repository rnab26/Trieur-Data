import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  answerPrelevementRuleRequestQuestion,
  createPrelevementRuleRequest,
  deletePrelevementRuleRequest,
  listPrelevementRuleRequests,
  updatePrelevementRuleRequest,
  type PrelevementRuleRequest,
  type RuleRequestQuestion,
  type RuleRequestStatut,
} from '@/lib/api'

// "il faut s'en rapprocher le plus possible [d'une session avec toi]"
// (Raphaël, 2026-09-22) : le père de Raphaël ne voit une demande
// avancer qu'après coup, au statut suivant (⏳ -> 🔧 -> ✅), sans savoir
// ce qui se passe entre-temps. Ce fil affiche, sous chaque demande, les
// messages courts qu'une session Claude Code note en travaillant
// dessus ("je regarde le code existant", "PR créée, CI en cours"...) --
// pas un vrai chat (pas de réponse possible ici, voir RuleQuestionBlock
// pour ça), juste la narration en quasi direct de ce qui se passe.
function formatEventTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// Réponse à une question à choix cliquables posée par une session
// Claude Code sur une demande de règle ambiguë -- même principe que
// ChantierCard/QuestionBlock côté Cockpit. Une réponse libre (le champ
// commentaire) reste toujours possible en plus des options.
//
// Version compacte (2026-09-24, retour de Raphaël sur la 1ère version :
// "fais-moi un truc propre [...] c'est juste qu'il y a un code couleur
// qui change") -- un simple encadré fin (contour rouge, pas de bandeau
// plein pleine largeur) au lieu d'une grosse boîte à bandeau.
export function RuleQuestionBlock({
  orgId,
  requestId,
  question,
  onAnswered,
}: {
  orgId: string
  requestId: string
  question: RuleRequestQuestion
  onAnswered: () => void
}) {
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Une option qui dit "préciser" n'est pas une réponse en soi -- juste
  // cliquer dessus l'envoyait quand même, avec le champ libre encore
  // vide la plupart du temps (bug réel signalé par Raphaël : des
  // réponses "pas prises en compte", parce qu'elles partaient avant
  // qu'il ait eu le temps de taper). Pour ces options-là, le clic
  // n'envoie plus rien : il sélectionne l'option et donne le focus au
  // champ, qui doit être rempli avant un bouton "Valider" séparé.
  const [optionAPreciser, setOptionAPreciser] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function submit(option: string, commentaire: string | null) {
    setSubmitting(true)
    setError(null)
    try {
      await answerPrelevementRuleRequestQuestion(orgId, requestId, question.id, option, commentaire)
      onAnswered()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleChoose(option: string) {
    if (option.toLowerCase().includes('préciser')) {
      setOptionAPreciser(option)
      // Laisse le temps au champ d'apparaître/se activer avant le focus.
      setTimeout(() => inputRef.current?.focus(), 0)
      return
    }
    void submit(option, comment.trim() || null)
  }

  function handleValiderPrecision() {
    if (!optionAPreciser || !comment.trim()) return
    void submit(optionAPreciser, comment.trim())
  }

  return (
    <div className="mt-1.5 rounded-lg p-2 text-xs shadow-[inset_0_0_0_1px_var(--danger)]">
      <p className="mb-1 font-bold text-[var(--danger)]">🔴 Réponse attendue</p>
      <p className="font-medium">{question.question}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {question.options.map((option) => (
          <Button
            key={option}
            type="button"
            variant={optionAPreciser === option ? 'primary' : 'secondary'}
            disabled={submitting}
            onClick={() => handleChoose(option)}
          >
            {option}
          </Button>
        ))}
      </div>
      <Input
        ref={inputRef}
        className="mt-1.5"
        placeholder={optionAPreciser ? 'Écris ta précision ici, puis valide ci-dessous…' : 'Préciser ta réponse (optionnel)…'}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {optionAPreciser && (
        <div className="mt-1.5">
          <Button type="button" disabled={submitting || !comment.trim()} onClick={handleValiderPrecision}>
            {submitting ? 'Enregistrement…' : '✅ Valider cette réponse'}
          </Button>
        </div>
      )}
      {error && <p className="mt-1 text-[var(--danger)]">Erreur : {error}</p>}
    </div>
  )
}

// Validation fonctionnelle par un humain (Raphaël, 2026-09-22 : "il faut
// vraiment établir un vrai système clair net et précis question réponse
// [...] bouton règle validé par l'admin fonctionnel sinon bouton à
// modifier/corriger [...] pas de doublon"). Avant : une session Claude
// Code passait seule une demande codée à "valide", sans qu'un humain ne
// confirme que ça marche vraiment -- et quand ça ne marchait pas, une
// NOUVELLE demande était recréée au lieu de corriger celle-ci (doublons).
//
// Deux modes (Raphaël, 2026-09-22 -- "une règle utilisée qui ne
// fonctionne pas, si on demande de la modifier ou la corriger, elle
// repasse dans le bloc d'en bas") :
// - "a_verifier" (codé + déployé, pas encore confirmé) : soit ça marche
//   (✅ Valider, statut -> valide), soit non (✏️ Corriger).
// - "valide" (déjà certifiée, mais un problème est découvert plus tard,
//   à tout moment) : juste "✏️ Signaler un problème / corriger", pas
//   besoin de revalider ce qui l'était déjà.
// Dans les deux cas, corriger ajoute la précision à LA MÊME demande et
// repasse son statut à "en_cours" -- jamais une nouvelle ligne.
//
// Version compacte (2026-09-24) : même encadré fin que RuleQuestionBlock,
// contour orange au lieu d'un bandeau plein pleine largeur.
function ValidationBlock({
  orgId,
  request,
  mode,
  onValidated,
  onCorrected,
}: {
  orgId: string
  request: PrelevementRuleRequest
  mode: 'a_verifier' | 'valide'
  onValidated: () => void
  onCorrected: (demande: string) => void
}) {
  const [correcting, setCorrecting] = useState(false)
  const [correctionText, setCorrectionText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleValider() {
    setSubmitting(true)
    setError(null)
    try {
      await updatePrelevementRuleRequest(orgId, request.id, { statut: 'valide' })
      onValidated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      setSubmitting(false)
    }
  }

  async function handleCorriger() {
    const precision = correctionText.trim()
    if (!precision) return
    setSubmitting(true)
    setError(null)
    try {
      const demande =
        `${request.demande}\n\n--- Correction du ${new Date().toLocaleDateString('fr-FR')} ` +
        `(cette règle a été codée mais ne fonctionne pas comme attendu) ---\n${precision}`
      await updatePrelevementRuleRequest(orgId, request.id, { demande, statut: 'en_cours' })
      onCorrected(demande)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      setSubmitting(false)
    }
  }

  if (mode === 'valide') {
    return (
      <div className="mt-1.5 text-xs">
        {!correcting ? (
          <button
            type="button"
            onClick={() => setCorrecting(true)}
            className="text-[var(--primary)] hover:underline"
          >
            ✏️ Signaler un problème / demander une correction
          </button>
        ) : (
          <div className="rounded-lg p-2 shadow-[inset_0_0_0_1px_var(--warning)]">
            <p className="mb-1 font-bold text-[var(--warning)]">🧪 Qu'est-ce qui ne va pas ?</p>
            <div className="flex flex-col gap-1.5">
              <textarea
                className="w-full rounded-lg bg-[var(--card)] p-1.5 text-xs shadow-[var(--ring-card)]"
                rows={2}
                value={correctionText}
                onChange={(e) => setCorrectionText(e.target.value)}
                autoFocus
              />
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  disabled={submitting || !correctionText.trim()}
                  onClick={() => void handleCorriger()}
                >
                  {submitting ? 'Enregistrement…' : '📩 Envoyer la correction'}
                </Button>
                <Button type="button" variant="secondary" disabled={submitting} onClick={() => setCorrecting(false)}>
                  Annuler
                </Button>
              </div>
            </div>
            {error && <p className="mt-1 text-[var(--danger)]">Erreur : {error}</p>}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="mt-1.5 rounded-lg p-2 text-xs shadow-[inset_0_0_0_1px_var(--warning)]">
      <p className="mb-1 font-bold text-[var(--warning)]">🧪 Codée et déployée — fonctionne-t-elle comme attendu ?</p>
      {!correcting ? (
        <div className="flex flex-wrap gap-1.5">
          <Button type="button" disabled={submitting} onClick={() => void handleValider()}>
            {submitting ? 'Enregistrement…' : '✅ Ça fonctionne, je certifie'}
          </Button>
          <Button type="button" variant="secondary" disabled={submitting} onClick={() => setCorrecting(true)}>
            ✏️ Ça ne marche pas, corriger
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <textarea
            className="w-full rounded-lg bg-[var(--card)] p-1.5 text-xs shadow-[var(--ring-card)]"
            rows={2}
            placeholder="Qu'est-ce qui ne va pas ? Sois précis (exemple concret si possible)..."
            value={correctionText}
            onChange={(e) => setCorrectionText(e.target.value)}
            autoFocus
          />
          <div className="flex gap-1.5">
            <Button
              type="button"
              disabled={submitting || !correctionText.trim()}
              onClick={() => void handleCorriger()}
            >
              {submitting ? 'Enregistrement…' : '📩 Envoyer la correction'}
            </Button>
            <Button type="button" variant="secondary" disabled={submitting} onClick={() => setCorrecting(false)}>
              Annuler
            </Button>
          </div>
        </div>
      )}
      {error && <p className="mt-1 text-[var(--danger)]">Erreur : {error}</p>}
    </div>
  )
}

// Historique chronologique unifié d'une demande (2026-09-24, Raphaël :
// "les requêtes, les demandes de modification, les questions, les
// réponses, les mettre dans l'ordre chronologique [...] uniquement si on
// souhaite déplier ça") -- remplace les deux blocs séparés
// AnsweredQuestions + ActivityFeed (l'un au-dessus de l'autre, sans lien
// temporel entre eux) par une seule liste triée dans le temps, repliée
// par défaut. Une question répondue et un message d'activité n'ont pas
// le même contenu (Q/R vs. simple message) mais partagent le même
// principe d'affichage compact : date + contenu, une ligne.
type HistoryItem = { ts: string; node: ReactNode }

function buildHistory(r: PrelevementRuleRequest): HistoryItem[] {
  const items: HistoryItem[] = []
  for (const q of r.questions) {
    if (!q.answered_at) continue
    items.push({
      ts: q.answered_at,
      node: (
        <>
          <p className="text-[var(--muted)]">{q.question}</p>
          <p className="mt-0.5 font-medium">→ {q.answer}</p>
          {q.comment && <p className="mt-0.5 text-[var(--muted)]">Précision : {q.comment}</p>}
        </>
      ),
    })
  }
  for (const e of r.events) {
    items.push({ ts: e.created_at, node: <p>{e.message}</p> })
  }
  return items.sort((a, b) => a.ts.localeCompare(b.ts))
}

function RuleHistory({ request }: { request: PrelevementRuleRequest }) {
  const [open, setOpen] = useState(false)
  const items = buildHistory(request)
  if (items.length === 0) return null
  return (
    <div className="mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
      >
        {open ? '▲' : '▼'} Historique ({items.length})
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-1">
          {items.map((item, i) => (
            <li key={i} className="rounded-lg bg-[var(--card)] p-1.5 text-xs shadow-[var(--ring-card)]">
              <span className="text-[var(--muted)]">{formatEventTime(item.ts)}</span>
              <div className="mt-0.5">{item.node}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// Bouton crayon compact, toujours le même partout dans ce fichier --
// clique = entre en édition. Retour de Raphaël (2026-09-24) sur la 1ère
// version des cartes : titre/résumé/demande ne doivent PLUS être des
// champs texte directement modifiables en permanence ("je peux écrire
// tout n'importe quoi, faire des erreurs de manipulation") -- affichage
// en texte simple par défaut (qui passe à la ligne normalement, contrairement
// à un <input>), un crayon à côté pour entrer en édition explicitement.
function EditPencil({ onClick, title }: { onClick: () => void; title: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="shrink-0 rounded p-0.5 text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
    >
      ✏️
    </button>
  )
}

// Carte compacte d'une règle certifiée (2026-09-24, Raphaël : "une petite
// box légère, pas besoin de mettre tout en vert sur vert -- tu mets juste
// la règle en noir, un petit logo vérifié/certifié en vert, le titre en
// gras propre, fin" -- 2e passe après un premier essai jugé "hyper gros,
// hyper épais"). Définie au niveau module (pas dans le corps de
// PrelevementRuleRequests) : sinon une nouvelle "fonction composant"
// serait recréée à chaque rendu du parent (le polling 15s en
// particulier) et React démonterait/remonterait la carte à chaque fois,
// perdant son état "déplié"/"en édition" -- même bug de fond que celui
// déjà corrigé pour le scroll (markScroll), juste sur l'ouverture/
// fermeture au lieu de la position de la page.
function CertifiedRuleCard({
  orgId,
  request: r,
  savingId,
  confirmingDelete,
  onConfirmDeleteToggle,
  onDelete,
  onFieldBlur,
  onCorrected,
}: {
  orgId: string
  request: PrelevementRuleRequest
  savingId: string | null
  confirmingDelete: boolean
  onConfirmDeleteToggle: (id: string | null) => void
  onDelete: (id: string) => void
  onFieldBlur: (id: string, field: 'titre' | 'demande' | 'resume', value: string, original: string) => void
  onCorrected: (id: string, demande: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [titreDraft, setTitreDraft] = useState(r.titre)
  const [resumeDraft, setResumeDraft] = useState(r.resume ?? '')
  const canReportProblem = r.questions.every((q) => q.answered_at)

  function startEditing() {
    setTitreDraft(r.titre)
    setResumeDraft(r.resume ?? '')
    setEditing(true)
  }
  function finishEditing() {
    const titre = titreDraft.trim()
    const resume = resumeDraft.trim()
    if (titre && titre !== r.titre) onFieldBlur(r.id, 'titre', titre, r.titre)
    if (resume !== (r.resume ?? '')) onFieldBlur(r.id, 'resume', resume, r.resume ?? '')
    setEditing(false)
  }

  return (
    <li className="rounded-lg px-2.5 py-1.5 shadow-[inset_2px_0_0_var(--success),var(--ring-card)]">
      <div className="flex items-start gap-1.5">
        <span title="Certifiée -- ne sera plus retouchée" className="mt-0.5 shrink-0 text-sm leading-none">
          ✅
        </span>
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex flex-col gap-1">
              <Input
                className="font-bold"
                value={titreDraft}
                disabled={savingId === r.id}
                onChange={(e) => setTitreDraft(e.target.value)}
                autoFocus
              />
              <textarea
                className="w-full rounded-lg bg-[var(--card)] p-1.5 text-xs shadow-[var(--ring-card)]"
                rows={2}
                placeholder="Résumé simple : à quoi sert cette règle, en une phrase sans jargon…"
                value={resumeDraft}
                disabled={savingId === r.id}
                onChange={(e) => setResumeDraft(e.target.value)}
              />
              <div>
                <Button type="button" disabled={savingId === r.id || !titreDraft.trim()} onClick={finishEditing}>
                  ✓ Terminé
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-sm font-semibold leading-snug break-words">{r.titre}</p>
              <p className="text-xs leading-snug text-[var(--muted)]">
                {r.resume || 'Pas encore de résumé -- clique sur ✏️ pour en ajouter un.'}
              </p>
            </>
          )}
        </div>
        {!editing && (
          <div className="flex shrink-0 items-center gap-1">
            <EditPencil onClick={startEditing} title="Modifier le titre / le résumé" />
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="text-xs text-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {open ? '▲' : '▼'}
            </button>
          </div>
        )}
      </div>
      {open && (
        <div className="mt-1.5 flex flex-col gap-1.5 border-t border-[var(--border)] pt-1.5 text-xs">
          <div>
            <p className="mb-0.5 font-medium text-[var(--muted)]">Demande d'origine :</p>
            <p className="whitespace-pre-wrap text-[var(--foreground)]">{r.demande}</p>
          </div>
          {canReportProblem && (
            <ValidationBlock
              orgId={orgId}
              request={r}
              mode="valide"
              onValidated={() => {}}
              onCorrected={(demande) => onCorrected(r.id, demande)}
            />
          )}
          <RuleHistory request={r} />
          <div className="mt-0.5 flex items-center justify-between">
            <span className="text-[var(--muted)]">
              Créée le {formatEventTime(r.created_at)}
              {r.updated_at !== r.created_at && ` -- modifiée le ${formatEventTime(r.updated_at)}`}
            </span>
            {confirmingDelete ? (
              <span className="flex items-center gap-1">
                <Button variant="danger" disabled={savingId === r.id} onClick={() => onDelete(r.id)}>
                  Confirmer
                </Button>
                <Button variant="secondary" onClick={() => onConfirmDeleteToggle(null)}>
                  Annuler
                </Button>
              </span>
            ) : (
              <Button variant="danger" onClick={() => onConfirmDeleteToggle(r.id)}>
                🗑️
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  )
}

// Statut affiché seulement quand il n'y a AUCUNE question en attente sur
// la demande -- une question en attente prime toujours sur le statut
// (voir renderStatutBadge ci-dessous), pour ne jamais laisser croire
// "en cours de codage" alors qu'une réponse est en fait attendue.
const STATUT_LABEL: Record<RuleRequestStatut, string> = {
  en_attente: '⏳ Pas encore examinée',
  en_cours: '🔧 En cours de codage',
  a_verifier: '🧪 Codée -- à vérifier',
  valide: '✅ Certifiée',
}

const STATUT_COLOR: Record<RuleRequestStatut, string> = {
  en_attente: 'text-[var(--muted)]',
  en_cours: 'text-[var(--primary)]',
  a_verifier: 'text-[var(--warning)]',
  valide: 'text-[var(--success)]',
}

// Carte compacte d'une règle pas encore certifiée (en_attente/en_cours/
// a_verifier) -- même principe que CertifiedRuleCard (texte simple qui
// passe à la ligne, édition via un crayon explicite, pas de gros bandeau
// coloré), juste le code couleur qui change selon ce qui attend une
// action (Raphaël, 2026-09-24 : "pareil pour les questions [...] c'est
// juste qu'il y a un code couleur qui change"). Composant au niveau
// module pour la même raison que CertifiedRuleCard (polling 15s).
function RuleCard({
  orgId,
  request: r,
  savingId,
  confirmingDelete,
  onConfirmDeleteToggle,
  onDelete,
  onFieldBlur,
  onQuestionAnswered,
  onValidated,
  onCorrected,
}: {
  orgId: string
  request: PrelevementRuleRequest
  savingId: string | null
  confirmingDelete: boolean
  onConfirmDeleteToggle: (id: string | null) => void
  onDelete: (id: string) => void
  onFieldBlur: (id: string, field: 'titre' | 'demande' | 'resume', value: string, original: string) => void
  onQuestionAnswered: () => void
  onValidated: (id: string) => void
  onCorrected: (id: string, demande: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [titreDraft, setTitreDraft] = useState(r.titre)
  const [demandeDraft, setDemandeDraft] = useState(r.demande)
  const pendingQuestions = r.questions.filter((q) => !q.answered_at)
  const awaitingValidation = pendingQuestions.length === 0 && r.statut === 'a_verifier'
  // Contour fin, code couleur seulement (pas de fond teinté) -- rouge =
  // bloquant, orange = à vérifier, neutre sinon.
  const accentClass = pendingQuestions.length > 0
    ? 'shadow-[inset_2px_0_0_var(--danger),var(--ring-card)]'
    : awaitingValidation
      ? 'shadow-[inset_2px_0_0_var(--warning),var(--ring-card)]'
      : 'shadow-[var(--ring-card)]'

  function startEditing() {
    setTitreDraft(r.titre)
    setDemandeDraft(r.demande)
    setEditing(true)
  }
  function finishEditing() {
    const titre = titreDraft.trim()
    const demande = demandeDraft.trim()
    if (titre && titre !== r.titre) onFieldBlur(r.id, 'titre', titre, r.titre)
    if (demande && demande !== r.demande) onFieldBlur(r.id, 'demande', demande, r.demande)
    setEditing(false)
  }

  return (
    <li className={'rounded-lg px-2.5 py-1.5 ' + accentClass}>
      <div className="flex items-start gap-1.5">
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex flex-col gap-1">
              <Input
                className="font-bold"
                value={titreDraft}
                disabled={savingId === r.id}
                onChange={(e) => setTitreDraft(e.target.value)}
                autoFocus
              />
              <textarea
                className="w-full rounded-lg bg-[var(--card)] p-1.5 text-xs shadow-[var(--ring-card)]"
                rows={2}
                value={demandeDraft}
                disabled={savingId === r.id}
                onChange={(e) => setDemandeDraft(e.target.value)}
              />
              <div>
                <Button type="button" disabled={savingId === r.id || !titreDraft.trim() || !demandeDraft.trim()} onClick={finishEditing}>
                  ✓ Terminé
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-sm font-semibold leading-snug break-words">{r.titre}</p>
              <p className="whitespace-pre-wrap text-xs leading-snug text-[var(--muted)]">{r.demande}</p>
            </>
          )}
        </div>
        {!editing && (
          <div className="flex shrink-0 items-center gap-1.5">
            {pendingQuestions.length > 0 ? (
              <span className="rounded-full bg-[var(--danger)] px-2 py-0.5 text-[0.65rem] font-bold text-white">
                🔴 Réponse attendue
              </span>
            ) : (
              // Lecture seule -- le statut est décidé par la session
              // Claude Code qui code la règle, jamais par Raphaël ou
              // son père (retour explicite : "les statuts sont à
              // statuer par toi, pas par moi").
              <span
                className={'rounded-full bg-[var(--card)] px-2 py-0.5 text-[0.65rem] font-semibold shadow-[inset_0_0_0_1px_currentColor] ' + STATUT_COLOR[r.statut]}
              >
                {STATUT_LABEL[r.statut]}
              </span>
            )}
            <EditPencil onClick={startEditing} title="Modifier le titre / la demande" />
          </div>
        )}
      </div>
      {pendingQuestions.map((q) => (
        <RuleQuestionBlock key={q.id} orgId={orgId} requestId={r.id} question={q} onAnswered={onQuestionAnswered} />
      ))}
      {awaitingValidation && (
        <ValidationBlock
          orgId={orgId}
          request={r}
          mode="a_verifier"
          onValidated={() => onValidated(r.id)}
          onCorrected={(demande) => onCorrected(r.id, demande)}
        />
      )}
      <RuleHistory request={r} />
      <div className="mt-1 flex items-center justify-between text-xs">
        <span className="text-[var(--muted)]">
          Créée le {formatEventTime(r.created_at)}
          {r.updated_at !== r.created_at && ` -- modifiée le ${formatEventTime(r.updated_at)}`}
        </span>
        {confirmingDelete ? (
          <span className="flex items-center gap-1">
            <Button variant="danger" disabled={savingId === r.id} onClick={() => onDelete(r.id)}>
              Confirmer
            </Button>
            <Button variant="secondary" onClick={() => onConfirmDeleteToggle(null)}>
              Annuler
            </Button>
          </span>
        ) : (
          <Button variant="danger" onClick={() => onConfirmDeleteToggle(r.id)}>
            🗑️
          </Button>
        )}
      </div>
    </li>
  )
}

// Demandes de modification des règles codées en dur du moteur
// (exclusions, FRST/RCUR, liste des produits...) -- intégré DANS le
// panneau "📋 Règles appliquées par le moteur" (Raphaël, 2026-09-22 :
// "pas de pollution visuelle", plus une section à part). L'historique
// (les demandes déjà créées) est replié par défaut, à dérouler --
// seule la nouvelle demande "règle qui n'existe pas encore" reste
// visible d'entrée, c'est l'action, pas l'historique.
export function PrelevementRuleRequests({
  orgId,
  refreshKey,
}: {
  orgId: string
  // Incrémenté par le parent après un ajout fait depuis le formulaire
  // inline sous une règle du panneau "Règles appliquées par le moteur"
  // -- fait recharger sans dupliquer la logique de récupération.
  refreshKey?: number
}) {
  const [requests, setRequests] = useState<PrelevementRuleRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  // Une question en attente est une ACTION à faire, pas de l'historique
  // -- dérouler automatiquement dès qu'il y en a une, pour ne jamais la
  // cacher derrière un clic (bug réel signalé par Raphaël : son père ne
  // trouvait pas où répondre).
  const hasPendingQuestion = requests.some((r) => r.questions.some((q) => !q.answered_at))
  // Même logique que hasPendingQuestion : une règle codée en attente de
  // validation fonctionnelle est aussi une ACTION à faire, pas de
  // l'historique.
  const hasPendingValidation = requests.some((r) => r.statut === 'a_verifier')

  const [newTitre, setNewTitre] = useState('')
  const [newDemande, setNewDemande] = useState('')
  const [creating, setCreating] = useState(false)

  const [savingId, setSavingId] = useState<string | null>(null)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  // Bump manuel après une réponse à une question -- même mécanisme que
  // refreshKey (venant du parent), pour recharger sans dupliquer la
  // logique de récupération.
  const [reloadNonce, setReloadNonce] = useState(0)

  // Bug réel signalé par Raphaël ("la page saute et je dois revenir
  // dessus") : répondre à une question, créer une demande ou modifier
  // un champ recharge toute la liste -- la carte concernée change de
  // hauteur (question qui disparaît, nouvelle carte qui apparaît...),
  // ce qui déplace tout ce qui est en dessous et fait sauter le
  // scroll. markScroll() note la position juste avant une action qui va
  // recharger ; le useLayoutEffect la restaure juste après, avant que
  // le navigateur peigne le nouveau rendu (donc sans clignotement).
  const scrollToRestore = useRef<number | null>(null)
  function markScroll() {
    scrollToRestore.current = window.scrollY
  }
  useLayoutEffect(() => {
    if (scrollToRestore.current !== null) {
      window.scrollTo(0, scrollToRestore.current)
      scrollToRestore.current = null
    }
  })

  useEffect(() => {
    let cancelled = false
    function load(showSpinner: boolean) {
      if (showSpinner) {
        setLoading(true)
        setError(null)
      }
      listPrelevementRuleRequests(orgId)
        .then((data) => {
          if (!cancelled) {
            setRequests(data)
            setError(null)
          }
        })
        .catch((err: unknown) => {
          // Silencieux pour le rafraîchissement automatique en arrière-plan
          // (showSpinner=false) -- une erreur réseau ponctuelle toutes les
          // 15s ne doit pas remplacer l'écran par un message d'erreur tant
          // que le dernier chargement réussi reste affiché.
          if (!cancelled && showSpinner) setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    }
    load(true)
    // Rapprocher le fil d'activité d'un vrai chat (Raphaël, 2026-09-22) :
    // pas de vrai temps réel (Supabase Realtime non câblé ici), mais un
    // polling léger pour voir les messages de la session Claude Code
    // apparaître sans avoir à recharger la page.
    const interval = setInterval(() => load(false), 15000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [orgId, refreshKey, reloadNonce])

  useEffect(() => {
    if (hasPendingQuestion || hasPendingValidation) setHistoryOpen(true)
  }, [hasPendingQuestion, hasPendingValidation])

  async function handleCreate() {
    const titre = newTitre.trim()
    const demande = newDemande.trim()
    if (!titre || !demande) return
    markScroll()
    setCreating(true)
    setError(null)
    try {
      // L'API de création ne renvoie pas les sous-listes questions/events
      // (pas d'embed sur cet endpoint) -- une demande neuve n'en a de
      // toute façon aucune.
      const created = await createPrelevementRuleRequest(orgId, titre, demande)
      setRequests((prev) => [...prev, { ...created, questions: [], events: [] }])
      setNewTitre('')
      setNewDemande('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setCreating(false)
    }
  }

  async function persist(
    id: string,
    patch: Partial<{ titre: string; demande: string; resume: string; statut: RuleRequestStatut }>,
  ) {
    markScroll()
    setSavingId(id)
    setError(null)
    try {
      // Bug réel trouvé en cours de route : l'API de modification ne
      // renvoie pas non plus questions/events -- remplacer l'objet entier
      // par `updated` les effaçait silencieusement de l'écran après un
      // simple renommage, jusqu'au rechargement suivant. Fusion au lieu
      // de remplacement : seuls les champs modifiés changent.
      const updated = await updatePrelevementRuleRequest(orgId, id, patch)
      setRequests((prev) => prev.map((r) => (r.id === id ? { ...r, ...updated } : r)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingId(null)
    }
  }

  // Sauvegarde directe (pas de frappe locale intermédiaire à répercuter
  // pendant la saisie) : le champ édité vit dans l'état local du
  // formulaire d'édition (RuleCard/CertifiedRuleCard), pas dans
  // `requests` -- seul le résultat final ("✓ Terminé") remonte ici.
  function handleFieldBlur(id: string, field: 'titre' | 'demande' | 'resume', value: string, original: string) {
    if (field !== 'resume' && !value) return // titre/demande jamais vides
    if (value !== original) void persist(id, { [field]: value })
  }

  async function handleDelete(id: string) {
    markScroll()
    setSavingId(id)
    setError(null)
    try {
      await deletePrelevementRuleRequest(orgId, id)
      setRequests((prev) => prev.filter((r) => r.id !== id))
      setConfirmingDeleteId(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingId(null)
    }
  }

  const nonValidees = requests.filter((r) => r.statut !== 'valide').length
  const nbPendingQuestions = requests.reduce((n, r) => n + r.questions.filter((q) => !q.answered_at).length, 0)
  const nbAwaitingValidation = requests.filter((r) => r.statut === 'a_verifier').length
  // Vue générale ("soit sur chaque règle... soit générale", Raphaël,
  // 2026-09-22) : le dernier message toutes demandes en_cours confondues,
  // visible sans dérouler l'historique ni ouvrir une demande en
  // particulier -- "qu'est-ce que Claude est en train de faire là,
  // maintenant".
  const latestActivity = requests
    .filter((r) => r.statut === 'en_cours')
    .flatMap((r) => r.events.map((e) => ({ requestTitre: r.titre, event: e })))
    .sort((a, b) => b.event.created_at.localeCompare(a.event.created_at))[0]
  // Comment éviter les doublons de règles (retour de Raphaël) : avertit
  // dès que le titre en cours de frappe ressemble à une demande déjà
  // créée, avant même de cliquer "Ajouter" -- jamais bloquant, juste un
  // signal pour éviter d'ouvrir une deuxième demande sur le même sujet.
  const newTitreNorm = newTitre.trim().toLowerCase()
  const similarExistingTitres =
    newTitreNorm.length < 3
      ? []
      : requests.filter((r) => {
          const t = r.titre.trim().toLowerCase()
          return t === newTitreNorm || t.includes(newTitreNorm) || newTitreNorm.includes(t)
        })

  // Deux bacs, jamais mélangés (Raphaël, 2026-09-22 : "deux bacs, un bac
  // actif, un bac en cours d'optimisation dès qu'une règle est créée ou
  // modifiée pour quelconque raison -- comme ça on s'y retrouve, on sait
  // ce qui est bon et ce qui ne l'est pas encore") -- remplace l'ancien
  // panneau statique "Règles appliquées par le moteur" + la liste
  // "Historique" séparée à côté, qui listaient les mêmes règles sans
  // lien fiable entre les deux (rapprochement par titre, fragile).
  // "Actif" = certifiée par un humain, donc ce que le moteur applique
  // vraiment aujourd'hui. "En cours" = tout le reste (nouvelle demande,
  // en cours de codage, codée mais pas encore vérifiée) -- une règle
  // active qui ne fonctionne plus (bouton "Signaler un problème" sur sa
  // carte, voir ValidationBlock) repasse automatiquement ici, jamais une
  // nouvelle ligne.
  const actifs = requests.filter((r) => r.statut === 'valide')
  const enCours = requests.filter((r) => r.statut !== 'valide')

  return (
    <div className="mt-2 border-t border-[var(--border)] pt-3">
      {error && <p className="mb-2 text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {latestActivity && (
        <p className="mb-1.5 rounded-lg bg-[var(--muted-bg)] p-1.5 text-xs shadow-[inset_0_0_0_1px_var(--primary)]">
          <span className="font-bold">🔧 Là, maintenant :</span>{' '}
          <span className="font-medium">{latestActivity.requestTitre}</span> --{' '}
          {latestActivity.event.message}{' '}
          <span className="text-[var(--muted)]">({formatEventTime(latestActivity.event.created_at)})</span>
        </p>
      )}

      {nbPendingQuestions > 0 && (
        <p className="mb-1.5 rounded-md bg-[var(--danger)] p-1.5 text-sm font-bold text-white">
          🔴 {nbPendingQuestions} question{nbPendingQuestions > 1 ? 's' : ''} en attente de ta réponse
          ci-dessous
        </p>
      )}

      {nbAwaitingValidation > 0 && (
        <p className="mb-1.5 rounded-md bg-[var(--warning)] p-1.5 text-sm font-bold text-[var(--warning-foreground)]">
          🧪 {nbAwaitingValidation} règle{nbAwaitingValidation > 1 ? 's' : ''} codée
          {nbAwaitingValidation > 1 ? 's' : ''} -- à valider ou corriger ci-dessous
        </p>
      )}

      {!loading && actifs.length > 0 && (
        <div className="mb-2">
          <p className="mb-1 text-xs font-bold text-[var(--success)]">✅ Actif ({actifs.length})</p>
          <ul className="flex flex-col gap-1">
            {actifs.map((r) => (
              <CertifiedRuleCard
                key={r.id}
                orgId={orgId}
                request={r}
                savingId={savingId}
                confirmingDelete={confirmingDeleteId === r.id}
                onConfirmDeleteToggle={setConfirmingDeleteId}
                onDelete={(id) => void handleDelete(id)}
                onFieldBlur={handleFieldBlur}
                onCorrected={(id, demande) => {
                  markScroll()
                  setRequests((prev) => prev.map((x) => (x.id === id ? { ...x, demande, statut: 'en_cours' } : x)))
                }}
              />
            ))}
          </ul>
        </div>
      )}

      {!loading && requests.length > 0 && (
        <button
          type="button"
          onClick={() => setHistoryOpen((v) => !v)}
          className="mb-1 flex items-center gap-2 text-xs font-medium text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <span>
            {historyOpen ? '▲' : '▼'} 🔧 En cours d'optimisation ({enCours.length})
          </span>
          {nonValidees > 0 && (
            <span className="rounded-full bg-[var(--primary)] px-2 py-0.5 text-[0.65rem] font-bold text-[var(--primary-foreground)]">
              {nonValidees} pas encore certifiée{nonValidees > 1 ? 's' : ''}
            </span>
          )}
        </button>
      )}

      {historyOpen && enCours.length > 0 && (
        <ul className="mb-2 flex flex-col gap-1">
          {enCours.map((r) => (
            <RuleCard
              key={r.id}
              orgId={orgId}
              request={r}
              savingId={savingId}
              confirmingDelete={confirmingDeleteId === r.id}
              onConfirmDeleteToggle={setConfirmingDeleteId}
              onDelete={(id) => void handleDelete(id)}
              onFieldBlur={handleFieldBlur}
              onQuestionAnswered={() => {
                markScroll()
                setReloadNonce((n) => n + 1)
              }}
              onValidated={(id) => {
                markScroll()
                setRequests((prev) => prev.map((x) => (x.id === id ? { ...x, statut: 'valide' } : x)))
              }}
              onCorrected={(id, demande) => {
                markScroll()
                setRequests((prev) => prev.map((x) => (x.id === id ? { ...x, demande, statut: 'en_cours' } : x)))
              }}
            />
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2 rounded-xl border border-dashed border-[var(--border)] p-3">
        <p className="text-xs font-medium text-[var(--muted)]">
          ➕ Nouvelle règle (celle-ci n'existe pas encore dans la liste ci-dessus)
        </p>
        <Input
          className="font-bold"
          placeholder="Nom de la règle (ex. Critère de RCUR)"
          value={newTitre}
          onChange={(e) => setNewTitre(e.target.value)}
        />
        {similarExistingTitres.length > 0 && (
          <div className="rounded-lg bg-[var(--muted-bg)] p-2 text-xs shadow-[inset_0_0_0_1px_var(--primary)]">
            <p className="font-medium">
              ⚠️ Une demande avec un nom proche existe déjà -- pour éviter un doublon, ajoute plutôt ta
              précision directement sur la carte existante ci-dessus ("✅ Actif" ou "🔧 En cours
              d'optimisation") :
            </p>
            <ul className="mt-1 list-disc pl-4">
              {similarExistingTitres.map((r) => (
                <li key={r.id}>
                  "{r.titre}" ({STATUT_LABEL[r.statut]})
                </li>
              ))}
            </ul>
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="mt-1 text-[var(--primary)] hover:underline"
            >
              Voir "en cours d'optimisation"
            </button>
          </div>
        )}
        <textarea
          className="w-full rounded-lg bg-[var(--card)] p-2 text-sm shadow-[var(--ring-card)]"
          rows={2}
          placeholder="Changement souhaité, en détail..."
          value={newDemande}
          onChange={(e) => setNewDemande(e.target.value)}
        />
        <div>
          <Button
            onClick={() => void handleCreate()}
            disabled={creating || !newTitre.trim() || !newDemande.trim()}
          >
            {creating ? 'Enregistrement…' : '➕ Ajouter la demande'}
          </Button>
        </div>
      </div>
    </div>
  )
}
