import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  ApiError,
  decodePipelineFiltersCode,
  deletePipelineSavedFilter,
  describeFilterGroups,
  encodePipelineFiltersCode,
  getPipelineColumnUniqueValues,
  listPipelineSavedFilters,
  renamePipelineSavedFilter,
  savePipelineSavedFilter,
  type FilterCriterion,
  type FilterGroup,
  type PipelineSavedFilter,
} from '@/lib/api'

const SELECT_CLASS =
  'rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm text-[var(--foreground)]'

// Copie conforme de views/tab3_filtrage_dedup.py : le SEUL mécanisme de
// filtre du Pipeline -- des GROUPES de critères combinés en OU, chaque
// groupe combinant ses critères en ET (trieur/filters.py:
// apply_filter_groups), jamais un filtre par colonne façon Google
// Sheets ni une recherche libre (qui n'ont jamais existé ici). Un
// groupe "en cours de saisie" (valeurs vides) est ignoré côté serveur,
// jamais un blocage.
function emptyCriterion(defaultColumn: string): FilterCriterion {
  return { column: defaultColumn, kind: 'valeurs', values: [] }
}

function CriterionRow({
  orgId,
  sessionId,
  masterColumns,
  criterion,
  onChange,
  onRemove,
}: {
  orgId: string
  sessionId: string | null
  masterColumns: string[]
  criterion: FilterCriterion
  onChange: (next: FilterCriterion) => void
  onRemove: () => void
}) {
  // Auto-correction comme l'original : une colonne absente de la liste
  // actuelle (ex. après un changement de colonnes maîtres) retombe sur
  // la première disponible plutôt que de planter.
  useEffect(() => {
    if (masterColumns.length === 0) return
    if (!masterColumns.includes(criterion.column)) {
      onChange({ ...criterion, column: masterColumns[0], values: [] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [masterColumns.join('|')])

  const isDept = criterion.column === 'CP'

  const [uniqueValues, setUniqueValues] = useState<string[] | null>(null)
  const [uniqueCount, setUniqueCount] = useState<number | null>(null)
  const [loadingValues, setLoadingValues] = useState(false)

  useEffect(() => {
    if (isDept || !sessionId || !criterion.column) return
    let cancelled = false
    setLoadingValues(true)
    getPipelineColumnUniqueValues(orgId, sessionId, criterion.column)
      .then((data) => {
        if (cancelled) return
        setUniqueValues(data.values)
        setUniqueCount(data.count)
      })
      .catch(() => {
        if (!cancelled) {
          setUniqueValues(null)
          setUniqueCount(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingValues(false)
      })
    return () => {
      cancelled = true
    }
  }, [orgId, sessionId, criterion.column, isDept])

  function setColumn(column: string) {
    onChange({ column, kind: column === 'CP' ? 'departements' : 'valeurs', values: [] })
  }

  return (
    <div className="flex flex-wrap items-start gap-2">
      <select className={SELECT_CLASS} value={criterion.column} onChange={(e) => setColumn(e.target.value)}>
        {masterColumns.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      {isDept && (
        <Input
          placeholder="Départements (ex: 02,33,77)"
          className="max-w-xs"
          value={criterion.values.join(',')}
          onChange={(e) =>
            onChange({
              ...criterion,
              kind: 'departements',
              values: e.target.value
                .split(',')
                .map((p) => p.trim())
                .filter(Boolean)
                .map((p) => p.padStart(2, '0')),
            })
          }
        />
      )}

      {!isDept && loadingValues && <span className="text-sm text-[var(--muted)]">Chargement des valeurs…</span>}

      {!isDept && !loadingValues && uniqueValues !== null && (
        <select
          multiple
          className={`${SELECT_CLASS} min-h-[38px] max-w-xs`}
          value={criterion.values}
          onChange={(e) =>
            onChange({
              ...criterion,
              kind: 'valeurs',
              values: Array.from(e.target.selectedOptions).map((o) => o.value),
            })
          }
        >
          {uniqueValues.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      )}

      {!isDept && !loadingValues && uniqueValues === null && (
        <Input
          placeholder={`Valeur(s) exacte(s) pour ${criterion.column} (séparées par ;)${
            uniqueCount ? ` -- ${uniqueCount} valeurs distinctes` : ''
          }`}
          className="max-w-xs"
          value={criterion.values.join(';')}
          onChange={(e) =>
            onChange({
              ...criterion,
              kind: 'valeurs',
              values: e.target.value
                .split(';')
                .map((v) => v.trim())
                .filter(Boolean),
            })
          }
        />
      )}

      <Button variant="danger" onClick={onRemove} title="Retirer ce critère">
        🗑️
      </Button>
    </div>
  )
}

export function PipelineFilterGroups({
  orgId,
  sessionId,
  masterColumns,
  groups,
  onChange,
}: {
  orgId: string
  sessionId: string | null
  masterColumns: string[]
  groups: FilterGroup[]
  onChange: (next: FilterGroup[]) => void
}) {
  const defaultColumn = masterColumns[0] ?? ''

  // État initial = un seul groupe vide (voir PipelineScreen) -- seedé
  // avec un premier critère dès que les colonnes maîtres sont connues,
  // même point de départ que st.session_state["_filter_group_ids"] =
  // [[uuid]] côté original.
  useEffect(() => {
    if (masterColumns.length > 0 && groups.length === 1 && groups[0].length === 0) {
      onChange([[emptyCriterion(masterColumns[0])]])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [masterColumns.join('|')])

  function updateGroup(gi: number, next: FilterGroup) {
    const copy = [...groups]
    copy[gi] = next
    onChange(copy)
  }

  function addGroup() {
    onChange([...groups, [emptyCriterion(defaultColumn)]])
  }

  function addCriterion(gi: number) {
    updateGroup(gi, [...groups[gi], emptyCriterion(defaultColumn)])
  }

  function removeCriterion(gi: number, ci: number) {
    const nextGroup = groups[gi].filter((_, i) => i !== ci)
    if (nextGroup.length === 0 && groups.length > 1) {
      onChange(groups.filter((_, i) => i !== gi))
    } else {
      updateGroup(gi, nextGroup)
    }
  }

  const completeGroups = groups.filter((g) => g.length > 0 && g.every((c) => c.values.length > 0))

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-sm font-medium">Filtrer par un ou plusieurs critères</p>
        <p className="text-xs text-[var(--muted)]">
          Plusieurs groupes = <strong>OU</strong> entre eux ; plusieurs critères dans un groupe ={' '}
          <strong>ET</strong>. Ex : tout le 34, plus le 71 seulement pour Lyon.
        </p>
      </div>

      {groups.map((group, gi) => (
        <div key={gi}>
          {gi > 0 && <div className="my-1 text-center text-sm font-semibold text-[var(--muted)]">OU</div>}
          <div className="flex flex-col gap-2 rounded-md border border-[var(--border)] p-3">
            {group.map((criterion, ci) => (
              <CriterionRow
                key={ci}
                orgId={orgId}
                sessionId={sessionId}
                masterColumns={masterColumns}
                criterion={criterion}
                onChange={(next) => updateGroup(gi, group.map((c, i) => (i === ci ? next : c)))}
                onRemove={() => removeCriterion(gi, ci)}
              />
            ))}
            <div>
              <Button variant="secondary" onClick={() => addCriterion(gi)}>
                ➕ Critère (ET)
              </Button>
            </div>
          </div>
        </div>
      ))}

      <div>
        <Button variant="secondary" onClick={addGroup}>
          ➕ Ajouter un groupe (OU)
        </Button>
      </div>

      <SavedFiltersPanel orgId={orgId} completeGroups={completeGroups} onApply={onChange} />
    </div>
  )
}

// Filtres pré-enregistrés + sauvegarde texte -- copie conforme de la
// section "💾 Filtres pré-enregistrés" / "🔗 Sauvegarde texte" de
// views/tab3_filtrage_dedup.py.
function SavedFiltersPanel({
  orgId,
  completeGroups,
  onApply,
}: {
  orgId: string
  completeGroups: FilterGroup[]
  onApply: (groups: FilterGroup[]) => void
}) {
  const [filters, setFilters] = useState<PipelineSavedFilter[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({})
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [code, setCode] = useState<string | null>(null)
  const [pastedCode, setPastedCode] = useState('')
  const [restoreError, setRestoreError] = useState<string | null>(null)
  const [restoreSuccess, setRestoreSuccess] = useState<string | null>(null)

  function reload() {
    listPipelineSavedFilters(orgId)
      .then((data) => {
        setFilters(data)
        setError(null)
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : 'Erreur inconnue.'))
  }

  useEffect(reload, [orgId])

  async function handleSave() {
    const name = newName.trim()
    if (!name || completeGroups.length === 0) return
    setSaving(true)
    setActionError(null)
    try {
      await savePipelineSavedFilter(orgId, { name, groups: completeGroups })
      setNewName('')
      reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  async function handleRename(id: string) {
    const name = (renameDrafts[id] ?? '').trim()
    if (!name) return
    setActionError(null)
    try {
      await renamePipelineSavedFilter(orgId, id, name)
      reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  async function handleDelete(id: string) {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id)
      return
    }
    setActionError(null)
    try {
      await deletePipelineSavedFilter(orgId, id)
      reload()
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setConfirmDeleteId(null)
    }
  }

  async function handleGetCode() {
    try {
      const data = await encodePipelineFiltersCode(orgId, filters ?? [])
      setCode(data.code)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  async function handleRestore() {
    setRestoreError(null)
    setRestoreSuccess(null)
    try {
      const data = await decodePipelineFiltersCode(orgId, pastedCode)
      for (const f of data.filters) {
        await savePipelineSavedFilter(orgId, { name: f.name, groups: f.groups })
      }
      setRestoreSuccess(`${data.filters.length} filtre(s) restauré(s)/mis à jour.`)
      setPastedCode('')
      reload()
    } catch (err) {
      setRestoreError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  return (
    <details className="rounded-md border border-[var(--border)] p-3" open={(filters?.length ?? 0) > 0}>
      <summary className="cursor-pointer text-sm font-medium">💾 Filtres pré-enregistrés</summary>

      <p className="mt-2 text-xs text-[var(--muted)]">
        {completeGroups.length > 0
          ? `Filtre actuel : ${describeFilterGroups(completeGroups)}`
          : 'Choisis au moins une colonne et des valeurs ci-dessus pour pouvoir enregistrer un filtre.'}
      </p>

      {error && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {error}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Input
          placeholder="Nom du filtre (ex : Sud-Ouest)"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className="max-w-xs"
        />
        <Button onClick={() => void handleSave()} disabled={saving || !newName.trim() || completeGroups.length === 0}>
          💾 Enregistrer
        </Button>
      </div>

      {filters && filters.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {filters.map((f) => (
            <li key={f.id} className="flex flex-col gap-1 rounded-md border border-[var(--border)] p-2">
              <p className="text-xs text-[var(--muted)]">
                <strong>{f.name}</strong> — {describeFilterGroups(f.groups)}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  value={renameDrafts[f.id] ?? f.name}
                  onChange={(e) => setRenameDrafts((prev) => ({ ...prev, [f.id]: e.target.value }))}
                  className="max-w-[10rem]"
                />
                <Button variant="secondary" onClick={() => onApply(f.groups)}>
                  Appliquer
                </Button>
                <Button variant="secondary" onClick={() => void handleRename(f.id)}>
                  Renommer
                </Button>
                <Button variant={confirmDeleteId === f.id ? 'danger' : 'secondary'} onClick={() => void handleDelete(f.id)}>
                  {confirmDeleteId === f.id ? 'Confirmer la suppression' : 'Supprimer'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {actionError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {actionError}</p>}

      <div className="mt-4 border-t border-[var(--border)] pt-3">
        <p className="text-sm font-medium">🔗 Sauvegarde texte (copier/coller)</p>
        {filters && filters.length > 0 ? (
          <>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Copie ce code et garde-le en lieu sûr (note, message…) : il permet de retrouver tes filtres même
              si l'environnement les perd.
            </p>
            <Button variant="secondary" className="mt-2" onClick={() => void handleGetCode()}>
              Générer le code
            </Button>
            {code && (
              <textarea
                readOnly
                value={code}
                rows={3}
                className="mt-2 w-full rounded-md border border-[var(--border)] bg-[var(--muted-bg)] p-2 text-xs"
                onClick={(e) => e.currentTarget.select()}
              />
            )}
          </>
        ) : (
          <p className="mt-1 text-xs text-[var(--muted)]">
            Enregistre au moins un filtre ci-dessus pour obtenir un code à sauvegarder.
          </p>
        )}

        <textarea
          placeholder="TRIEUR-FILTRES-v1:..."
          value={pastedCode}
          onChange={(e) => setPastedCode(e.target.value)}
          rows={2}
          className="mt-3 w-full rounded-md border border-[var(--border)] p-2 text-xs"
        />
        <Button variant="secondary" className="mt-2" onClick={() => void handleRestore()} disabled={!pastedCode.trim()}>
          ♻️ Restaurer depuis ce code
        </Button>
        {restoreError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {restoreError}</p>}
        {restoreSuccess && <p className="mt-2 text-sm text-[var(--success,#16a34a)]">{restoreSuccess}</p>}
      </div>
    </details>
  )
}
