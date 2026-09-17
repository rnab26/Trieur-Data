import { useEffect, useState } from 'react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, getMasterColumns, getRecord, updateRecord } from '@/lib/api'

// PATCH /orgs/{org_id}/records/{record_id} remplace ENTIEREMENT le jsonb
// `data` (voir trieur/db.py:update_record) -- on part donc toujours du
// contenu complet renvoyé par GET .../records/{record_id}, jamais de la
// ligne aplatie du tableau (qui mélange des colonnes d'affichage comme
// "Fichier source" qui ne font pas partie de `data`).
export function RecordEditDialog({
  orgId,
  recordId,
  onClose,
  onSaved,
}: {
  orgId: string
  recordId: string
  onClose: () => void
  onSaved: () => void
}) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fields, setFields] = useState<Array<[string, string]>>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([getRecord(orgId, recordId), getMasterColumns(orgId)])
      .then(([record, master]) => {
        if (cancelled) return
        const data = (record.data as Record<string, unknown>) ?? {}
        const orderedKeys = [
          ...master.columns,
          ...Object.keys(data).filter((k) => !master.columns.includes(k)),
        ]
        setFields(orderedKeys.map((k) => [k, data[k] == null ? '' : String(data[k])]))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [orgId, recordId])

  function updateField(key: string, value: string) {
    setFields((prev) => prev.map(([k, v]) => (k === key ? [k, value] : [k, v])))
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    const data: Record<string, string | null> = {}
    for (const [k, v] of fields) data[k] = v === '' ? null : v
    try {
      await updateRecord(orgId, recordId, data)
      onSaved()
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={onClose} title="Modifier le client">
      {loading && <p className="text-sm text-[var(--muted)]">Chargement…</p>}
      {error && <p className="text-sm text-[var(--danger)]">Erreur : {error}</p>}
      {!loading && !error && (
        <div className="flex flex-col gap-3">
          {fields.length === 0 && (
            <p className="text-sm text-[var(--muted)]">Aucun champ à afficher.</p>
          )}
          {fields.map(([key, value]) => (
            <div key={key}>
              <label htmlFor={`field-${key}`} className="mb-1 block text-sm text-[var(--muted)]">
                {key}
              </label>
              <Input
                id={`field-${key}`}
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
              />
            </div>
          ))}
          {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
          <div className="mt-2 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose} disabled={saving}>
              Annuler
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? 'Enregistrement…' : 'Enregistrer'}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  )
}
