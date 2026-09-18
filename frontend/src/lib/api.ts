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

// Traitement global du 401 -- voir api/main.py:get_current_ctx : un jeton
// révoqué (mot de passe changé ailleurs, compte désactivé) ou un compte
// sans profil associé renvoie 401 même après un refresh Supabase réussi.
// Sans ceci, chaque écran affichait juste le message d'erreur brut sans
// action de récupération -- l'utilisateur restait bloqué tant qu'il ne
// rechargeait pas/se déconnectait manuellement. On force ici la
// déconnexion : App.tsx repasse alors sur LoginScreen (via useAuth/session),
// et LoginScreen affiche un message clair grâce au flag sessionStorage.
function handleUnauthorized() {
  try {
    sessionStorage.setItem('td_session_expired', '1')
  } catch {
    // stockage indisponible (navigation privée...) -- la déconnexion reste
    // effective, seul le message explicatif sur l'écran de connexion sera absent.
  }
  void supabase.auth.signOut()
}

async function throwForErrorResponse(res: Response): Promise<never> {
  let detail = res.statusText
  try {
    const body = await res.json()
    detail = body.detail ?? detail
  } catch {
    // pas de corps JSON -- on garde le statusText
  }
  if (res.status === 401) {
    handleUnauthorized()
  }
  throw new ApiError(res.status, detail)
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
    return throwForErrorResponse(res)
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
  active_master_column_set_id?: string | null
  [key: string]: unknown
}

export function getMe() {
  return request<{ profile: Profile }>('/me')
}

// Jeux de colonnes maîtres personnels (liés au COMPTE, pas à un
// environnement) -- mirroir de views/tab1_colonnes_maitres.py
// (`_render_account_memory`). `active_master_column_set_id` (sur
// `Profile`, voir getMe ci-dessus) indique le dernier jeu appliqué, à
// charger automatiquement une fois par session -- voir api/main.py
// (/me/column-sets*) pour le contrat serveur.
export type UserColumnSet = {
  id: string
  user_id: string
  name: string
  columns: string[]
  [key: string]: unknown
}

export function listMyColumnSets() {
  return request<{ sets: UserColumnSet[] }>('/me/column-sets')
}

export function saveMyColumnSet(name: string, columns: string[]) {
  return request<UserColumnSet>('/me/column-sets', {
    method: 'POST',
    body: JSON.stringify({ name, columns }),
  })
}

export function applyMyColumnSet(setId: string) {
  return request<UserColumnSet>(`/me/column-sets/${setId}/apply`, { method: 'POST' })
}

export function deleteMyColumnSet(setId: string) {
  return request<{ id: string; deleted: boolean }>(`/me/column-sets/${setId}`, { method: 'DELETE' })
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
    return throwForErrorResponse(res)
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
    return throwForErrorResponse(res)
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

// Requête multipart dédiée -- import multi-fichiers + Google Sheets DANS
// LE MÊME BATCH (voir api/main.py:create_pipeline_session_endpoint,
// même flux que views/tab2_import_mapping.py
// `st.file_uploader(accept_multiple_files=True)` + champ URL). `files`
// répété autant de fois que nécessaire (FastAPI `list[UploadFile]`) --
// un seul champ "file" ne suffirait pas pour plusieurs fichiers.
async function uploadPipelineFiles<T>(
  orgId: string,
  files: File[],
  googleSheetUrl?: string,
): Promise<T> {
  const headers = await authHeader()
  const form = new FormData()
  for (const f of files) form.append('files', f)
  if (googleSheetUrl) form.set('google_sheet_url', googleSheetUrl)
  const res = await fetch(`${API_URL}/orgs/${orgId}/pipeline/sessions`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  return res.json() as Promise<T>
}

export function createPipelineSession(orgId: string, files: File[], googleSheetUrl?: string) {
  return uploadPipelineFiles<PipelineSessionCreated>(orgId, files, googleSheetUrl)
}

// Un fichier importé = un ou plusieurs ONGLETS (une feuille Excel/CSV/
// Google Sheets) ; chaque onglet est mappé et fusionné SÉPARÉMENT --
// copie conforme de views/tab2_import_mapping.py (jamais un mapping
// unique sur l'union de toutes les colonnes de tous les fichiers).
export type PipelineSheetSuggestion = {
  sheet_key: string
  columns: string[]
  row_count: number
  n_duplicates: number
  preview_rows: Record<string, unknown>[]
  suggested_mapping: Record<string, string>
  unknown_columns: string[]
  // true : une mémoire de mapping existe déjà pour cette FORME de
  // fichier (même empreinte de colonnes qu'un import déjà confirmé dans
  // cet environnement) -- la suggestion l'a déjà appliquée en priorité,
  // voir trieur/matching.py:auto_assign_with_memory.
  remembered_for_shape: boolean
}

export type PipelineMappingSuggestion = {
  session_id: string
  sheets: PipelineSheetSuggestion[]
}

// dry_run=true : suggestion d'auto-assignation PAR ONGLET (mémoire de
// mapping par forme de fichier PUIS détection générique), rien n'est
// écrit -- voir api/main.py:apply_pipeline_mapping.
export function suggestPipelineMapping(orgId: string, sessionId: string) {
  return request<PipelineMappingSuggestion>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ dry_run: true }) },
  )
}

