import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  CHANTIER_STATUSES,
  addChantierMessage,
  addChantierTodo,
  answerChantierQuestion,
  listChantierMessages,
  listChantierQuestions,
  listChantierTodos,
  setChantierTodoDone,
  updateChantierStatus,
  type Chantier,
  type ChantierMessage,
  type ChantierQuestion,
  type ChantierStatus,
  type ChantierTodo,
} from '@/lib/api'

export const STATUT_LABELS: Record<ChantierStatus, string> = {
  a_faire: '📋 À faire',
  en_cours: '🔧 En cours',
  attente_retour: '⏳ Attente de ta réponse',
  termine: '✅ Terminé',
  abandonne: '⛔ Abandonné',
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

const URL_PATTERN = /(https?:\/\/[^\s]+)/g

// Un message de chantier peut contenir un lien vers une fiche de
// questions (Artifact claude.ai) -- affiché en texte brut jusqu'ici, donc
// impossible à taper au pouce sur téléphone (Raphaël, 2026-09-21).
function LinkifiedText({ text }: { text: string }) {
  // split() sur un pattern à groupe capturant intercale les URLs trouvées
  // aux index impairs -- pas de `.test()` séparé, qui serait faux avec un
  // regex global (son `lastIndex` change à chaque appel).
  const parts = text.split(URL_PATTERN)
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--primary)] underline break-all"
          >
            {part}
          </a>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}

