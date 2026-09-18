import { PIPELINE_UNASSIGNED } from '@/lib/api'

const PREVIEW_ROWS_MAX = 5

// Grille de mapping -- mirroir de views/tab2_import_mapping.py : "ligne 1
// = grille de selectbox (une par colonne source, options = colonnes
// maîtres disponibles), alignée AU-DESSUS d'un aperçu des premières
// lignes" plutôt qu'une liste verticale de champs. Défilement horizontal
// si beaucoup de colonnes (même patron que les tableaux larges de
// DatabaseScreen) -- on ne réduit jamais le nombre de colonnes affichées
// pour tenir sur un écran de téléphone.
export function PipelineMappingGrid({
  columns,
  previewRows,
  masterColumns,
  mapping,
  onMappingChange,
  duplicateMasterCols,
}: {
  columns: string[]
  previewRows: Record<string, unknown>[]
  masterColumns: string[]
  mapping: Record<string, string>
  onMappingChange: (col: string, master: string) => void
  duplicateMasterCols: string[]
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full min-w-max text-sm">
        <thead>
          <tr className="bg-[var(--muted-bg)] text-left">
            {columns.map((col) => (
              <th key={col} className="whitespace-nowrap px-3 py-2 font-medium">
                {col}
              </th>
            ))}
          </tr>
          <tr className="bg-[var(--muted-bg)] text-left">
            {columns.map((col) => {
              const value = mapping[col] ?? PIPELINE_UNASSIGNED
              const isDup = value !== PIPELINE_UNASSIGNED && duplicateMasterCols.includes(value)
              return (
                <th key={col} className="px-3 py-2">
                  <select
                    value={value}
                    onChange={(e) => onMappingChange(col, e.target.value)}
                    aria-label={`Colonne maître pour ${col}`}
                    className={
                      'w-full min-w-[9rem] rounded-md border bg-[var(--card)] px-2 py-1.5 text-sm font-normal ' +
                      (isDup ? 'border-[var(--danger)]' : 'border-[var(--border)]')
                    }
                  >
                    <option value={PIPELINE_UNASSIGNED}>(non assigné)</option>
                    {masterColumns.map((mc) => (
                      <option key={mc} value={mc}>
                        {mc}
                      </option>
                    ))}
                  </select>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {previewRows.slice(0, PREVIEW_ROWS_MAX).map((row, i) => (
            <tr key={i} className="border-t border-[var(--border)]">
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap px-3 py-2 text-[var(--muted)]">
                  {row[col] == null ? '' : String(row[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