export type PipelineMappingResult = {
  session_id: string
  status: string
  n_rows_updated: number
  used_master_columns: string[]
  iban_warnings: { column: string; n_invalid: number }[]
}

// Applique le mapping fourni PAR ONGLET ({sheet_key: {src_col:
// master_col}}, l'appelant doit envoyer le mapping COMPLET voulu pour
// chaque onglet qu'il fournit, pas un patch -- même contrat que côté
// serveur) et fait passer la session au statut "mapped". `excludedSheets`
// = onglets à ne pas fusionner (voir la case "à inclure" de
// views/tab2_import_mapping.py). Le mapping CONFIRMÉ de chaque onglet
// fusionné est mémorisé côté serveur pour sa propre forme de fichier.
export function applyPipelineMapping(
  orgId: string,
  sessionId: string,
  mapping: Record<string, Record<string, string>>,
  excludedSheets: string[] = [],
) {
  return request<PipelineMappingResult>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ mapping, excluded_sheets: excludedSheets, dry_run: false }) },
  )
}

// ---------------------------------------------------------------
// Dédoublonnage de session pipeline (étape 3, distinct des filtres par
// colonne) -- voir api/main.py:apply_pipeline_dedup/clear_pipeline_dedup,
// mirroir de views/tab3_filtrage_dedup.py.
// ---------------------------------------------------------------

// Groupe manuel (<= DEDUP_GROUP_THRESHOLD groupes, voir api/main.py) :
// chaque ligne du groupe + la présélection "la plus complète" -- permet
// la revue groupe par groupe de views/tab3_filtrage_dedup.py. Au-delà,
// seul le compte (n_rows) est renvoyé : l'écran retombe sur la règle
// globale (`keep`).
export type PipelineDedupManualGroup = {
  value: unknown
  default_keep_index: number
  rows: { index: number; data: Record<string, unknown> }[]
}
export type PipelineDedupSummaryGroup = { value: unknown; n_rows: number }

export type PipelineDedupPreview = {
  session_id: string
  column: string
  n_duplicate_groups: number
  n_duplicate_rows: number
  manual_review_available: boolean
  groups: PipelineDedupManualGroup[] | PipelineDedupSummaryGroup[]
}

export function previewPipelineDedup(
  orgId: string,
  sessionId: string,
  opts: { column: string; keep?: 'first' | 'complete'; filterGroups?: FilterGroup[] },
) {
  return request<PipelineDedupPreview>(`/orgs/${orgId}/pipeline/sessions/${sessionId}/dedup`, {
    method: 'POST',
    body: JSON.stringify({
      column: opts.column,
      keep: opts.keep ?? 'first',
      filter_groups: opts.filterGroups ?? [],
      dry_run: true,
    }),
  })
}

