// Client pour l'API REST FastAPI (api/main.py). Chaque appel porte le
// jeton Supabase courant en "Authorization: Bearer <token>" -- voir
// api/main.py:get_current_ctx pour le contrat côté serveur.

import { supabase } from './supabase'

const API_URL = import.meta.env.VITE_API_URL

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) {
    throw new ApiError(401, 'Aucune session active. Reconnecte-toi.')
  }
  return { Authorization: `Bearer ${token}` }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await authHeader()
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...headers,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // pas de corps JSON -- on garde le statusText
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export type Organization = {
  id: string
  name: string
  [key: string]: unknown
}

export type RecordRow = {
  id: string
  [key: string]: unknown
}

export type RecordsPage = {
  page: number
  page_size: number
  total: number
  fetched: number
  rows: RecordRow[]
}

export type Dashboard = {
  total_records: number
  alerts_pending: number
  last_import: { source_filename: string; imported_at: string } | null
}

export function listOrgs() {
  return request<Organization[]>('/orgs')
}

export function getDashboard(orgId: string) {
  return request<Dashboard>(`/orgs/${orgId}/dashboard`)
}

// Opérateurs de filtre par colonne, "façon Google Sheets" -- même liste
// que views/tab_database.py:FILTER_OPERATORS, ne pas laisser diverger.
export const FILTER_OPERATORS = ['contient', 'ne contient pas', 'égal à', 'vide', 'non vide'] as const
export type FilterOperator = (typeof FILTER_OPERATORS)[number]

export type ColFilter = { op: FilterOperator; value: string }
export type ColFilters = Record<string, ColFilter>

export function listRecords(
  orgId: string,
  opts: { page?: number; pageSize?: number; search?: string; colFilters?: ColFilters } = {},
) {
  const params = new URLSearchParams()
  params.set('page', String(opts.page ?? 1))
  params.set('page_size', String(opts.pageSize ?? 50))
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(opts.colFilters))
  }
  return request<RecordsPage>(`/orgs/${orgId}/records?${params.toString()}`)
}

export function getRecord(orgId: string, recordId: string) {
  return request<RecordRow>(`/orgs/${orgId}/records/${recordId}`)
}

export function updateRecord(orgId: string, recordId: string, data: Record<string, unknown>) {
  return request<{ id: string; data: Record<string, unknown>; updated: boolean }>(
    `/orgs/${orgId}/records/${recordId}`,
    { method: 'PATCH', body: JSON.stringify({ data }) },
  )
}

export function getMasterColumns(orgId: string) {
  return request<{ columns: string[] }>(`/orgs/${orgId}/master-columns`)
}

export function setMasterColumns(orgId: string, columns: string[]) {
  return request<{ columns: string[] }>(`/orgs/${orgId}/master-columns`, {
    method: 'POST',
    body: JSON.stringify({ columns }),
  })
}

export type Profile = {
  id: string
  full_name?: string | null
  is_super_admin?: boolean
  [key: string]: unknown
}

export function getMe() {
  return request<{ profile: Profile }>('/me')
}

export type ImportPreview = {
  columns: string[]
  unknown_columns: string[]
  preview_rows: Record<string, unknown>[]
  row_count: number
}

export type ImportResult = {
  n_imported: number
  n_alerts: number
  unknown_columns: string[]
  added_to_master_columns: string[]
}

