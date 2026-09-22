// Client pour l'API REST FastAPI (api/main.py). Chaque appel porte le
// jeton Supabase courant en "Authorization: Bearer <token>" -- voir
// api/main.py:get_current_ctx pour le contrat côté serveur.

import { clearAccountCache } from './useAccount'
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
  // Même nettoyage que AuthContext.signOut() (revue Copilot, PR #30) --
  // ce chemin de déconnexion forcée appelle directement
  // supabase.auth.signOut() sans passer par AuthContext, donc sans lui
  // le cache compte (useAccount.ts) survivrait à une session
  // expirée/révoquée et fuiterait vers le compte suivant connecté dans
  // le même onglet.
  clearAccountCache()
  void supabase.auth.signOut()
}

// Message générique -- ce wrapper couvre TOUTES les requêtes de ce
// client (dashboard, listes, export, import...), pas seulement l'import
// de fichiers : un avertissement "ne quitte pas la page pendant
// l'import" serait faux/trompeur sur un simple GET. L'avertissement
// spécifique à l'import reste affiché dans Tab2ImportMapping.tsx
// pendant que l'upload est actif -- pas ici (revue Copilot, PR #28).
const NETWORK_ERROR_MESSAGE =
  "Connexion interrompue -- vérifie ta connexion et ne quitte pas cette page (ni un autre "
  + "onglet/appli) tant qu'une action est en cours, puis réessaie."

// `fetch` lui-même peut échouer sans jamais renvoyer de Response --
// connexion coupée en cours d'envoi (page mise en arrière-plan sur
// mobile : le navigateur suspend/tue la requête), page/appli quittée,
// ou coupure réseau. Sans ce wrapper, l'erreur brute du navigateur
// (souvent "Failed to fetch"/"Load failed", jamais une ApiError) tombe
// dans le `catch` générique de chaque écran et s'affiche comme
// "Erreur inconnue" -- aucune info exploitable pour l'utilisateur.
async function safeFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch {
    throw new ApiError(0, NETWORK_ERROR_MESSAGE)
  }
}

// Une connexion peut aussi être coupée APRÈS avoir reçu les en-têtes de
// la Response, pendant la lecture du corps (res.json()/res.blob()) --
// safeFetch ne voit rien de ça (la promesse de fetch() s'est déjà
// résolue). Sans ce wrapper, la même coupure produit encore une erreur
// brute hors ApiError sur cette 2e moitié de la requête (revue Copilot,
// PR #28).
async function safeReadJson<T>(res: Response): Promise<T> {
  // res.json() confond deux choses : la LECTURE du corps (peut échouer sur
  // coupure réseau) et son PARSING (peut échouer sur un JSON invalide --
  // proxy qui renvoie du HTML, réponse serveur malformée...). Les séparer
  // pour ne pas accuser à tort la connexion d'une réponse serveur
  // défaillante (revue Copilot, PR #28).
  let text: string
  try {
    text = await res.text()
  } catch {
    throw new ApiError(0, NETWORK_ERROR_MESSAGE)
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(res.status, "Réponse du serveur invalide.")
  }
}

async function safeReadBlob(res: Response): Promise<Blob> {
  try {
    return await res.blob()
  } catch {
    throw new ApiError(0, NETWORK_ERROR_MESSAGE)
  }
}

