import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/AuthContext'
import { useIsAdmin, useOrgs } from '@/lib/useAccount'
import {
  ApiError,
  getMasterColumns,
  type ColFilters,
  type PipelineFilterGroup,
  type PipelineMappingResult,
  type PipelineSessionCreated,
} from '@/lib/api'
import { Tab1ColonnesMaitres } from './pipeline/Tab1ColonnesMaitres'
import { Tab2ImportMapping } from './pipeline/Tab2ImportMapping'
import { Tab3FiltrageDedup, emptyCriterion, newUid, type UiGroup } from './pipeline/Tab3FiltrageDedup'
import { Tab4Export } from './pipeline/Tab4Export'

// Trieur de Data -- 4 onglets, mirroir de app.py (st.tabs) et des 4 vues
// Streamlit (views/tab1_colonnes_maitres.py, tab2_import_mapping.py,
// tab3_filtrage_dedup.py, tab4_export.py). Les 4 onglets restent toujours
// accessibles (comme st.tabs, qui monte tout dans le DOM) -- un onglet pas
// encore utilisable affiche juste un message d'info, jamais un contrôle
// d'une étape non atteinte.
//
// État partagé entre onglets (équivalent de st.session_state) : la
// session de pipeline (fichier importé + mapping), le filtre
// multi-critères et les filtres additionnels (recherche/colonnes), et
// l'ordre/sélection des colonnes à l'export -- tout vit ICI, chaque
// onglet ne porte que son état d'affichage local (voir chaque composant).
type TabKey = '1' | '2' | '3' | '4'

const TAB_LABELS: [TabKey, string][] = [
  ['1', '1. Colonnes maîtres'],
  ['2', '2. Import et Mapping'],
  ['3', '3. Filtrage & Dedup'],
  ['4', '4. Export'],
]

