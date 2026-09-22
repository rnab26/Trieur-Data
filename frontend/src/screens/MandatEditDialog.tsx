import { useState } from 'react'
import { Dialog } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError, updatePrelevementMandat, type RecordRow } from '@/lib/api'

// Contrairement à RecordEditDialog (clients génériques, jsonb remplacé
// entièrement), le PATCH mandat n'envoie que les champs réellement
// modifiés -- voir trieur/db.py:update_prelevement_mandat. Pas de fetch
// séparé non plus : la ligne à éditer vient déjà entière de la liste déjà
// chargée (colonnes fixes de la table, rien de plus à récupérer).
export function MandatEditDialog({
  orgId,
  mandat,
  columns,
  onClose,
  onSaved,
}: {
  orgId: string
  mandat: RecordRow
  columns: string[]
  onClose: () => void
  onSaved: () => void
}) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    for (const col of columns) {
      const v = mandat[col]
      init[col] = v == null ? '' : String(v)
    }
    return init
  })
  const [editedKeys, setEditedKeys] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function updateField(key: string, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }))
    setEditedKeys((prev) => new Set(prev).add(key))
  }

  async function handleSave() {
    if (editedKeys.size === 0) {
      onClose()
      return
    }
    setSaving(true)
    setSaveError(null)
    const data: Record<string, unknown> = {}
    for (const key of editedKeys) {
      data[key] = values[key] === '' ? null : values[key]
    }
    try {
      await updatePrelevementMandat(orgId, String(mandat._id), data)
      onSaved()
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open onClose={onClose} title="Modifier le mandat">
      <div className="flex flex-col gap-3">
        {columns.map((col) => (
          <div key={col}>
            <label htmlFor={`mandat-field-${col}`} className="mb-1 block text-sm text-[var(--muted)]">
              {col}
            </label>
            <Input
              id={`mandat-field-${col}`}
              value={values[col] ?? ''}
              onChange={(e) => updateField(col, e.target.value)}
            />
          </div>
        ))}
        {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Annuler
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