export type PipelineDedupResult = {
  session_id: string
  dedup_config: { column: string; keep: string } | { column: string; mode: 'manual'; keep_indices: number[] } | null
  n_before: number
  n_after: number
  n_removed: number
}

export function activatePipelineDedup(
  orgId: string,
  sessionId: string,
  opts: { column: string; keep?: 'first' | 'complete'; filterGroups?: FilterGroup[] },
) {
  return request<PipelineDedupResult>(`/orgs/${orgId}/pipeline/sessions/${sessionId}/dedup`, {
    method: 'POST',
    body: JSON.stringify({
      column: opts.column,
      keep: opts.keep ?? 'first',
      filter_groups: opts.filterGroups ?? [],
      dry_run: false,
    }),
  })
}

// Revue manuelle groupe par groupe -- `keepIndices` = un index CHOISI
// par groupe (voir trieur/filters.py:dedupe_dataframe_manual), dans le
// MÊME ORDRE que les groupes renvoyés par previewPipelineDedup.
export function activatePipelineDedupManual(
  orgId: string,
  sessionId: string,
  opts: { column: string; keepIndices: number[]; filterGroups?: FilterGroup[] },
) {
  return request<PipelineDedupResult>(`/orgs/${orgId}/pipeline/sessions/${sessionId}/dedup`, {
    method: 'POST',
    body: JSON.stringify({
      column: opts.column,
      mode: 'manual',
      keep_indices: opts.keepIndices,
      filter_groups: opts.filterGroups ?? [],
      dry_run: false,
    }),
  })
}

