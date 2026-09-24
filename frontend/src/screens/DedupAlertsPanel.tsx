import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError, listDedupAlerts, resolveDedupAlert, type DedupAlert } from '@/lib/api'

// Alertes de doublon IBAN en attente, avec diff champ par champ -- mirroir
// de views/tab_database.py:_render_alerts (diff calculé côté serveur par
// diff_rows(), jamais réimplémenté ici). Se cache entièrement quand il
// n'y a aucune alerte en attente, comme côté Streamlit -- rien à traiter,
// rien à montrer.
export function DedupAlertsPanel({
  orgId,
  refreshKey,
  onResolved,
}: {
  orgId: string
  refreshKey: number
  onResolved: () => void
}) {
  const [alerts, setAlerts] = useState<DedupAlert[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resolvingId, setResolvingId] = useState<string | null>(null)
  const [resolveError, setResolveError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listDedupAlerts(orgId)
      .then((data) => {
        if (!cancelled) setAlerts(data)
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

  async function handleResolve(alertId: string, status: 'confirmed_duplicate' | 'confirmed_different') {
    setResolvingId(alertId)
    setResolveError(null)
    try {
      await resolveDedupAlert(orgId, alertId, status)
      setAlerts((prev) => (prev ?? []).filter((a) => a.id !== alertId))
      onResolved()
    } catch (err) {
      setResolveError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
    } finally {
      setResolvingId(null)
    }
  }

  if (loading) {
    return <p className="mb-4 text-sm text-[var(--muted)]">Vérification des alertes de doublon…</p>
  }

  if (error) {
    return (
      <p className="mb-4 text-sm text-[var(--danger)]">
        Impossible de charger les alertes de doublon : {error}
      </p>
    )
  }

  if (!alerts || alerts.length === 0) return null

  return (
    <div className="mb-4 rounded-lg shadow-[inset_0_0_0_1px_var(--danger)] bg-[var(--card)] p-3">
      <p className="mb-3 text-sm font-semibold text-[var(--danger)]">
        ⚠️ {alerts.length} alerte{alerts.length > 1 ? 's' : ''} de doublon IBAN en attente
      </p>
      {resolveError && <p className="mb-2 text-sm text-[var(--danger)]">Erreur : {resolveError}</p>}
      <div className="flex flex-col gap-4">
        {alerts.map((alert) => (
          <div key={alert.id} className="rounded-md shadow-[var(--ring-card)] p-3">
            <div className="overflow-x-auto">
              <table className="w-full min-w-max text-sm">
                <thead>
                  <tr className="bg-[var(--muted-bg)] text-left">
                    <th className="whitespace-nowrap px-3 py-2 font-medium">Champ</th>
                    <th className="whitespace-nowrap px-3 py-2 font-medium">Nouvelle ligne</th>
                    <th className="whitespace-nowrap px-3 py-2 font-medium">Déjà en base</th>
                    <th className="whitespace-nowrap px-3 py-2 font-medium">Différent</th>
                  </tr>
                </thead>
                <tbody>
                  {alert.diff.map((row) => (
                    <tr key={row.Champ} className="border-t border-[var(--border)]">
                      <td className="whitespace-nowrap px-3 py-2 font-medium">{row.Champ}</td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {row['Nouvelle ligne'] == null ? '' : String(row['Nouvelle ligne'])}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {row['Déjà en base'] == null ? '' : String(row['Déjà en base'])}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">{row.Différent}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {alert.note && <p className="mt-2 text-xs text-[var(--muted)]">{alert.note}</p>}
            <div className="mt-3 flex gap-2">
              <Button
                variant="danger"
                disabled={resolvingId === alert.id}
                onClick={() => void handleResolve(alert.id, 'confirmed_duplicate')}
              >
                {resolvingId === alert.id ? '…' : "C'est un doublon"}
              </Button>
              <Button
                variant="secondary"
                disabled={resolvingId === alert.id}
                onClick={() => void handleResolve(alert.id, 'confirmed_different')}
              >
                {resolvingId === alert.id ? '…' : 'Ce sont 2 personnes différentes'}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
