import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { ApiError, getDashboard, type Dashboard } from '@/lib/api'

// Résumé "où j'en suis" en haut de la Base de données -- mirroir de
// views/tab_database.py:_render_dashboard (nombre de clients, alertes de
// doublon IBAN en attente, dernier import). Recalculé à chaque fois que
// `refreshKey` change (après un import, une suppression...), pour ne
// jamais afficher un total périmé.
export function DashboardPanel({ orgId, refreshKey }: { orgId: string; refreshKey: number }) {
  const [data, setData] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getDashboard(orgId)
      .then((res) => {
        if (!cancelled) setData(res)
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
  }, [orgId, refreshKey])

  if (loading) {
    return <p className="mb-4 text-sm text-[var(--muted)]">Chargement du tableau de bord…</p>
  }

  if (error) {
    return (
      <p className="mb-4 text-sm text-[var(--danger)]">
        Impossible de charger le tableau de bord : {error}
      </p>
    )
  }

  if (!data) return null

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card>
        <CardContent>
          <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Clients</p>
          <p className="text-2xl font-semibold">{data.total_records}</p>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Alertes en attente</p>
          <p
            className={
              'text-2xl font-semibold' + (data.alerts_pending > 0 ? ' text-[var(--danger)]' : '')
            }
          >
            {data.alerts_pending}
          </p>
          <p className="text-xs text-[var(--muted)]">
            {data.alerts_pending > 0 ? 'à traiter' : 'aucune'}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Dernier import</p>
          {data.last_import ? (
            <>
              <p className="truncate text-sm font-semibold" title={data.last_import.source_filename}>
                {data.last_import.source_filename}
              </p>
              <p className="text-xs text-[var(--muted)]">le {data.last_import.imported_at}</p>
            </>
          ) : (
            <p className="text-sm text-[var(--muted)]">—</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