async function throwForErrorResponse(res: Response): Promise<never> {
  // Même distinction que safeReadJson : une coupure réseau PENDANT la
  // lecture du corps d'une réponse d'erreur (en-têtes 4xx/5xx déjà reçus,
  // puis connexion perdue) doit remonter NETWORK_ERROR_MESSAGE, pas un
  // simple repli silencieux sur statusText -- sinon l'utilisateur ne voit
  // jamais le message réseau explicite pour cette moitié des coupures
  // possibles (revue Copilot, PR #28).
  let detail = res.statusText
  let text: string | null = null
  try {
    text = await res.text()
  } catch {
    if (res.status === 401) {
      handleUnauthorized()
    }
    throw new ApiError(0, NETWORK_ERROR_MESSAGE)
  }
  try {
    const body = JSON.parse(text)
    detail = body.detail ?? detail
  } catch {
    // pas de corps JSON (ou corps vide) -- on garde le statusText
  }
  if (res.status === 401) {
    handleUnauthorized()
  }
  throw new ApiError(res.status, detail)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await authHeader()
  const res = await safeFetch(`${API_URL}${path}`, {
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
  return safeReadJson<T>(res)
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
  const res = await safeFetch(`${API_URL}/orgs/${orgId}/import`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  return safeReadJson<T>(res)
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

  const res = await safeFetch(`${API_URL}/orgs/${orgId}/records/export?${params.toString()}`, { headers })
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  const blob = await safeReadBlob(res)
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

// Question à choix cliquables posée sur un chantier -- remplace la
// fiche Artifact séparée du Cockpit (Raphaël, 2026-09-21) : elle vit
// dans la même base que le reste du Cockpit, une réponse donnée ici est
// visible telle quelle par n'importe quelle session Claude ensuite.
export type ChantierQuestion = {
  id: string
  chantier_id: string
  question: string
  options: string[]
  answer: string | null
  comment: string | null
  created_at: string
  answered_at: string | null
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

export function listChantierQuestions(orgId: string, chantierId: string) {
  return request<ChantierQuestion[]>(`/orgs/${orgId}/chantiers/${chantierId}/questions`)
}

export function answerChantierQuestion(
  orgId: string,
  chantierId: string,
  questionId: string,
  answer: string,
  comment: string | null,
) {
  return request<ChantierQuestion[]>(
    `/orgs/${orgId}/chantiers/${chantierId}/questions/${questionId}`,
    { method: 'PATCH', body: JSON.stringify({ answer, comment }) },
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
//
// Le mapping est PAR ONGLET (sheet_key -> {source: maître}) -- fidèle à
// views/tab2_import_mapping.py : chaque fichier peut avoir plusieurs
// onglets Excel (sheet_key = "{fichier} :: {onglet}", ou juste le nom
// du fichier/onglet pour un CSV/PDF/fichier unique), chacun avec son
// propre mapping. Ne jamais fusionner ça en un mapping global.
// ---------------------------------------------------------------

// Sentinelle "non assigné" -- même valeur exacte que
// trieur/matching.py:auto_assign_columns_fast et api/main.py, ne jamais
// diverger (le backend compare cette chaîne littéralement).
export const PIPELINE_UNASSIGNED = '(non assigne)'

export type PipelineSheetSummary = {
  sheet_key: string
  columns: string[]
  row_count: number
  n_duplicates: number
  preview_rows: Record<string, unknown>[]
}

export type PipelineSessionCreated = {
  session_id: string
  status: string
  row_count: number
  columns: string[]
  unknown_columns: string[]
  preview_rows: Record<string, unknown>[]
  sheets: PipelineSheetSummary[]
}

// Mapping par onglet : sheet_key -> {colonne source: colonne maître}.
export type PipelineMappingBySheet = Record<string, Record<string, string>>

// Requête multipart dédiée (fichier seul, pas d'autres champs) -- même
// raison que importRequest ci-dessus : rester autonome plutôt que de
// partager un helper générique qui devrait gérer deux formes de champs
// différentes.
async function uploadPipelineFiles<T>(orgId: string, files: File[]): Promise<T> {
  const headers = await authHeader()
  const form = new FormData()
  for (const file of files) form.append('files', file)
  const res = await safeFetch(`${API_URL}/orgs/${orgId}/pipeline/sessions`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  return safeReadJson<T>(res)
}

// Plusieurs fichiers fusionnés en UNE session -- restaure le
// st.file_uploader(accept_multiple_files=True) de l'onglet 2 d'origine
// (views/tab2_import_mapping.py), perdu dans le premier portage React
// (un seul fichier sélectionnable, régression signalée par l'utilisateur).
export function createPipelineSession(orgId: string, files: File[]) {
  return uploadPipelineFiles<PipelineSessionCreated>(orgId, files)
}

export type PipelineMappingSuggestion = {
  session_id: string
  suggested_mapping: PipelineMappingBySheet
}

// dry_run=true : suggestion d'auto-assignation PAR ONGLET, rien n'est
// écrit -- voir api/main.py:apply_pipeline_mapping. `sheetKeys` (tous les
// onglets de la session, cf. `sheets[].sheet_key` renvoyé par
// createPipelineSession) permet au serveur d'échantillonner CHAQUE onglet
// individuellement plutôt qu'un LIMIT global -- sans ça, un onglet à lui
// seul plus gros que la limite masquait tous les onglets suivants de la
// suggestion (revue Copilot, PR #27).
export function suggestPipelineMapping(orgId: string, sessionId: string, sheetKeys: string[]) {
  return request<PipelineMappingSuggestion>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ dry_run: true, sheet_keys: sheetKeys }) },
  )
}

// [IBAN] Colonnes IBAN détectées (nom ou contenu) et lignes au checksum
// invalide -- même vérification que views/tab2_import_mapping.py, mod 97 :
// rien n'est supprimé automatiquement, juste remonté pour vérification
// avant export. Voir api/main.py:apply_pipeline_mapping.
export type PipelineIbanWarning = { column: string; n_invalid: number; sample_row_ids: string[] }

export type PipelineMappingResult = {
  session_id: string
  status: string
  mapping: PipelineMappingBySheet
  n_rows_updated: number
  n_rows_excluded: number
  iban_columns_detected: string[]
  iban_warnings: PipelineIbanWarning[]
}

// Applique le mapping fourni (PAR ONGLET -- l'appelant doit envoyer le
// mapping COMPLET voulu pour chaque onglet qu'il inclut, pas un patch ;
// un onglet absent de `mapping` est exclu de la base fusionnée, même
// contrat que côté serveur) et fait passer la session au statut "mapped".
// `sheetKeys` (tous les onglets de la session) permet au serveur de
// traiter chaque onglet PAR PAGES depuis la base plutôt que de tout
// charger en mémoire -- indispensable pour les gros imports (voir
// suggestPipelineMapping, même contrat côté dry_run).
export function applyPipelineMapping(
  orgId: string, sessionId: string, mapping: PipelineMappingBySheet, sheetKeys: string[],
) {
  return request<PipelineMappingResult>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/mapping`,
    { method: 'POST', body: JSON.stringify({ mapping, dry_run: false, sheet_keys: sheetKeys }) },
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
  page: number
  page_size: number
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

// [13] Filtre multi-critères de l'onglet 3 (trieur/filters.py:apply_filter_groups) :
// plusieurs GROUPES combinés en OU, chaque groupe pouvant contenir plusieurs
// CRITÈRES combinés en ET. Format EXACT attendu par l'API (groups=... en JSON) --
// voir api/main.py:list_pipeline_session_rows.
export type PipelineFilterCriterion = { column: string; kind: 'departements' | 'valeurs'; values: string[] }
export type PipelineFilterGroup = PipelineFilterCriterion[]

// Un groupe n'est "complet" que si TOUS ses critères ont une colonne et des
// valeurs -- même règle que trieur/filters.py:apply_filter_groups (un
// groupe en cours de saisie est ignoré, jamais envoyé tel quel à l'API).
export function completeFilterGroups(groups: PipelineFilterGroup[]): PipelineFilterGroup[] {
  return groups.filter((g) => g.length > 0 && g.every((c) => c.column && c.values.length > 0))
}

function groupsParam(groups: PipelineFilterGroup[] | undefined): string | null {
  const complete = completeFilterGroups(groups ?? [])
  return complete.length > 0 ? JSON.stringify(complete) : null
}

export function listPipelineSessionRows(
  orgId: string,
  sessionId: string,
  opts: {
    page?: number
    pageSize?: number
    search?: string
    colFilters?: ColFilters
    groups?: PipelineFilterGroup[]
  } = {},
) {
  const params = new URLSearchParams()
  params.set('page', String(opts.page ?? 1))
  params.set('page_size', String(opts.pageSize ?? 50))
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersPipeline(opts.colFilters)))
  }
  const g = groupsParam(opts.groups)
  if (g) params.set('groups', g)
  return request<PipelineRowsPage>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/rows?${params.toString()}`,
  )
}

// Même mécanique de téléchargement navigateur que exportRecords ci-dessus
// (pas de JSON en retour) -- voir api/main.py:export_pipeline_session_rows.
// `filenameBase` : nom de fichier choisi par l'utilisateur (onglet 4,
// équivalent de raw_name/export_name_base côté Streamlit) -- l'API elle-même
// nomme toujours le fichier d'après le fichier source (pas de paramètre
// serveur pour ça, volontairement non modifié ici), donc le renommage se
// fait uniquement côté navigateur sur l'attribut de téléchargement.
export async function exportPipelineSessionRows(
  orgId: string,
  sessionId: string,
  opts: {
    format: 'csv' | 'xlsx'
    search?: string
    colFilters?: ColFilters
    groups?: PipelineFilterGroup[]
    columns?: string[]
    filenameBase?: string
  },
): Promise<void> {
  const headers = await authHeader()
  const params = new URLSearchParams()
  params.set('format', opts.format)
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersPipeline(opts.colFilters)))
  }
  const g = groupsParam(opts.groups)
  if (g) params.set('groups', g)
  // Ordre + sélection des colonnes (équivalent glisser-déposer de l'onglet
  // 4 Streamlit) -- voir api/main.py:export_pipeline_session_rows. Absent
  // = toutes les colonnes, ordre d'apparition (comportement précédent).
  if (opts.columns) params.set('columns', opts.columns.join(','))

  const res = await safeFetch(
    `${API_URL}/orgs/${orgId}/pipeline/sessions/${sessionId}/export?${params.toString()}`,
    { headers },
  )
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  const blob = await safeReadBlob(res)
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const serverFilename = match ? match[1] : `export_pipeline.${opts.format}`
  const filename = opts.filenameBase
    ? `${opts.filenameBase.trim().replace(/[\\/:*?"<>|]+/g, '_') || 'export'}.${opts.format}`
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
// Pipeline "Trieur de Data" -- étape 3 (analyse des doublons + suppression
// définitive), voir api/main.py:get_pipeline_duplicates / apply_pipeline_dedupe.
// Même moteur que trieur/filters.py:duplicate_groups/dedupe_dataframe(_manual),
// adapté aux lignes {id, data} du staging (api/pipeline_engine.py).
//
// Écart volontaire par rapport à Streamlit (views/tab3_filtrage_dedup.py) :
// là-bas, la suppression restait EN MÉMOIRE et annulable (bouton "↩️
// Annuler") tant que la base source n'était pas touchée. Ici, POST
// .../dedupe supprime réellement les lignes perdantes du staging Postgres
// -- pas d'annulation possible après coup. Le frontend doit donc afficher
// un avertissement explicite avant d'appeler cette route (voir
// Tab3FiltrageDedup.tsx).
// ---------------------------------------------------------------

export type PipelineDuplicateGroup = { value: string | null; row_ids: string[]; suggested_keep_id: string }

export type PipelineDuplicates = {
  session_id: string
  column: string
  group_count: number
  duplicate_row_count: number
  filtered_row_count: number
  group_threshold: number
  groups: PipelineDuplicateGroup[]
}

export function getPipelineDuplicates(
  orgId: string,
  sessionId: string,
  opts: { column: string; search?: string; colFilters?: ColFilters; groups?: PipelineFilterGroup[] },
) {
  const params = new URLSearchParams()
  params.set('column', opts.column)
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersPipeline(opts.colFilters)))
  }
  const g = groupsParam(opts.groups)
  if (g) params.set('groups', g)
  return request<PipelineDuplicates>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/duplicates?${params.toString()}`,
  )
}

export type PipelineDedupeResult = {
  session_id: string
  column: string
  mode: string
  n_removed: number
  row_count: number | null
}

export type PipelineDedupeBody = {
  column: string
  mode: 'rule' | 'manual'
  keep?: 'first' | 'complete'
  keepIds?: string[]
  search?: string
  colFilters?: ColFilters
  groups?: PipelineFilterGroup[]
}

export function applyPipelineDedupe(orgId: string, sessionId: string, body: PipelineDedupeBody) {
  const complete = completeFilterGroups(body.groups ?? [])
  return request<PipelineDedupeResult>(
    `/orgs/${orgId}/pipeline/sessions/${sessionId}/dedupe`,
    {
      method: 'POST',
      body: JSON.stringify({
        column: body.column,
        mode: body.mode,
        keep: body.keep ?? 'first',
        keep_ids: body.keepIds ?? [],
        search: body.search ?? '',
        col_filters: body.colFilters ? toApiColFiltersPipeline(body.colFilters) : {},
        groups: complete,
      }),
    },
  )
}

// ---------------------------------------------------------------
// Génération des mandats de prélèvement (environnement Prélèvement) --
// voir trieur/prelevement.py pour les règles métier. Réservé aux
// administrateurs, comme le Cockpit.
// ---------------------------------------------------------------

export type PrelevementRuleExplanation = { titre: string; detail: string }

export type PrelevementRules = {
  org_id: string
  ics: string | null
  nature: 'CORE' | 'B2B'
  delay_days: number
  frais_setup_eur: number
  // Un montant par produit connu (voir produits_connus) -- toujours
  // complet à l'affichage (pré-rempli par l'API avec frais_setup_eur
  // tant que rien n'a été personnalisé), remplacement en masse à
  // l'enregistrement, comme les colonnes maîtres.
  frais_par_produit: Record<string, number>
  // {code de périodicité normalisé -> explication affichée dans le
  // mandat}, même convention (toujours complet, remplacement en masse).
  periodicites: Record<string, string>
  // Liste fixe des produits gérés par le moteur -- informative, jamais
  // éditable depuis l'écran (voir PROJECT_LOG.md, 2026-09-22 : couplée
  // à la fusion spéciale MYJURIS+IMMO et au nom des colonnes de
  // l'export CRM).
  produits_connus: string[]
  explication: PrelevementRuleExplanation[]
}

export function getPrelevementRules(orgId: string) {
  return request<PrelevementRules>(`/orgs/${orgId}/prelevement/rules`)
}

export function savePrelevementRules(
  orgId: string,
  body: {
    ics: string | null
    nature: 'CORE' | 'B2B'
    delayDays: number
    fraisSetupEur: number
    fraisParProduit: Record<string, number>
    periodicites: Record<string, string>
  },
) {
  return request<PrelevementRules>(`/orgs/${orgId}/prelevement/rules`, {
    method: 'POST',
    body: JSON.stringify({
      ics: body.ics,
      nature: body.nature,
      delay_days: body.delayDays,
      frais_setup_eur: body.fraisSetupEur,
      frais_par_produit: body.fraisParProduit,
      periodicites: body.periodicites,
    }),
  })
}

// ---------------------------------------------------------------
// Demandes de modification des règles codées en dur (2026-09-22) --
// file d'attente écrite depuis l'écran, jamais appliquée
// automatiquement : Raphaël/son père décrivent le changement souhaité,
// une session Claude Code la traite ensuite (code + tests + PR) et
// met à jour `statut` ici même.
// ---------------------------------------------------------------

export const RULE_REQUEST_STATUTS = ['en_attente', 'en_cours', 'valide'] as const
export type RuleRequestStatut = (typeof RULE_REQUEST_STATUTS)[number]

// Question à choix cliquables posée par une session Claude Code sur une
// demande ambiguë (2026-09-22) -- même principe que ChantierQuestion
// côté Cockpit, rattachée ici à une demande de règle Prélèvement plutôt
// qu'à un chantier.
export type RuleRequestQuestion = {
  id: string
  request_id: string
  question: string
  options: string[]
  answer: string | null
  comment: string | null
  created_at: string
  answered_at: string | null
}

export type PrelevementRuleRequest = {
  id: string
  org_id: string
  titre: string
  demande: string
  statut: RuleRequestStatut
  created_at: string
  updated_at: string
  // Toujours présent (liste vide si aucune question posée) -- l'API
  // l'inclut directement dans la même réponse (embed PostgREST), pour
  // que l'écran affiche le statut ET une question en attente sans appel
  // séparé par demande.
  questions: RuleRequestQuestion[]
}

export function listPrelevementRuleRequests(orgId: string) {
  return request<PrelevementRuleRequest[]>(`/orgs/${orgId}/prelevement/rule-requests`)
}

export function answerPrelevementRuleRequestQuestion(
  orgId: string,
  requestId: string,
  questionId: string,
  answer: string,
  comment: string | null,
) {
  return request<RuleRequestQuestion>(
    `/orgs/${orgId}/prelevement/rule-requests/${requestId}/questions/${questionId}`,
    { method: 'PATCH', body: JSON.stringify({ answer, comment }) },
  )
}

export function createPrelevementRuleRequest(orgId: string, titre: string, demande: string) {
  return request<PrelevementRuleRequest>(`/orgs/${orgId}/prelevement/rule-requests`, {
    method: 'POST',
    body: JSON.stringify({ titre, demande }),
  })
}

export function updatePrelevementRuleRequest(
  orgId: string,
  requestId: string,
  patch: Partial<{ titre: string; demande: string; statut: RuleRequestStatut }>,
) {
  return request<PrelevementRuleRequest>(`/orgs/${orgId}/prelevement/rule-requests/${requestId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deletePrelevementRuleRequest(orgId: string, requestId: string) {
  return request<{ id: string; removed: boolean }>(
    `/orgs/${orgId}/prelevement/rule-requests/${requestId}`,
    { method: 'DELETE' },
  )
}

export type PrelevementMandatRow = Record<string, string | number | null>

export type PrelevementMissingPhone = { referenceClient: string; nom: string; motif: string }

// Structuré (pas des phrases à virgules empilées) pour que l'écran
// l'affiche en petit tableau/grille lisible -- demande du 2026-09-22
// ("moins mal aux yeux").
export type PrelevementSummary = {
  nFichiers: number
  nLignes: number
  nExclus: number
  exclusions: { raison: string; n: number }[]
  nMandats: number
  nFirst: number
  nRcur: number
  nFusions: number
  nSansTelephone: number
}

export type PrelevementGenerateResult = {
  ooffCount: number
  rcurCount: number
  exclusCount: number
  summary: PrelevementSummary
  mandats: PrelevementMandatRow[]
  // Mandats envoyés quand même sans numéro de téléphone (ni Téléphone ni
  // Mobile trouvés sur la ligne CRM) -- décision de Raphaël (2026-09-22) :
  // jamais bloquant, mais signalé immédiatement, sans devoir ouvrir le
  // fichier téléchargé pour le découvrir.
  telephonesManquants: PrelevementMissingPhone[]
  filename: string
  fileBase64: string
}

// Envoie le fichier CRM brut et renvoie un aperçu du résultat (lignes de
// l'onglet "Mandat" + résumé des étapes) SANS télécharger automatiquement
// -- demandé par Raphaël (2026-09-22) : avant, le classeur se
// téléchargeait directement, sans qu'on puisse voir le résultat avant de
// l'enregistrer. Le classeur complet (4 onglets) revient encodé en
// base64 ; downloadPrelevementFile ci-dessous le décode pour le
// téléchargement, déclenché explicitement par un bouton "Télécharger".
export async function generatePrelevementMandats(
  orgId: string,
  files: File[],
): Promise<PrelevementGenerateResult> {
  const headers = await authHeader()
  const form = new FormData()
  for (const file of files) form.append('files', file)
  const res = await safeFetch(`${API_URL}/orgs/${orgId}/prelevement/generate`, {
    method: 'POST',
    headers,
    body: form,
  })
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  const data = (await res.json()) as {
    counts: { ooff: number; rcur: number; exclus: number; sans_telephone: number }
    summary: {
      n_fichiers: number
      n_lignes: number
      n_exclus: number
      exclusions: { raison: string; n: number }[]
      n_mandats: number
      n_first: number
      n_rcur: number
      n_fusions: number
      n_sans_telephone: number
    }
    mandats: PrelevementMandatRow[]
    telephones_manquants: { reference_client: string; nom: string; motif: string }[]
    filename: string
    file_base64: string
  }
  return {
    ooffCount: data.counts.ooff,
    rcurCount: data.counts.rcur,
    exclusCount: data.counts.exclus,
    summary: {
      nFichiers: data.summary.n_fichiers,
      nLignes: data.summary.n_lignes,
      nExclus: data.summary.n_exclus,
      exclusions: data.summary.exclusions,
      nMandats: data.summary.n_mandats,
      nFirst: data.summary.n_first,
      nRcur: data.summary.n_rcur,
      nFusions: data.summary.n_fusions,
      nSansTelephone: data.summary.n_sans_telephone,
    },
    mandats: data.mandats,
    telephonesManquants: data.telephones_manquants.map((t) => ({
      referenceClient: t.reference_client,
      nom: t.nom,
      motif: t.motif,
    })),
    filename: data.filename,
    fileBase64: data.file_base64,
  }
}

// Enregistre en base le lot de mandats affiché dans l'aperçu -- demandé
// en anticipation de la future vue de consultation (chantier séparé).
export function savePrelevementMandats(orgId: string, mandats: PrelevementMandatRow[]) {
  return request<{ batch_id: string | null; n_saved: number }>(
    `/orgs/${orgId}/prelevement/mandats`,
    { method: 'POST', body: JSON.stringify({ mandats }) },
  )
}

// ---------------------------------------------------------------
// Vue de consultation des mandats déjà enregistrés (2026-09-22) -- même
// principe que listRecords/updateRecord/bulkDeleteRecords/bulkUpdateRecords/
// exportRecords ci-dessus, mais sur la table dédiée
// trieur_data.prelevement_mandats (colonnes fixes, pas de "colonnes
// maîtres" à gérer).
export type PrelevementMandatsPage = {
  page: number
  page_size: number
  total: number
  columns: string[]
  rows: RecordRow[]
}

export function listPrelevementMandats(
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
  return request<PrelevementMandatsPage>(`/orgs/${orgId}/prelevement/mandats?${params.toString()}`)
}

// Contrairement à updateRecord (qui remplace tout le jsonb), le PATCH
// mandat n'attend QUE les champs modifiés -- voir
// trieur/db.py:update_prelevement_mandat, qui fusionne plutôt que
// remplacer (pas de jsonb ici, des colonnes SQL fixes).
export function updatePrelevementMandat(orgId: string, mandatId: string, data: Record<string, unknown>) {
  return request<{ id: string; data: Record<string, unknown>; updated: boolean }>(
    `/orgs/${orgId}/prelevement/mandats/${mandatId}`,
    { method: 'PATCH', body: JSON.stringify({ data }) },
  )
}

export function bulkDeletePrelevementMandats(orgId: string, ids: string[]) {
  return request<{ n_deleted: number }>(`/orgs/${orgId}/prelevement/mandats`, {
    method: 'DELETE',
    body: JSON.stringify({ ids }),
  })
}

export function bulkUpdatePrelevementMandats(orgId: string, ids: string[], field: string, value: unknown) {
  return request<{ n_updated: number; n_requested: number }>(
    `/orgs/${orgId}/prelevement/mandats/bulk`,
    { method: 'PATCH', body: JSON.stringify({ ids, field, value }) },
  )
}

export async function exportPrelevementMandats(
  orgId: string,
  opts: { format: 'csv' | 'xlsx'; search?: string; colFilters?: ColFilters },
): Promise<void> {
  const headers = await authHeader()
  const params = new URLSearchParams()
  params.set('format', opts.format)
  if (opts.search) params.set('search', opts.search)
  if (opts.colFilters && Object.keys(opts.colFilters).length > 0) {
    params.set('col_filters', JSON.stringify(toApiColFiltersExport(opts.colFilters)))
  }
  const res = await safeFetch(
    `${API_URL}/orgs/${orgId}/prelevement/mandats/export?${params.toString()}`,
    { headers },
  )
  if (!res.ok) {
    return throwForErrorResponse(res)
  }
  const blob = await safeReadBlob(res)
  const disposition = res.headers.get('content-disposition') ?? ''
  const match = /filename="?([^"]+)"?/.exec(disposition)
  const filename = match ? match[1] : `mandats_prelevement.${opts.format}`

  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// Décode le classeur base64 renvoyé par generatePrelevementMandats et
// déclenche son téléchargement -- séparé de la génération pour que
// l'utilisateur puisse d'abord voir l'aperçu.
export function downloadPrelevementFile(result: PrelevementGenerateResult) {
  const bytes = Uint8Array.from(atob(result.fileBase64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = result.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