export function PipelineScreen() {
  const { session: authSession, signOut } = useAuth()
  const { orgs, orgsError, orgId, setOrgId } = useOrgs()
  const { isAdmin } = useIsAdmin(true)

  const [tab, setTab] = useState<TabKey>('1')

  const [masterColumns, setMasterColumns] = useState<string[] | null>(null)
  const [masterColumnsError, setMasterColumnsError] = useState<string | null>(null)

  const [pipelineSession, setPipelineSession] = useState<PipelineSessionCreated | null>(null)
  const [mappingResult, setMappingResult] = useState<PipelineMappingResult | null>(null)

  // [13] Filtre multi-critères de l'onglet 3 (groupes OU / critères ET) --
  // état d'édition local (avec ids pour les clés React), converti en
  // PipelineFilterGroup[] (sans id) juste avant chaque appel API.
  const [groups, setGroups] = useState<UiGroup[]>([{ id: newUid(), criteria: [emptyCriterion('')] }])
  const apiGroups: PipelineFilterGroup[] = useMemo(
    () => groups.map((g) => g.criteria.map((c) => ({ column: c.column, kind: c.kind, values: c.values }))),
    [groups],
  )

  const [search, setSearch] = useState('')
  const [colFilters, setColFilters] = useState<ColFilters>({})

  // Incrémenté après une suppression de doublons définitive (onglet 3) --
  // force les onglets 3/4 à recharger le compte de lignes réel.
  const [refreshKey, setRefreshKey] = useState(0)

  const [colOrder, setColOrder] = useState<string[]>([])
  const [excludedCols, setExcludedCols] = useState<Set<string>>(new Set())
  const [filenameBase, setFilenameBase] = useState('export_leads')

  function toggleColIncluded(col: string) {
    setExcludedCols((prev) => {
      const next = new Set(prev)
      if (next.has(col)) next.delete(col)
      else next.add(col)
      return next
    })
  }

  function moveColUp(i: number) {
    if (i === 0) return
    setColOrder((prev) => {
      const next = [...prev]
      ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
      return next
    })
  }

  function moveColDown(i: number) {
    setColOrder((prev) => {
      if (i >= prev.length - 1) return prev
      const next = [...prev]
      ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
      return next
    })
  }

  // `defaultColumn` est explicite (pas déduit de `masterColumns` en lisant
  // la closure) : appelé juste après un changement d'org (handleOrgChange
  // ci-dessous), `masterColumns` de CE rendu est encore celui de l'ANCIENNE
  // org (le state vient tout juste d'être vidé par `setMasterColumns(null)`,
  // qui ne s'applique qu'au rendu suivant) -- utiliser la valeur périmée
  // initialiserait le 1er critère de filtre sur une colonne qui n'existe
  // plus, un filtre dessus ne matcherait alors jamais.
  function resetPipeline(defaultColumn: string = masterColumns?.[0] ?? '') {
    setPipelineSession(null)
    setMappingResult(null)
    setGroups([{ id: newUid(), criteria: [emptyCriterion(defaultColumn)] }])
    setSearch('')
    setColFilters({})
    setRefreshKey(0)
    setColOrder([])
    setExcludedCols(new Set())
    setFilenameBase('export_leads')
    setTab('2')
  }

  // `cancelled` : la requête d'une ANCIENNE org peut se résoudre après le
  // changement d'org suivant (réseau lent, org changée deux fois vite) --
  // sans ce garde, elle écraserait `masterColumns` avec une liste qui ne
  // correspond plus à `orgId` (trouvaille Copilot, PR #25 -- même défaut
  // que l'ancienne implémentation évitait déjà avec ce même patron).
  function loadMasterColumns(orgIdVal: string): () => void {
    let cancelled = false
    setMasterColumnsError(null)
    getMasterColumns(orgIdVal)
      .then((data) => {
        if (!cancelled) setMasterColumns(data.columns)
      })
      .catch((err: unknown) => {
        if (!cancelled) setMasterColumnsError(err instanceof ApiError ? err.message : 'Erreur inconnue.')
      })
    return () => {
      cancelled = true
    }
  }

  // Chargement initial des colonnes maîtres (utilisées par les onglets 2 et
  // 3) -- Tab1ColonnesMaitres notifie aussi ce composant via
  // onColumnsChange dès qu'elles sont créées/modifiées, pour rester à jour
  // sans revenir sur l'onglet 1.
  useEffect(() => {
    if (!orgId) return
    return loadMasterColumns(orgId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId])

  function handleOrgChange(nextOrgId: string) {
    setOrgId(nextOrgId)
    setMasterColumns(null)
    resetPipeline('')
    setTab('1')
  }

  const sessionMapped = mappingResult !== null

  return (
    <div className="mx-auto max-w-3xl p-4">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Trieur de Data</h1>
        <div className="flex items-center gap-2 text-sm text-[var(--muted)]">
          <span>{authSession?.user.email}</span>
          <Button variant="secondary" onClick={() => void signOut()}>
            Se déconnecter
          </Button>
        </div>
      </header>
      <p className="mb-4 text-sm text-[var(--muted)]">
        Import Excel/CSV/PDF ou Google Sheets → mapping colonnes → aperçu → filtrage → export.
      </p>

      {orgsError && (
        <p className="mb-4 text-sm text-[var(--danger)]">
          Impossible de charger les environnements : {orgsError}
        </p>
      )}

      {orgs && orgs.length === 0 && !orgsError && (
        <p className="text-sm text-[var(--muted)]">
          Ton compte n'a accès à aucun environnement pour l'instant. Contacte l'administrateur.
        </p>
      )}

      {orgs && orgs.length > 0 && (
        <div className="mb-4 flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="pipeline-org-switcher" className="text-sm text-[var(--muted)]">
              Environnement
            </label>
            <select
              id="pipeline-org-switcher"
              className="rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"
              value={orgId ?? ''}
              onChange={(e) => handleOrgChange(e.target.value)}
            >
              {orgs.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-[var(--muted)]">
            Un environnement (ex. « Prélèvement », « Énergie ») a ses propres colonnes maîtres et
            ses propres imports -- change-le ici pour cloisonner un autre type de données, sans
            mélanger les fichiers ou les colonnes entre les deux.
          </p>
        </div>
      )}

      {orgId && (
        <>
          <div className="mb-4 flex flex-wrap gap-1 border-b border-[var(--border)]">
            {TAB_LABELS.map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={
                  'rounded-t-md px-3 py-2 text-sm font-medium ' +
                  (tab === key
                    ? 'border-b-2 border-[var(--primary)] text-[var(--foreground)]'
                    : 'text-[var(--muted)] hover:text-[var(--foreground)]')
                }
              >
                {label}
              </button>
            ))}
          </div>

          {tab === '1' && (
            <Tab1ColonnesMaitres
              orgId={orgId}
              isAdmin={isAdmin}
              onColumnsChange={(cols) => {
                setMasterColumns(cols)
                setMasterColumnsError(null)
              }}
            />
          )}

          {tab === '2' && (
            <Tab2ImportMapping
              orgId={orgId}
              masterColumns={masterColumns}
              masterColumnsError={masterColumnsError}
              session={pipelineSession}
              mappingResult={mappingResult}
              onSessionCreated={(s) => {
                setPipelineSession(s)
                setMappingResult(null)
              }}
              onMapped={(result) => {
                setMappingResult(result)
                setRefreshKey(0)
              }}
              onResetSession={resetPipeline}
            />
          )}

          {tab === '3' && (
            <Tab3FiltrageDedup
              orgId={orgId}
              sessionId={pipelineSession?.session_id ?? null}
              sessionMapped={sessionMapped}
              masterColumns={masterColumns}
              groups={groups}
              setGroups={setGroups}
              apiGroups={apiGroups}
              search={search}
              setSearch={setSearch}
              colFilters={colFilters}
              setColFilters={setColFilters}
              refreshKey={refreshKey}
              onDedupeApplied={() => setRefreshKey((k) => k + 1)}
            />
          )}

          {tab === '4' && (
            <Tab4Export
              orgId={orgId}
              sessionId={pipelineSession?.session_id ?? null}
              sessionMapped={sessionMapped}
              mappingResult={mappingResult}
              masterColumns={masterColumns}
              search={search}
              colFilters={colFilters}
              apiGroups={apiGroups}
              refreshKey={refreshKey}
              colOrder={colOrder}
              setColOrder={setColOrder}
              excludedCols={excludedCols}
              toggleColIncluded={toggleColIncluded}
              moveColUp={moveColUp}
              moveColDown={moveColDown}
              filenameBase={filenameBase}
              setFilenameBase={setFilenameBase}
            />
          )}
        </>
      )}
    </div>
  )
}
