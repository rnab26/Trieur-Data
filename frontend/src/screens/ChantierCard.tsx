import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  CHANTIER_STATUSES,
  addChantierMessage,
  addChantierTodo,
  listChantierMessages,
  listChantierTodos,
  setChantierTodoDone,
  updateChantierStatus,
  type Chantier,
  type ChantierMessage,
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
    <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-[var(--foreground)]">{chantier.title}</p>
          <p className="text-xs text-[var(--muted)]">
            Priorité {chantier.priority} · mis à jour {formatDate(chantier.updated_at)}
          </p>
        </div>
        <select
          aria-label={`Statut de ${chantier.title}`}
          className="rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs text-[var(--foreground)]"
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
                  <p className="whitespace-pre-wrap">{msg.body}</p>
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
