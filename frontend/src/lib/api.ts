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
  last_import: { filename: string; created_at: string } | null
}

export function listOrgs() {
  return request<Organization[]>('/orgs')
}

export function getDashboard(orgId: string) {
  return request<Dashboard>(`/orgs/${orgId}/dashboard`)
}

export function listRecords(
  orgId: string,
  opts: { page?: number; pageSize?: number; search?: string } = {},
) {
  const params = new URLSearchParams()
  params.set('page', String(opts.page ?? 1))
  params.set('page_size', String(opts.pageSize ?? 50))
  if (opts.search) params.set('search', opts.search)
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

export function previewImport(orgId: string, file: File) {
  return importRequest<ImportPreview>(orgId, file, { dryRun: true })
}

export function confirmImport(
  orgId: string,
  file: File,
  opts: { ibanCol?: string | null; addUnknownColumns?: boolean },
) {
  return importRequest<ImportResult>(orgId, file, { ...opts, dryRun: false })
}
