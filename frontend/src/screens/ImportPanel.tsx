import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  ApiError,
  confirmImport,
  getMasterColumns,
  previewImport,
  setMasterColumns,
  type ImportPreview,
  type ImportResult,
} from '@/lib/api'

// Import CSV/Excel dans la base -- mirroir de
// views/tab_database.py:_render_import : aperçu des colonnes détectées
// (via /import?dry_run=true, qui lit le fichier avec pandas côté
// serveur sans rien écrire), choix de la colonne IBAN, puis import réel
// avec vérification de doublon IBAN contre tout l'historique.
export function ImportPanel({
  orgId,
  isAdmin,
  onImported,
}: {
  orgId: string
  isAdmin: boolean
  onImported: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)

  const [ibanCol, setIbanCol] = useState<string>('')
  const [addUnknown, setAddUnknown] = useState(false)

  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)

  const [addingLater, setAddingLater] = useState(false)
  const [addLaterError, setAddLaterError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  function reset() {
    setFile(null)
    setPreview(null)
    setPreviewError(null)
    setIbanCol('')
    setAddUnknown(false)
    setResult(null)
    setImportError(null)
    setAddLaterError(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function handleFileChange(f: File | null) {
    setFile(f)
    setResult(null)
    setImportError(null)
    setPreview(null)
    setPreviewError(null)
    setIbanCol('')
    setAddUnknown(false)
    if (!f) return
    setPreviewLoading(true)
    try {
      const data = await previewImport(orgId, f)
      setPreview(data)
      // Suggestion automatique : une seule colonne dont le nom contient
      // "iban" -- si plusieurs correspondent, c'est ambigu : on laisse le
      // choix vide pour forcer une sélection explicite, comme demandé.
      const candidates = data.columns.filter((c) => c.toLowerCase().includes('iban'))
      if (candidates.length === 1) setIbanCol(candidates[0])
    } catch (err) {
      setPreviewError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleConfirm() {
    if (!file) return
    setImporting(true)
    setImportError(null)
    try {
      const data = await confirmImport(orgId, file, {
        ibanCol: ibanCol || null,
        addUnknownColumns: addUnknown,
      })
      setResult(data)
      onImported()
    } catch (err) {
      setImportError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setImporting(false)
    }
  }

  async function handleAddRemainingNow() {
    if (!result) return
    const remaining = result.unknown_columns.filter((c) => !result.added_to_master_columns.includes(c))
    if (remaining.length === 0) return
    setAddingLater(true)
    setAddLaterError(null)
    try {
      const current = await getMasterColumns(orgId)
      const merged = [...current.columns, ...remaining.filter((c) => !current.columns.includes(c))]
      await setMasterColumns(orgId, merged)
      setResult({ ...result, added_to_master_columns: [...result.added_to_master_columns, ...remaining] })
    } catch (err) {
      setAddLaterError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setAddingLater(false)
    }
  }

  const remainingUnknown = result
    ? result.unknown_columns.filter((c) => !result.added_to_master_columns.includes(c))
    : []

  const ambiguousIban =
    preview != null && preview.columns.filter((c) => c.toLowerCase().includes('iban')).length > 1

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">Importer un fichier</h2>
        <p className="text-sm text-[var(--muted)]">
          Chaque ligne est comparée à tout l'historique déjà en base pour cet environnement -- un
          même IBAN déjà vu, même sous un autre nom, déclenche une alerte au lieu d'être importé
          en double silencieusement.
        </p>
      </div>

      {!result && (
        <div className="flex flex-col gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => void handleFileChange(e.target.files?.[0] ?? null)}
            className="text-sm"
          />

          {previewLoading && (
            <>
              <p className="text-sm text-[var(--muted)]">Lecture du fichier…</p>
              <p className="text-xs font-medium text-[var(--danger)]">
                ⚠️ Ne quitte pas cette page (ni une autre appli/onglet) tant que la lecture est en
                cours -- ça coupe l'envoi et il faudra recommencer.
              </p>
            </>
          )}
          {previewError && <p className="text-sm text-[var(--danger)]">Erreur : {previewError}</p>}

          {preview && (
            <>
              <div className="overflow-x-auto rounded-lg shadow-[var(--ring-card)]">
                <table className="w-full min-w-max text-sm">
                  <thead>
                    <tr className="bg-[var(--muted-bg)] text-left">
                      {preview.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((row, i) => (
                      <tr key={i} className="border-t border-[var(--border)]">
                        {preview.columns.map((c) => (
                          <td key={c} className="whitespace-nowrap px-3 py-2">
                            {row[c] == null ? '' : String(row[c])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-sm text-[var(--muted)]">
                {preview.row_count} ligne(s) détectée(s) -- aperçu des {preview.preview_rows.length}
                {' '}premières.
              </p>

              <div>
                <label htmlFor="iban-col" className="mb-1 block text-sm text-[var(--muted)]">
                  Quelle colonne contient l'IBAN ?
                  {ambiguousIban && (
                    <span className="ml-2 text-[var(--danger)]">
                      Plusieurs colonnes ressemblent à un IBAN -- choisis la bonne.
                    </span>
                  )}
                </label>
                <select
                  id="iban-col"
                  className="rounded-md shadow-[var(--ring-card)] bg-[var(--card)] px-3 py-2 text-sm"
                  value={ibanCol}
                  onChange={(e) => setIbanCol(e.target.value)}
                >
                  <option value="">(aucune)</option>
                  {preview.columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              {preview.unknown_columns.length > 0 && (
                <div className="rounded-md shadow-[var(--ring-card)] bg-[var(--muted-bg)] p-3 text-sm">
                  <p className="mb-1 font-medium">
                    Colonne(s) inconnue(s) dans ce fichier : {preview.unknown_columns.join(', ')}
                  </p>
                  {isAdmin ? (
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={addUnknown}
                        onChange={(e) => setAddUnknown(e.target.checked)}
                      />
                      Les ajouter aux colonnes maîtres de l'environnement
                    </label>
                  ) : (
                    <p className="text-[var(--muted)]">
                      Elles seront importées quand même -- seul un administrateur peut les ajouter
                      aux réglages.
                    </p>
                  )}
                </div>
              )}

              {importing && (
                <p className="text-xs font-medium text-[var(--danger)]">
                  ⚠️ Ne quitte pas cette page (ni une autre appli/onglet) tant que l'import est en
                  cours -- ça coupe l'envoi et il faudra recommencer.
                </p>
              )}
              {importError && <p className="text-sm text-[var(--danger)]">Erreur : {importError}</p>}

              <div>
                <Button onClick={() => void handleConfirm()} disabled={importing}>
                  {importing ? 'Import en cours…' : 'Vérifier et importer'}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--success,#16a34a)]">
            {result.n_imported} ligne(s) importée(s), {result.n_alerts} alerte(s) de doublon IBAN
            créée(s).
          </p>

          {result.unknown_columns.length > 0 && (
            <div className="rounded-md shadow-[var(--ring-card)] bg-[var(--muted-bg)] p-3 text-sm">
              {result.added_to_master_columns.length > 0 && (
                <p>
                  Ajoutée(s) aux colonnes maîtres : {result.added_to_master_columns.join(', ')}
                </p>
              )}
              {remainingUnknown.length > 0 && (
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span>Colonne(s) non ajoutée(s) : {remainingUnknown.join(', ')}</span>
                  {isAdmin && (
                    <Button
                      variant="secondary"
                      onClick={() => void handleAddRemainingNow()}
                      disabled={addingLater}
                    >
                      {addingLater ? 'Ajout…' : 'Les ajouter maintenant'}
                    </Button>
                  )}
                </div>
              )}
              {addLaterError && <p className="text-[var(--danger)]">Erreur : {addLaterError}</p>}
            </div>
          )}

          <div>
            <Button variant="secondary" onClick={reset}>
              Importer un autre fichier
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