export function clearPipelineDedup(orgId: string, sessionId: string) {
  return request<{ session_id: string; dedup_config: null }>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/dedup`,
    { method: 'DELETE' },
  )
}

// ---------------------------------------------------------------
// Presets d'export nommés (ordre + sélection des colonnes, étape 4) --
// voir api/main.py section "Presets d'export", mirroir de
// views/tab4_export.py.
// ---------------------------------------------------------------

export type PipelineExportPreset = {
  id: string
  name: string
  included: string[]
  excluded: string[]
  [key: string]: unknown
}

export function listPipelineExportPresets(orgId: string) {
  return request<PipelineExportPreset[]>(`/orgs/${orgId}/pipeline/export-presets`)
}

export function savePipelineExportPreset(
  orgId: string,
  body: { name: string; included: string[]; excluded: string[] },
) {
  return request<PipelineExportPreset>(`/orgs/${orgId}/pipeline/export-presets`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function deletePipelineExportPreset(orgId: string, presetId: string) {
  return request<{ id: string; deleted: boolean }>(
    `/orgs/${orgId}/pipeline/export-presets/${presetId}`,
    { method: 'DELETE' },
  )
}

// Renomme SANS toucher au contenu (ordre/colonnes) -- bouton "Renommer"
// distinct de "Enregistrer" dans views/tab4_export.py.
export function renamePipelineExportPreset(orgId: string, presetId: string, name: string) {
  return request<PipelineExportPreset>(
    `/orgs/${orgId}/pipeline/export-presets/${presetId}/rename`,
    { method: 'POST', body: JSON.stringify({ name }) },
  )
}

// ---------------------------------------------------------------
// Filtres multi-critères (onglet "Filtrer", voir
// views/tab3_filtrage_dedup.py -- trieur/filters.py:apply_filter_groups).
// Un critère = {column, kind, values} ; un groupe = critères combinés
// en ET ; le filtre = groupes combinés en OU. C'est le SEUL mécanisme
// de filtre du Pipeline -- il n'y a jamais eu de recherche libre ni de
// filtre par colonne façon Google Sheets (ColFilters) dans l'original.
// ---------------------------------------------------------------

export type FilterCriterionKind = 'departements' | 'valeurs'
export type FilterCriterion = { column: string; kind: FilterCriterionKind; values: string[] }
export type FilterGroup = FilterCriterion[]

export type PipelineSavedFilter = {
  id: string
  name: string
  groups: FilterGroup[]
  [key: string]: unknown
}

export function listPipelineSavedFilters(orgId: string) {
  return request<PipelineSavedFilter[]>(`/orgs/${orgId}/pipeline/saved-filters`)
}

export function savePipelineSavedFilter(orgId: string, body: { name: string; groups: FilterGroup[] }) {
  return request<PipelineSavedFilter>(`/orgs/${orgId}/pipeline/saved-filters`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function renamePipelineSavedFilter(orgId: string, filterId: string, name: string) {
  return request<PipelineSavedFilter>(`/orgs/${orgId}/pipeline/saved-filters/${filterId}/rename`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function deletePipelineSavedFilter(orgId: string, filterId: string) {
  return request<{ id: string; deleted: boolean }>(
    `/orgs/${orgId}/pipeline/saved-filters/${filterId}`,
    { method: 'DELETE' },
  )
}

// Code texte copiable ("TRIEUR-FILTRES-v1:...") -- secours hors de
// l'environnement (note, message...) si les filtres enregistrés sont
// perdus -- voir trieur/persistence.py:encode_filters_code/decode_filters_code.
export function encodePipelineFiltersCode(orgId: string, filters: { name: string; groups: FilterGroup[] }[]) {
  return request<{ code: string }>(`/orgs/${orgId}/pipeline/saved-filters/encode`, {
    method: 'POST',
    body: JSON.stringify({ filters }),
  })
}

export function decodePipelineFiltersCode(orgId: string, code: string) {
  return request<{ filters: { name: string; groups: FilterGroup[] }[] }>(
    `/orgs/${orgId}/pipeline/saved-filters/decode`,
    { method: 'POST', body: JSON.stringify({ code }) },
  )
}

// Résumé lisible d'un filtre ("(CP dept 34) OU (CP dept 71 ET VILLE =
// Lyon)") -- même règle que trieur/filters.py:describe_filter_groups,
// reproduite ici (pure fonction d'affichage, aucune I/O) pour ne pas
// faire un aller-retour réseau juste pour un libellé.
export function describeFilterGroups(groups: FilterGroup[]): string {
  if (groups.length === 0) return '(vide)'
  const describeCriterion = (c: FilterCriterion) => {
    const vals = c.values.length > 0 ? c.values.join(', ') : '(vide)'
    return c.kind === 'departements' ? `${c.column} dept ${vals}` : `${c.column} = ${vals}`
  }
  const groupStrs = groups.map((g) => (g.length > 0 ? g.map(describeCriterion).join(' ET ') : '(vide)'))
  return groupStrs.length > 1 ? groupStrs.map((s) => `(${s})`).join(' OU ') : groupStrs[0]
}

// ---------------------------------------------------------------
// Pipeline "Trieur de Data" -- étape 2 (filtrer/exporter les lignes en
// staging), voir api/main.py:list_pipeline_session_rows /
// export_pipeline_session_rows.
// ---------------------------------------------------------------

export type PipelineRowsPage = {
  session_id: string
  page: number
  page_size: number
  row_count: number
  count: number
  rows: Record<string, unknown>[]
}

// Valeurs distinctes de `column` sur TOUTE la session (pas juste la
// page affichée) -- peuple le multiselect d'un critère de filtre, voir
// api/main.py:get_pipeline_column_unique_values /
// views/tab3_filtrage_dedup.py:_render_value_picker. `values: null` =
// trop de valeurs distinctes (> 1000) : l'écran doit basculer sur un
// champ texte libre.
export function getPipelineColumnUniqueValues(orgId: string, sessionId: string, column: string) {
  return request<{ count: number; values: string[] | null }>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/columns/${encodeURIComponent(column)}/unique-values`,
  )
}