// Une question à choix cliquables, posée par une session Claude sur un
// chantier ambigu (Raphaël, 2026-09-21 -- remplace la fiche Artifact à
// part, perdue d'une session à l'autre : ici la réponse vit dans le
// Cockpit lui-même, visible par la prochaine session automatiquement).
function QuestionBlock({
  orgId,
  chantierId,
  question,
  onAnswered,
}: {
  orgId: string
  chantierId: string
  question: ChantierQuestion
  onAnswered: (updated: ChantierQuestion[]) => void
}) {
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleChoose(option: string) {
    setSubmitting(true)
    setError(null)
    try {
      const updated = await answerChantierQuestion(
        orgId, chantierId, question.id, option, comment.trim() || null,
      )
      onAnswered(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSubmitting(false)
    }
  }

  if (question.answered_at) {
    return (
      <div className="rounded-md shadow-[var(--ring-card)] bg-[var(--muted-bg)] p-2 text-sm">
        <p className="text-[var(--muted)]">{question.question}</p>
        <p className="mt-1">
          Ta réponse : <span className="font-medium">{question.answer}</span>
          {question.comment && <span className="text-[var(--muted)]"> — {question.comment}</span>}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-md shadow-[inset_0_0_0_1px_var(--primary)] bg-[var(--muted-bg)] p-3 text-sm">
      <p className="font-medium">{question.question}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {question.options.map((option) => (
          <Button
            key={option}
            type="button"
            variant="secondary"
            disabled={submitting}
            onClick={() => void handleChoose(option)}
          >
            {option}
          </Button>
        ))}
      </div>
      <Input
        className="mt-2"
        placeholder="Préciser ta réponse (optionnel)…"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {error && <p className="mt-1 text-xs text-[var(--danger)]">{error}</p>}
    </div>
  )
}

export function ChantierCard({
  orgId,
  chantier,
  compact = false,
  onStatusChanged,
}: {
  orgId: string
  chantier: Chantier
  compact?: boolean
  onStatusChanged: () => void
}) {
  const [statusSaving, setStatusSaving] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)

  const [threadOpen, setThreadOpen] = useState(!compact && chantier.status === 'attente_retour')
  const [messages, setMessages] = useState<ChantierMessage[] | null>(null)
  const [messagesError, setMessagesError] = useState<string | null>(null)
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)

  const [todos, setTodos] = useState<ChantierTodo[] | null>(null)
  const [todosError, setTodosError] = useState<string | null>(null)
  const [newTodo, setNewTodo] = useState('')
  const [addingTodo, setAddingTodo] = useState(false)

  const [questions, setQuestions] = useState<ChantierQuestion[] | null>(null)
  const [questionsError, setQuestionsError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listChantierTodos(orgId, chantier.id)
      .then((data) => {
        if (!cancelled) setTodos(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setTodosError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId, chantier.id])

  // Chargées inconditionnellement (pas seulement quand le fil est ouvert)
  // -- une question sans réponse est ce qui explique le statut "Attente
  // de ta réponse", elle doit être visible sans un clic de plus.
  useEffect(() => {
    let cancelled = false
    listChantierQuestions(orgId, chantier.id)
      .then((data) => {
        if (!cancelled) setQuestions(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setQuestionsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId, chantier.id])

  useEffect(() => {
    if (!threadOpen || messages !== null) return
    let cancelled = false
    listChantierMessages(orgId, chantier.id)
      .then((data) => {
        if (!cancelled) setMessages(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setMessagesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [threadOpen, messages, orgId, chantier.id])

  async function handleStatusChange(newStatus: ChantierStatus) {
    setStatusSaving(true)
    setStatusError(null)
    try {
      await updateChantierStatus(orgId, chantier.id, newStatus)
      onStatusChanged()
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setStatusSaving(false)
    }
  }

  async function handleSend() {
    if (!reply.trim()) return
    setSending(true)
    setMessagesError(null)
    try {
      const updated = await addChantierMessage(orgId, chantier.id, reply.trim())
      setMessages(updated)
      setReply('')
    } catch (err) {
      setMessagesError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSending(false)
    }
  }

  async function handleToggleTodo(todo: ChantierTodo) {
    setTodosError(null)
    try {
      await setChantierTodoDone(orgId, chantier.id, todo.id, !todo.done)
      setTodos((prev) => prev && prev.map((t) => (t.id === todo.id ? { ...t, done: !todo.done } : t)))
    } catch (err) {
      setTodosError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  async function handleAddTodo() {
    if (!newTodo.trim()) return
    setAddingTodo(true)
    setTodosError(null)
    try {
      const updated = await addChantierTodo(orgId, chantier.id, newTodo.trim())
      setTodos(updated)
      setNewTodo('')
    } catch (err) {
      setTodosError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setAddingTodo(false)
    }
  }

  return (
    <div className="rounded-lg shadow-[var(--ring-card)] bg-[var(--card)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-[var(--foreground)]">{chantier.title}</p>
          <p className="text-xs text-[var(--muted)]">
            Priorité {chantier.priority} · mis à jour {formatDate(chantier.updated_at)}
          </p>
        </div>
        <select
          aria-label={`Statut de ${chantier.title}`}
          className="rounded-md shadow-[var(--ring-card)] bg-[var(--card)] px-2 py-1 text-xs text-[var(--foreground)]"
          value={chantier.status}
          disabled={statusSaving}
          onChange={(e) => void handleStatusChange(e.target.value as ChantierStatus)}
        >
          {CHANTIER_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUT_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      {statusError && <p className="mt-1 text-xs text-[var(--danger)]">{statusError}</p>}

      {questionsError && <p className="mt-1 text-xs text-[var(--danger)]">{questionsError}</p>}
      {questions && questions.some((q) => !q.answered_at) && (
        <div className="mt-2 flex flex-col gap-2">
          {questions
            .filter((q) => !q.answered_at)
            .map((q) => (
              <QuestionBlock
                key={q.id}
                orgId={orgId}
                chantierId={chantier.id}
                question={q}
                onAnswered={setQuestions}
              />
            ))}
        </div>
      )}

      {todos && todos.length > 0 && (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted-bg)]">
            <div
              className="h-full rounded-full bg-[var(--primary)] transition-all"
              style={{ width: `${Math.round((todos.filter((t) => t.done).length / todos.length) * 100)}%` }}
            />
          </div>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            {todos.filter((t) => t.done).length}/{todos.length} points traités
          </p>
        </div>
      )}

      {!compact && (
        <div className="mt-3 flex flex-col gap-1">
          {todosError && <p className="text-xs text-[var(--danger)]">{todosError}</p>}
          {todos === null && !todosError && (
            <p className="text-xs text-[var(--muted)]">Chargement des points à suivre…</p>
          )}
          {todos && todos.length === 0 && (
            <p className="text-xs text-[var(--muted)]">Aucun point à suivre pour l'instant.</p>
          )}
          {todos?.map((todo) => (
            <label key={todo.id} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={todo.done} onChange={() => void handleToggleTodo(todo)} />
              <span className={todo.done ? 'text-[var(--muted)] line-through' : ''}>{todo.body}</span>
            </label>
          ))}
          <form
            className="mt-1 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void handleAddTodo()
            }}
          >
            <Input
              placeholder="Ajouter un point à suivre…"
              value={newTodo}
              onChange={(e) => setNewTodo(e.target.value)}
            />
            <Button type="submit" variant="secondary" disabled={addingTodo || !newTodo.trim()}>
              {addingTodo ? '…' : '➕'}
            </Button>
          </form>
        </div>
      )}

      {!compact && (
        <div className="mt-3">
          <button
            type="button"
            className="text-xs font-medium text-[var(--muted)] underline"
            onClick={() => setThreadOpen((v) => !v)}
          >
            {threadOpen ? 'Masquer le fil de discussion' : 'Voir le fil de discussion'}
          </button>

          {threadOpen && (
            <div className="mt-2 flex flex-col gap-2">
              {messagesError && <p className="text-xs text-[var(--danger)]">{messagesError}</p>}
              {messages === null && !messagesError && (
                <p className="text-xs text-[var(--muted)]">Chargement…</p>
              )}
              {messages && messages.length === 0 && (
                <p className="text-xs text-[var(--muted)]">Aucun message pour l'instant.</p>
              )}
              {messages?.map((msg) => (
                <div key={msg.id} className="rounded-md bg-[var(--muted-bg)] p-2 text-sm">
                  <p className="text-xs text-[var(--muted)]">
                    {msg.author_type === 'user' ? '🧑 Toi' : '🤖 Claude'} · {formatDate(msg.created_at)}
                  </p>
                  <p className="whitespace-pre-wrap">
                    <LinkifiedText text={msg.body} />
                  </p>
                </div>
              ))}
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  void handleSend()
                }}
              >
                <Input
                  placeholder="Ajouter un message…"
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                />
                <Button type="submit" variant="secondary" disabled={sending || !reply.trim()}>
                  {sending ? 'Envoi…' : 'Envoyer'}
                </Button>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