// Requête multipart -- pas de JSON, donc pas d'appel à `request()`
// (qui pose systématiquement 'Content-Type: application/json').
async function importRequest<T>(
  orgId: string,
  file: File,
  opts: { ibanCol?: string | null; addUnknownColumns?: boolean; dryRun?: boolean },
): Promise<T> {
  const headers = await authHeader()
  const form = new FormData()
  form.set('file', file)
  if (opts.ibanCol) form.set('iban_col', opts.ibanCol)
  form.set('add_unknown_columns', String(opts.addUnknownColumns ?? false))
  form.set('dry_run', String(opts.dryRun ?? false))
  const res = await fetch(`${API_URL}/orgs/${orgId}/import`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // pas de corps JSON -- on garde le statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export type SavedView = {
  id: string
  name: string
  search: string
  col_filters: ColFilters
  visible_cols: string[]
  [key: string]: unknown
}

export function listSavedViews(orgId: string) {
  return request<SavedView[]>(`/orgs/${orgId}/saved-views`)
}

export function saveSavedView(
  orgId: string,
  body: { name: string; search: string; colFilters: ColFilters; visibleCols: string[] },
) {
  return request<SavedView>(`/orgs/${orgId}/saved-views`, {
    method: 'POST',
    body: JSON.stringify({
      name: body.name,
      search: body.search,
      col_filters: body.colFilters,
      visible_cols: body.visibleCols,
    }),
  })
}

export function deleteSavedView(orgId: string, viewId: string) {
  return request<{ id: string; deleted: boolean }>(`/orgs/${orgId}/saved-views/${viewId}`, {
    method: 'DELETE',
  })
}

// Suppression groupée -- voir api/main.py:bulk_delete_records (boucle
// serveur sur delete_record(), aucune logique dupliquée ici).
export function bulkDeleteRecords(orgId: string, ids: string[]) {
  return request<{ n_deleted: number }>(`/orgs/${orgId}/records`, {
    method: 'DELETE',
    body: JSON.stringify({ ids }),
  })
}

// Modification en masse d'UN SEUL champ pour toute la sélection -- voir
// api/main.py:bulk_update_records. `value` reste `unknown` (pas
// `string`) : une valeur "fausse" (0, false) est une vraie valeur, pas
// une case vide, même piège que le reste du projet -- l'appelant ne doit
// jamais la convertir en chaîne vide avant d'appeler cette fonction.
export function bulkUpdateRecords(orgId: string, ids: string[], field: string, value: unknown) {
  return request<{ n_updated: number; n_requested: number }>(`/orgs/${orgId}/records/bulk`, {
    method: 'PATCH',
    body: JSON.stringify({ ids, field, value }),
  })
}

export type DiffRow = {
  Champ: string
  'Nouvelle ligne': unknown
  'Déjà en base': unknown
  Différent: string
}

export type DedupAlert = {
  id: string
  note: string
  created_at: string | null
  diff: DiffRow[]
}

export function listDedupAlerts(orgId: string) {
  return request<DedupAlert[]>(`/orgs/${orgId}/dedup-alerts`)
}

export type DedupAlertStatus = 'confirmed_duplicate' | 'confirmed_different'

export function resolveDedupAlert(orgId: string, alertId: string, status: DedupAlertStatus) {
  return request<{ id: string; status: DedupAlertStatus }>(
    `/orgs/${orgId}/dedup-alerts/${alertId}/resolve`,
    { method: 'POST', body: JSON.stringify({ status }) },
  )
}

// Export CSV/Excel -- déclenche un téléchargement navigateur, pas de
// JSON en retour (voir api/main.py:export_org_records). `knownCols` :
// les colonnes actuellement CONNUES à l'écran (lot chargé), référence
// pour détecter un masquage explicite -- une colonne hors de ce lot
// (jamais vue) reste incluse même si elle n'est pas dans `visibleCols`.
export async function exportRecords(
  orgId: string,
  opts: {
    format: 'csv' | 'xlsx'
    search?: string
    colFilters?: ColFilters
    visibleCols?: string[]
    knownCols?: string[]
  },
): Promise<void> {
  const headers = await authHeader()
  const params = new URLSearchParams()
  params.set('format', opts.format)
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersExport(opts.colFilters)))
  }
  if (opts.visibleCols) params.set('visible_cols', opts.visibleCols.join(','))
  if (opts.knownCols) params.set('known_cols', opts.knownCols.join(','))

  const res = await fetch(`${API_URL}/orgs/${orgId}/records/export?${params.toString()}`, { headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // pas de corps JSON -- on garde le statusText
    }
    throw new ApiError(res.status, detail)
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const filename = match ? match[1] : `export.${opts.format}`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Même normalisation (valeur en minuscules) que toApiColFilters côté
// DatabaseScreen.tsx -- dupliquée ici en interne (fonction non exportée
// par ce module) pour que exportRecords reste autonome sans dépendre
// d'un helper défini dans un écran.
function toApiColFiltersExport(filters: ColFilters): ColFilters {
  const out: ColFilters = {}
  for (const [col, f] of Object.entries(filters)) {
    out[col] = { op: f.op, value: f.value.toLowerCase() }
  }
  return out
}

export function previewImport(orgId: string, file: File) {
  return importRequest<ImportPreview>(orgId, file, { dryRun: true })
}

// ---------------------------------------------------------------
// Cockpit -- chantiers de développement du logiciel lui-même (voir
// api/main.py, section "Cockpit"). Réservé aux administrateurs : ces
// appels renvoient une ApiError 403 pour tout autre compte.
// ---------------------------------------------------------------

export const CHANTIER_STATUSES = ['a_faire', 'en_cours', 'attente_retour', 'termine', 'abandonne'] as const
export type ChantierStatus = (typeof CHANTIER_STATUSES)[number]
export const CHANTIER_PRIORITIES = ['basse', 'normale', 'haute'] as const
export type ChantierPriority = (typeof CHANTIER_PRIORITIES)[number]

export type Chantier = {
  id: string
  org_id: string
  title: string
  status: ChantierStatus
  priority: ChantierPriority
  theme: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type Section = {
  id: string
  org_id: string
  nom: string
  position: number
}

export type ChantierMessage = {
  id: string
  chantier_id: string
  author_type: 'user' | 'claude'
  author: string
  body: string
  created_at: string
}

export type ChantierTodo = {
  id: string
  chantier_id: string
  body: string
  done: boolean
  position: number
  done_at: string | null
}

export function listChantiers(orgId: string) {
  return request<Chantier[]>(`/orgs/${orgId}/chantiers`)
}

export function listSections(orgId: string) {
  return request<Section[]>(`/orgs/${orgId}/sections`)
}

export function createChantier(
  orgId: string,
  body: { title: string; priority: ChantierPriority; theme?: string | null },
) {
  return request<Chantier>(`/orgs/${orgId}/chantiers`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createSection(orgId: string, nom: string) {
  return request<Section>(`/orgs/${orgId}/sections`, {
    method: 'POST',
    body: JSON.stringify({ nom }),
  })
}

export function updateChantierStatus(orgId: string, chantierId: string, status: ChantierStatus) {
  return request<{ id: string; status: ChantierStatus }>(
    `/orgs/${orgId}/chantiers/${chantierId}/status`,
    { method: 'PATCH', body: JSON.stringify({ status }) },
  )
}

export function listChantierMessages(orgId: string, chantierId: string) {
  return request<ChantierMessage[]>(`/orgs/${orgId}/chantiers/${chantierId}/messages`)
}

export function addChantierMessage(orgId: string, chantierId: string, body: string) {
  return request<ChantierMessage[]>(`/orgs/${orgId}/chantiers/${chantierId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  })
}

export function listChantierTodos(orgId: string, chantierId: string) {
  return request<ChantierTodo[]>(`/orgs/${orgId}/chantiers/${chantierId}/todos`)
}

export function addChantierTodo(orgId: string, chantierId: string, body: string) {
  return request<ChantierTodo[]>(`/orgs/${orgId}/chantiers/${chantierId}/todos`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  })
}

export function setChantierTodoDone(orgId: string, chantierId: string, todoId: string, done: boolean) {
  return request<{ id: string; done: boolean }>(
    `/orgs/${orgId}/chantiers/${chantierId}/todos/${todoId}`,
    { method: 'PATCH', body: JSON.stringify({ done }) },
  )
}

export function confirmImport(
  orgId: string,
  file: File,
  opts: { ibanCol?: string | null; addUnknownColumns?: boolean },
) {
  return importRequest<ImportResult>(orgId, file, { ...opts, dryRun: false })
}

// ---------------------------------------------------------------
// Pipeline "Trieur de Data" -- étape 1 (import + mapping), voir
// api/main.py section "Pipeline Trieur de Data". Les colonnes maîtres
// cibles du mapping restent get/setMasterColumns ci-dessus, PAS une
// deuxième liste -- ne jamais dupliquer cette notion côté frontend non
// plus.
// ---------------------------------------------------------------

// Sentinelle "non assigné" -- même valeur exacte que
// trieur/matching.py:auto_assign_columns_fast et api/main.py, ne jamais
// diverger (le backend compare cette chaîne littéralement).
export const PIPELINE_UNASSIGNED = '(non assigne)'

export type PipelineSessionCreated = {
  session_id: string
  status: string
  row_count: number
  columns: string[]
  unknown_columns: string[]
  preview_rows: Record<string, unknown>[]
}

// Requête multipart dédiée (fichier seul, pas d'autres champs) -- même
// raison que importRequest ci-dessus : rester autonome plutôt que de
// partager un helper générique qui devrait gérer deux formes de champs
// différentes.
async function uploadPipelineFile<T>(orgId: string, file: File): Promise<T> {
  const headers = await authHeader()
  const form = new FormData()
  form.set('file', file)
  const res = await fetch(`${API_URL}/orgs/${orgId}/pipeline/sessions`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // pas de corps JSON -- on garde le statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export function createPipelineSession(orgId: string, file: File) {
  return uploadPipelineFile<PipelineSessionCreated>(orgId, file)
}

export type PipelineMappingSuggestion = {
  session_id: string
  suggested_mapping: Record<string, string>
  columns: string[]
}

// dry_run=true : suggestion d'auto-assignation, rien n'est écrit --
// voir api/main.py:apply_pipeline_mapping.
export function suggestPipelineMapping(orgId: string, sessionId: string) {
  return request<PipelineMappingSuggestion>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ dry_run: true }) },
  )
}

export type PipelineMappingResult = {
  session_id: string
  status: string
  mapping: Record<string, string>
  n_rows_updated: number
}

// Applique le mapping fourni (l'appelant doit envoyer le mapping
// COMPLET voulu, pas un patch -- même contrat que côté serveur) et fait
// passer la session au statut "mapped".
export function applyPipelineMapping(orgId: string, sessionId: string, mapping: Record<string, string>) {
  return request<PipelineMappingResult>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ mapping, dry_run: false }) },
  )
}

// ---------------------------------------------------------------
// Pipeline "Trieur de Data" -- étape 2 (filtrer/exporter les lignes en
// staging), voir api/main.py:list_pipeline_session_rows /
// export_pipeline_session_rows. Mêmes opérateurs de filtre (FILTER_OPERATORS
// ci-dessus) et même normalisation casse que côté /records -- une seule
// source de vérité, ne pas dupliquer une deuxième liste d'opérateurs.
// ---------------------------------------------------------------

export type PipelineRowsPage = {
  session_id: string
  row_count: number
  count: number
  rows: Record<string, unknown>[]
}

// _matches_filter (views/tab_database.py) met en minuscules la VALEUR du
// champ mais pas `needle` -- même normalisation côté appelant que
// toApiColFilters/toApiColFiltersExport ci-dessus, dupliquée ici pour que
// les deux fonctions pipeline restent autonomes.
function toApiColFiltersPipeline(filters: ColFilters): ColFilters {
  const out: ColFilters = {}
  for (const [col, f] of Object.entries(filters)) {
    out[col] = { op: f.op, value: f.value.toLowerCase() }
  }
  return out
}

export function listPipelineSessionRows(
  orgId: string,
  sessionId: string,
  opts: { search?: string; colFilters?: ColFilters } = {},
) {
  const params = new URLSearchParams()
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersPipeline(opts.colFilters)))
  }
  return request<PipelineRowsPage>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/rows?${params.toString()}`,
  )
}

// Même mécanique de téléchargement navigateur que exportRecords ci-dessus
// (pas de JSON en retour) -- voir api/main.py:export_pipeline_session_rows.
export async function exportPipelineSessionRows(
  orgId: string,
  sessionId: string,
  opts: { format: 'csv' | 'xlsx'; search?: string; colFilters?: ColFilters },
): Promise<void> {
  const headers = await authHeader()
  const params = new URLSearchParams()
  params.set('format', opts.format)
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersPipeline(opts.colFilters)))
  }

  const res = await fetch(
    `${API_URL}/orgs/${orgId}/pipeline/sessions/${sessionId}/export?${params.toString()}`,
    { headers },
  )
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // pas de corps JSON -- on garde le statusText
    }
    throw new ApiError(res.status, detail)
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const filename = match ? match[1] : `export_pipeline.${opts.format}`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