// Même règle que trieur/export.py:sanitize_filename côté serveur --
// dupliquée ici car ce renommage reste purement client (voir
// exportPipelineSessionRows) : retire les caractères interdits sur
// disque et une extension .csv/.xlsx tapée par erreur (déjà ajoutée par
// l'appelant).
function sanitizeFilenameClient(name: string): string {
  const withoutExt = name.trim().replace(/\.(csv|xlsx)$/i, '')
  const cleaned = withoutExt.replace(/[\\/:*?"<>|]/g, '_').trim()
  return cleaned || 'export_pipeline'
}

export function listPipelineSessionRows(
  orgId: string,
  sessionId: string,
  opts: { page?: number; pageSize?: number; filterGroups?: FilterGroup[] } = {},
) {
  const params = new URLSearchParams()
  params.set('page', String(opts.page ?? 1))
  params.set('page_size', String(opts.pageSize ?? 50))
  if (opts.filterGroups && opts.filterGroups.length > 0) {
    params.set('filter_groups', JSON.stringify(opts.filterGroups))
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
  opts: {
    format: 'csv' | 'xlsx'
    filterGroups?: FilterGroup[]
    columns?: string[]
    // Nom de fichier voulu par l'utilisateur (voir views/tab4_export.py:
    // champ texte pré-rempli, sanitize_filename) -- le backend ne connaît
    // que le nom de la session (source_filename), donc ce renommage reste
    // uniquement côté client (l'attribut `download` de l'ancre), sans
    // toucher au Content-Disposition renvoyé par l'API.
    filename?: string
  },
): Promise<void> {
  const headers = await authHeader()
  const params = new URLSearchParams()
  params.set('format', opts.format)
  if (opts.filterGroups && opts.filterGroups.length > 0) {
    params.set('filter_groups', JSON.stringify(opts.filterGroups))
  }
  // Ordre + sélection des colonnes (équivalent glisser-déposer de l'onglet
  // 4 Streamlit) -- voir api/main.py:export_pipeline_session_rows. Absent
  // = toutes les colonnes, ordre d'apparition (comportement précédent).
  if (opts.columns) params.set('columns', opts.columns.join(','))

  const res = await fetch(
    `${API_URL}/orgs/${orgId}/pipeline/sessions/${sessionId}/export?${params.toString()}`,
    { headers },
  )
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const serverFilename = match ? match[1] : `export_pipeline.${opts.format}`
  // Un nom choisi côté écran remplace le nom serveur, mais garde
  // l'extension réelle renvoyée -- jamais un double ".csv.xlsx".
  const filename = opts.filename
    ? `${sanitizeFilenameClient(opts.filename)}.${opts.format}`
    : serverFilename

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------
// "💾 Enregistrer dans la base de données (CRM)" -- copie conforme de
// views/tab4_export.py:_render_save_to_database. Enregistre le résultat
// FILTRÉ de la session (pas juste les colonnes de l'export) dans un
// environnement de destination, avec la même vérification de doublon
// IBAN que l'import direct de la Base de données.
// ---------------------------------------------------------------

export type PipelineSaveToDatabasePreview = { row_count: number; unknown_columns: string[] }
export type PipelineSaveToDatabaseResult = {
  n_imported: number
  n_alerts: number
  unknown_columns: string[]
  added_to_master_columns: string[]
}

export function previewSavePipelineSessionToDatabase(
  orgId: string,
  sessionId: string,
  opts: { targetOrgId: string; filterGroups?: FilterGroup[] },
) {
  return request<PipelineSaveToDatabasePreview>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/save-to-database`,
    {
      method: 'POST',
      body: JSON.stringify({
        target_org_id: opts.targetOrgId,
        filter_groups: opts.filterGroups ?? [],
        dry_run: true,
      }),
    },
  )
}

export function savePipelineSessionToDatabase(
  orgId: string,
  sessionId: string,
  opts: {
    targetOrgId: string
    filterGroups?: FilterGroup[]
    ibanCol?: string
    addUnknownColumns?: boolean
    importName?: string
  },
) {
  return request<PipelineSaveToDatabaseResult>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/save-to-database`,
    {
      method: 'POST',
      body: JSON.stringify({
        target_org_id: opts.targetOrgId,
        filter_groups: opts.filterGroups ?? [],
        iban_col: opts.ibanCol || null,
        add_unknown_columns: opts.addUnknownColumns ?? false,
        import_name: opts.importName || null,
        dry_run: false,
      }),
    },
  )
}
