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

  // Valeur BRUTE d'origine par colonne (avant conversion en chaîne pour
  // l'affichage dans <Input>) -- voir handleSave : un champ jamais
  // touché doit repartir avec SON type d'origine (nombre, booléen...)
  // dans le PATCH, pas la version stringifiée utilisée pour l'affichage.
  // Sans ça, modifier UNE seule ligne convertissait TOUTES ses valeurs
  // inchangées en chaînes (0 -> "0", false -> "false"), cassant la
  // distinction vide/non-vide côté backend (revue PR #24, point #2).
  const [originalData, setOriginalData] = useState<Record<string, unknown>>({})
  const [editedKeys, setEditedKeys] = useState<Set<string>>(new Set())

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
        setOriginalData(data)
        setEditedKeys(new Set())
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
    setEditedKeys((prev) => new Set(prev).add(key))
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    const data: Record<string, unknown> = {}
    for (const [k, v] of fields) {
      // Champ non modifié : renvoie sa valeur BRUTE d'origine (type
      // préservé), jamais la chaîne d'affichage -- seul un champ
      // effectivement édité est envoyé comme chaîne (ou null si vidé).
      data[k] = editedKeys.has(k) ? (v === '' ? null : v) : (originalData[k] ?? null)
    }
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
