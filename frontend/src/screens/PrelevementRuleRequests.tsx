import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  createPrelevementRuleRequest,
  deletePrelevementRuleRequest,
  listPrelevementRuleRequests,
  updatePrelevementRuleRequest,
  type PrelevementRuleRequest,
  type RuleRequestStatut,
} from '@/lib/api'

const STATUT_LABEL: Record<RuleRequestStatut, string> = {
  en_attente: '⏳ En attente',
  en_cours: '🔵 En cours',
  valide: '✅ Validé',
}

const STATUT_COLOR: Record<RuleRequestStatut, string> = {
  en_attente: 'text-[var(--muted)]',
  en_cours: 'text-[var(--primary)]',
  valide: 'text-[var(--success)]',
}

// Demandes de modification des règles codées en dur du moteur
// (exclusions, FRST/RCUR, liste des produits...) -- demandé par
// Raphaël (2026-09-22) : lui/son père écrivent ici le changement
// souhaité, ça s'enregistre en base (statut de départ "En attente"),
// et une session Claude Code la traite quand on le lui demande par
// message -- jamais codé/appliqué depuis cet écran lui-même.
export function PrelevementRuleRequests({
  orgId,
  refreshKey,
}: {
  orgId: string
  // Incrémenté par le parent après un ajout fait depuis le formulaire
  // inline sous une règle du panneau "Règles appliquées par le moteur"
  // (Raphaël, 2026-09-22 : le point d'entrée pour MODIFIER une règle
  // existante est directement dessous, pas ici -- cette liste ne sert
  // de formulaire de saisie que pour une règle qui n'existe pas encore)
  // -- fait recharger sans dupliquer la logique de récupération.
  refreshKey?: number
}) {
  const [requests, setRequests] = useState<PrelevementRuleRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [newTitre, setNewTitre] = useState('')
  const [newDemande, setNewDemande] = useState('')
  const [creating, setCreating] = useState(false)

  const [savingId, setSavingId] = useState<string | null>(null)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listPrelevementRuleRequests(orgId)
      .then((data) => {
        if (!cancelled) setRequests(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [orgId, refreshKey])

  async function handleCreate() {
    const titre = newTitre.trim()
    const demande = newDemande.trim()
    if (!titre || !demande) return
    setCreating(true)
    setError(null)
    try {
      const created = await createPrelevementRuleRequest(orgId, titre, demande)
      setRequests((prev) => [...prev, created])
      setNewTitre('')
      setNewDemande('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setCreating(false)
    }
  }

  async function persist(id: string, patch: Partial<{ titre: string; demande: string; statut: RuleRequestStatut }>) {
    setSavingId(id)
    setError(null)
    try {
      const updated = await updatePrelevementRuleRequest(orgId, id, patch)
      setRequests((prev) => prev.map((r) => (r.id === id ? updated : r)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingId(null)
    }
  }

  async function handleDelete(id: string) {
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

  return (
    <div className="mb-4 rounded-lg border border-[var(--border)] p-3">
      <h2 className="text-sm font-semibold">📝 Demandes de modification de règles</h2>
      <p className="mt-1 mb-3 text-xs text-[var(--muted)]">
        Historique de toutes les demandes, quel que soit leur statut. Pour modifier une règle
        existante, utilise "✏️ Demander une modification" juste en dessous d'elle, plus haut -- le
        formulaire ci-dessous ne sert qu'à proposer une règle qui n'existe pas encore. Envoie ensuite
        un message à la session Claude Code pour qu'elle traite les demandes en attente.
      </p>

      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && <p className="mb-2 text-sm text-[var(--danger)]">Erreur : {error}</p>}

      {!loading && requests.length === 0 && (
        <p className="mb-3 text-sm text-[var(--muted)]">Aucune demande pour l'instant.</p>
      )}

      {!loading && requests.length > 0 && (
        <ul className="mb-3 flex flex-col gap-3">
          {requests.map((r) => (
            <li key={r.id} className="rounded-md border border-[var(--border)] p-2">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Input
                  className="min-w-[10rem] flex-1 font-medium"
                  value={r.titre}
                  disabled={savingId === r.id}
                  onChange={(e) =>
                    setRequests((prev) => prev.map((x) => (x.id === r.id ? { ...x, titre: e.target.value } : x)))
                  }
                  onBlur={(e) => {
                    const titre = e.target.value.trim()
                    if (titre && titre !== r.titre) void persist(r.id, { titre })
                  }}
                />
                <select
                  className={
                    'rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs font-medium ' +
                    STATUT_COLOR[r.statut]
                  }
                  value={r.statut}
                  disabled={savingId === r.id}
                  onChange={(e) => void persist(r.id, { statut: e.target.value as RuleRequestStatut })}
                >
                  <option value="en_attente">{STATUT_LABEL.en_attente}</option>
                  <option value="en_cours">{STATUT_LABEL.en_cours}</option>
                  <option value="valide">{STATUT_LABEL.valide}</option>
                </select>
              </div>
              <textarea
                className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] p-2 text-sm"
                rows={2}
                value={r.demande}
                disabled={savingId === r.id}
                onChange={(e) =>
                  setRequests((prev) => prev.map((x) => (x.id === r.id ? { ...x, demande: e.target.value } : x)))
                }
                onBlur={(e) => {
                  const demande = e.target.value.trim()
                  if (demande && demande !== r.demande) void persist(r.id, { demande })
                }}
              />
              <div className="mt-1 flex items-center justify-between">
                <span className="text-xs text-[var(--muted)]">
                  Modifié le {new Date(r.updated_at).toLocaleDateString('fr-FR')}
                </span>
                {confirmingDeleteId === r.id ? (
                  <span className="flex items-center gap-1">
                    <Button
                      variant="danger"
                      disabled={savingId === r.id}
                      onClick={() => void handleDelete(r.id)}
                    >
                      Confirmer
                    </Button>
                    <Button variant="secondary" onClick={() => setConfirmingDeleteId(null)}>
                      Annuler
                    </Button>
                  </span>
                ) : (
                  <Button variant="danger" onClick={() => setConfirmingDeleteId(r.id)}>
                    🗑️
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-2 rounded-md border border-dashed border-[var(--border)] p-2">
        <p className="text-xs font-medium text-[var(--muted)]">Nouvelle demande</p>
        <Input
          placeholder="Nom de la règle (ex. Critère de RCUR)"
          value={newTitre}
          onChange={(e) => setNewTitre(e.target.value)}
        />
        <textarea
          className="w-full rounded-md border border-[var(--border)] bg-[var(--card)] p-2 text-sm"
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
