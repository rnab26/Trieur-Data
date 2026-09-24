import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { FILTER_OPERATORS, type ColFilters, type FilterOperator } from '@/lib/api'

const SELECT_CLASS =
  'rounded-md shadow-[var(--ring-card)] bg-[var(--card)] px-2 py-2 text-sm text-[var(--foreground)]'

// Filtres par colonne "façon Google Sheets" -- mirroir de
// views/tab_database.py:_render_client_list (section "🔎 Filtres par
// colonne") : un opérateur + une valeur par colonne, combinés entre eux
// (ET), en plus de la recherche libre. `filters` reste la valeur BRUTE
// tapée par l'utilisateur (pas mise en minuscules) -- c'est le parent
// qui la normalise avant de l'envoyer à l'API, pour que réappliquer une
// vue enregistrée réaffiche exactement ce qui a été tapé.
export function ColumnFilters({
  columns,
  filters,
  onChange,
}: {
  columns: string[]
  filters: ColFilters
  onChange: (next: ColFilters) => void
}) {
  const [open, setOpen] = useState(false)
  const activeCount = Object.keys(filters).length

  function setFilter(col: string, patch: Partial<{ op: FilterOperator; value: string }>) {
    const current = filters[col] ?? { op: 'contient' as FilterOperator, value: '' }
    const next = { ...current, ...patch }
    const rest = { ...filters }
    const needsValue = next.op !== 'vide' && next.op !== 'non vide'
    if (needsValue && next.value.trim() === '') {
      // Valeur vide et opérateur qui en a besoin : pas un filtre actif,
      // on l'enlève pour ne pas envoyer un filtre inutile à l'API --
      // mais on garde l'opérateur choisi affiché même sans valeur.
      delete rest[col]
      onChange(rest)
      // On garde tout de même l'opérateur affiché localement via un
      // filtre "en attente" (valeur vide, absent du payload API).
      setPendingOp(col, next.op)
      return
    }
    rest[col] = next
    onChange(rest)
    clearPendingOp(col)
  }

  // Opérateur choisi pour une colonne sans valeur encore tapée -- pas
  // envoyé à l'API (voir setFilter), mais doit rester affiché dans le
  // <select> tant que l'utilisateur n'a pas changé de colonne ni
  // rechargé la page.
  const [pendingOps, setPendingOpsState] = useState<Record<string, FilterOperator>>({})
  function setPendingOp(col: string, op: FilterOperator) {
    setPendingOpsState((prev) => ({ ...prev, [col]: op }))
  }
  function clearPendingOp(col: string) {
    setPendingOpsState((prev) => {
      if (!(col in prev)) return prev
      const next = { ...prev }
      delete next[col]
      return next
    })
  }

  function clearAll() {
    onChange({})
    setPendingOpsState({})
  }

  return (
    <div className="mb-4 rounded-lg shadow-[var(--ring-card)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium"
      >
        <span>
          🔎 Filtres par colonne{activeCount > 0 ? ` (${activeCount} actif${activeCount > 1 ? 's' : ''})` : ''}
        </span>
        <span className="text-[var(--muted)]">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-[var(--border)] p-3">
          <p className="mb-3 text-xs text-[var(--muted)]">
            Combinés entre eux (ET), insensible à la casse.
          </p>
          {columns.length === 0 && (
            <p className="text-sm text-[var(--muted)]">Aucune colonne à filtrer pour l'instant.</p>
          )}
          <div className="flex flex-col gap-2">
            {columns.map((col) => {
              const current = filters[col]
              const op = current?.op ?? pendingOps[col] ?? 'contient'
              const value = current?.value ?? ''
              const needsValue = op !== 'vide' && op !== 'non vide'
              return (
                <div key={col} className="flex flex-wrap items-center gap-2">
                  <span className="w-32 flex-shrink-0 truncate text-sm" title={col}>
                    {col}
                  </span>
                  <select
                    className={SELECT_CLASS}
                    value={op}
                    onChange={(e) => setFilter(col, { op: e.target.value as FilterOperator })}
                  >
                    {FILTER_OPERATORS.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                  <Input
                    className="max-w-xs"
                    value={value}
                    disabled={!needsValue}
                    placeholder={needsValue ? col : '(aucune valeur nécessaire)'}
                    onChange={(e) => setFilter(col, { op, value: e.target.value })}
                  />
                </div>
              )
            })}
          </div>
          {activeCount > 0 && (
            <div className="mt-3">
              <Button variant="secondary" onClick={clearAll}>
                Effacer tous les filtres
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
