import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useIsAdmin, useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  deletePipelineExportPreset,
  exportPipelineSessionRows,
  listPipelineExportPresets,
  previewSavePipelineSessionToDatabase,
  renamePipelineExportPreset,
  savePipelineExportPreset,
  savePipelineSessionToDatabase,
  type FilterGroup,
  type PipelineExportPreset,
} from '@/lib/api'

// Ordre + sélection des colonnes à l'export + presets nommés -- mirroir
// de views/tab4_export.py. Le vrai glisser-déposer (streamlit-sortables)
// n'est pas fiable au toucher (usage principal : téléphone) -- flèches
// haut/bas, même patron que MasterColumnsPanel/l'ancienne version de cet
// écran, cohérent dans toute l'app.
export function PipelineExportPanel({
  orgId,
  sessionId,
  colOrder,
  excludedCols,
  onColOrderChange,
  onExcludedColsChange,
  filterGroups,
  rowCount,
  filteredCount,
}: {
  orgId: string
  sessionId: string
  colOrder: string[]
  excludedCols: Set<string>
  onColOrderChange: (next: string[]) => void
  onExcludedColsChange: (next: Set<string>) => void
  filterGroups: FilterGroup[]
  rowCount: number
  filteredCount: number
}) {
  const [exporting, setExporting] = useState<'csv' | 'xlsx' | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [filename, setFilename] = useState('export_leads')

  const [presets, setPresets] = useState<PipelineExportPreset[] | null>(null)
  const [presetsError, setPresetsError] = useState<string | null>(null)
  const [presetName, setPresetName] = useState('')
  const [savingPreset, setSavingPreset] = useState(false)
  const [presetActionError, setPresetActionError] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [renameDrafts, setRenameDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    let cancelled = false
    listPipelineExportPresets(orgId)
      .then((data) => {
        if (!cancelled) setPresets(data)
      })
      .catch((err: unknown) => {
        if (!cancelled) setPresetsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }, [orgId])

  function moveUp(i: number) {
    if (i === 0) return
    const next = [...colOrder]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    onColOrderChange(next)
  }

  function moveDown(i: number) {
    if (i >= colOrder.length - 1) return
    const next = [...colOrder]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    onColOrderChange(next)
  }

  function toggleIncluded(col: string) {
    const next = new Set(excludedCols)
    if (next.has(col)) next.delete(col)
    else next.add(col)
    onExcludedColsChange(next)
  }

  async function handleExport(format: 'csv' | 'xlsx') {
    setExporting(format)
    setExportError(null)
    try {
      const selectedColumns = colOrder.filter((c) => !excludedCols.has(c))
      await exportPipelineSessionRows(orgId, sessionId, {
        format,
        filterGroups,
        columns: selectedColumns.length > 0 ? selectedColumns : undefined,
        filename: filename.trim() || undefined,
      })
    } catch (err) {
      setExportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setExporting(null)
    }
  }

  async function handleSavePreset() {
    const name = presetName.trim()
    if (!name) return
    setSavingPreset(true)
    setPresetActionError(null)
    try {
      const included = colOrder.filter((c) => !excludedCols.has(c))
      const excluded = colOrder.filter((c) => excludedCols.has(c))
      const saved = await savePipelineExportPreset(orgId, { name, included, excluded })
      setPresets((prev) => {
        const withoutSameName = (prev ?? []).filter((p) => p.name.toLowerCase() !== name.toLowerCase())
        return [...withoutSameName, saved]
      })
      setPresetName('')
    } catch (err) {
      setPresetActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSavingPreset(false)
    }
  }

  function applyPreset(preset: PipelineExportPreset) {
    const known = new Set(colOrder)
    // Colonnes du preset absentes des données actuelles : ignorées avec
    // avertissement -- colonnes présentes mais pas dans le preset :
    // ajoutées à la fin des incluses -- même règle que
    // views/tab4_export.py:_apply_export_preset.
    const presetIncluded = preset.included.filter((c) => known.has(c))
    const presetExcluded = preset.excluded.filter((c) => known.has(c))
    const coveredByPreset = new Set([...presetIncluded, ...presetExcluded])
    const notCovered = colOrder.filter((c) => !coveredByPreset.has(c))
    onColOrderChange([...presetIncluded, ...presetExcluded, ...notCovered])
    onExcludedColsChange(new Set(presetExcluded))
  }

  async function handleDeletePreset(id: string) {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id)
      return
    }
    setPresetActionError(null)
    try {
      await deletePipelineExportPreset(orgId, id)
      setPresets((prev) => (prev ?? []).filter((p) => p.id !== id))
    } catch (err) {
      setPresetActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setConfirmDeleteId(null)
    }
  }

  async function handleRenamePreset(id: string) {
    const name = (renameDrafts[id] ?? '').trim()
    if (!name) return
    setPresetActionError(null)
    try {
      const renamed = await renamePipelineExportPreset(orgId, id, name)
      setPresets((prev) => (prev ?? []).map((p) => (p.id === id ? renamed : p)))
    } catch (err) {
      setPresetActionError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    }
  }

  const allExcluded = colOrder.length > 0 && colOrder.length === excludedCols.size

  return (
    <div className="flex flex-col gap-3">
      {colOrder.length > 0 && (
        <details className="rounded-md border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-sm font-medium">
            🔀 Ordre et sélection des colonnes à l'export ({colOrder.length - excludedCols.size}/
            {colOrder.length} incluse(s))
          </summary>
          <p className="mt-2 text-xs text-[var(--muted)]">
            Décoche une colonne pour l'exclure de l'export, utilise les flèches pour changer son
            ordre dans le fichier généré.
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {colOrder.map((col, i) => (
              <li key={col} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={!excludedCols.has(col)}
                  onChange={() => toggleIncluded(col)}
                  aria-label={`Inclure la colonne ${col} dans l'export`}
                />
                <span className={`flex-1 text-sm ${excludedCols.has(col) ? 'text-[var(--muted)] line-through' : ''}`}>
                  {col}
                </span>
                <Button variant="secondary" onClick={() => moveUp(i)} disabled={i === 0}>
                  ⬆️
                </Button>
                <Button variant="secondary" onClick={() => moveDown(i)} disabled={i === colOrder.length - 1}>
                  ⬇️
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}

      <details className="rounded-md border border-[var(--border)] p-3" open={(presets?.length ?? 0) > 0}>
        <summary className="cursor-pointer text-sm font-medium">
          💾 Presets d'export (ordre + colonnes)
        </summary>

        {presetsError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {presetsError}</p>}

        {presets && presets.length === 0 && !presetsError && (
          <p className="mt-2 text-sm text-[var(--muted)]">Aucun preset enregistré pour l'instant.</p>
        )}

        {presets && presets.length > 0 && (
          <ul className="mt-2 flex flex-col gap-2">
            {presets.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] p-2">
                <Input
                  value={renameDrafts[p.id] ?? p.name}
                  onChange={(e) => setRenameDrafts((prev) => ({ ...prev, [p.id]: e.target.value }))}
                  className="max-w-[10rem]"
                />
                <span className="text-xs text-[var(--muted)]">
                  {p.included.length} incluse(s) / {p.excluded.length} exclue(s)
                </span>
                <Button variant="secondary" onClick={() => applyPreset(p)}>
                  Appliquer
                </Button>
                <Button variant="secondary" onClick={() => void handleRenamePreset(p.id)}>
                  Renommer
                </Button>
                <Button
                  variant={confirmDeleteId === p.id ? 'danger' : 'secondary'}
                  onClick={() => void handleDeletePreset(p.id)}
                >
                  {confirmDeleteId === p.id ? 'Confirmer la suppression' : '🗑️ Supprimer'}
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Input
            placeholder="Nom du preset"
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            className="max-w-xs"
          />
          <Button onClick={() => void handleSavePreset()} disabled={savingPreset || !presetName.trim()}>
            {savingPreset ? 'Enregistrement…' : '💾 Enregistrer'}
          </Button>
        </div>
        {presetActionError && <p className="mt-2 text-sm text-[var(--danger)]">Erreur : {presetActionError}</p>}
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="pipeline-export-filename" className="text-sm text-[var(--muted)]">
          Nom du fichier
        </label>
        <Input
          id="pipeline-export-filename"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          className="max-w-xs"
        />
        <span className="text-xs text-[var(--muted)]">
          → {(filename.trim() || 'export_pipeline')}.csv / .xlsx
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Exporter ces résultats</span>
        <Button
          variant="secondary"
          disabled={exporting !== null || filteredCount === 0 || allExcluded}
          onClick={() => void handleExport('csv')}
        >
          {exporting === 'csv' ? 'Préparation…' : 'Exporter CSV'}
        </Button>
        <Button
          variant="secondary"
          disabled={exporting !== null || filteredCount === 0 || allExcluded}
          onClick={() => void handleExport('xlsx')}
        >
          {exporting === 'xlsx' ? 'Préparation…' : 'Exporter Excel'}
        </Button>
        <span className="text-xs text-[var(--muted)]">
          {filteredCount} / {rowCount} ligne(s), avec le filtre/le dédoublonnage actuels.
        </span>
      </div>
      {allExcluded && (
        <p className="text-sm text-[var(--danger)]">
          Toutes les colonnes sont exclues -- inclus-en au moins une pour exporter.
        </p>
      )}
      {exportError && <p className="text-sm text-[var(--danger)]">Erreur d'export : {exportError}</p>}

      <SaveToDatabasePanel orgId={orgId} sessionId={sessionId} filterGroups={filterGroups} rowCount={filteredCount} />
    </div>
  )
}

// "💾 Enregistrer dans la base de données (CRM)" -- copie conforme de
// views/tab4_export.py:_render_save_to_database. Enregistre le résultat
// FILTRÉ (pas juste les colonnes de l'export ci-dessus) dans
// l'environnement choisi, avec la même vérification de doublon IBAN
// que l'import direct de la Base de données.
function SaveToDatabasePanel({
  orgId,
  sessionId,
  filterGroups,
  rowCount,
}: {
  orgId: string
  sessionId: string
  filterGroups: FilterGroup[]
  rowCount: number
}) {
  const { orgs, orgsError } = useOrgs()
  const { isAdmin } = useIsAdmin(true)

  const [targetOrgId, setTargetOrgId] = useState('')
  const [ibanCol, setIbanCol] = useState('')
  const [importName, setImportName] = useState('export_trieur')

  const [unknownColumns, setUnknownColumns] = useState<string[]>([])
  const [addUnknownColumns, setAddUnknownColumns] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveResult, setSaveResult] = useState<{ n_imported: number; n_alerts: number } | null>(null)

  useEffect(() => {
    if (orgs && orgs.length > 0 && !targetOrgId) setTargetOrgId(orgs[0].id)
  }, [orgs, targetOrgId])

  useEffect(() => {
    if (!targetOrgId || rowCount === 0) {
      setUnknownColumns([])
      return
    }
    let cancelled = false
    setChecking(true)
    setCheckError(null)
    previewSavePipelineSessionToDatabase(orgId, sessionId, { targetOrgId, filterGroups })
      .then((data) => {
        if (!cancelled) setUnknownColumns(data.unknown_columns)
      })
      .catch((err: unknown) => {
        if (!cancelled) setCheckError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
      .finally(() => {
        if (!cancelled) setChecking(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, sessionId, targetOrgId, JSON.stringify(filterGroups), rowCount])

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setSaveResult(null)
    try {
      const data = await savePipelineSessionToDatabase(orgId, sessionId, {
        targetOrgId,
        filterGroups,
        ibanCol: ibanCol || undefined,
        addUnknownColumns,
        importName,
      })
      setSaveResult({ n_imported: data.n_imported, n_alerts: data.n_alerts })
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setSaving(false)
    }
  }

  if (orgsError || !orgs || orgs.length === 0 || rowCount === 0) return null

  return (
    <details className="rounded-md border border-[var(--border)] p-3">
      <summary className="cursor-pointer text-sm font-medium">💾 Enregistrer dans la base de données (CRM)</summary>
      <p className="mt-2 text-xs text-[var(--muted)]">
        Enregistre les {rowCount} ligne(s) de la base filtrée (pas seulement les colonnes de l'export
        ci-dessus) dans l'environnement choisi, avec la même vérification de doublon IBAN que l'import
        direct de l'onglet Base de données. Si un fichier mélange plusieurs activités, filtre-le
        d'abord ci-dessus, enregistre, puis refais une passe pour l'autre activité.
      </p>

      <div className="mt-3 flex flex-col gap-2">
        <label className="text-xs text-[var(--muted)]">
          Environnement de destination
          <select
            className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-2 text-sm"
            value={targetOrgId}
            onChange={(e) => setTargetOrgId(e.target.value)}
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-[var(--muted)]">
          Colonne IBAN (optionnel, pour la vérification de doublon)
          <Input value={ibanCol} onChange={(e) => setIbanCol(e.target.value)} className="mt-1" placeholder="IBAN" />
        </label>

        <label className="text-xs text-[var(--muted)]">
          Nom de cet import
          <Input value={importName} onChange={(e) => setImportName(e.target.value)} className="mt-1" />
        </label>

        {checking && <p className="text-sm text-[var(--muted)]">Vérification des colonnes…</p>}
        {checkError && <p className="text-sm text-[var(--danger)]">Erreur : {checkError}</p>}
        {unknownColumns.length > 0 && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={addUnknownColumns} onChange={(e) => setAddUnknownColumns(e.target.checked)} />
            Ajouter {unknownColumns.join(', ')} aux colonnes maîtres de cet environnement
            {!isAdmin && ' (réservé aux administrateurs)'}
          </label>
        )}

        <div>
          <Button onClick={() => void handleSave()} disabled={saving || !targetOrgId}>
            {saving ? 'Enregistrement…' : '💾 Enregistrer dans cet environnement'}
          </Button>
        </div>

        {saveError && <p className="text-sm text-[var(--danger)]">Erreur : {saveError}</p>}
        {saveResult && (
          <p className="text-sm text-[var(--success,#16a34a)]">
            {saveResult.n_imported} ligne(s) enregistrée(s), {saveResult.n_alerts} alerte(s) de doublon IBAN
            créée(s).
          </p>
        )}
      </div>
    </details>
  )
}
