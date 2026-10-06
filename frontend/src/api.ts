import type { Catalog, ExportStatus, Question, QuestionPayload, Draft, DraftContent, SearchResult, PoolState, PaperStatus } from './types'
import type { PositionContext } from './position'

export class ApiError extends Error {
  status: number
  code?: string
  detail?: Record<string, unknown>

  constructor(status: number, message: string, code?: string, detail?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

async function parseError(response: Response): Promise<never> {
  let message = `请求失败（${response.status}）`
  let code: string | undefined
  let details: Record<string, unknown> | undefined
  try {
    const body = await response.json()
    const detail = body.detail || body.message
    message = Array.isArray(detail) ? detail.map((item: { loc?: string[]; msg?: string }) => `${item.loc?.join('.') || ''}：${item.msg || '输入无效'}`).join('；') : typeof detail === 'object' && detail ? detail.message || message : detail || message
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) { code = detail.code; details = detail }
  } catch {
    // Keep the status-based message when a non-JSON error is returned.
  }
  throw new ApiError(response.status, message, code, details)
}

export async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!response.ok) return parseError(response)
  return response.json() as Promise<T>
}

export const api = {
  pool: () => jsonRequest<PoolState>('/api/pool'),
  addPool: (id: string) => jsonRequest<PoolState>(`/api/pool/${encodeURIComponent(id)}`, { method: 'PUT' }),
  removePool: (id: string) => jsonRequest<PoolState>(`/api/pool/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  removePoolBatch: (question_ids: string[]) => jsonRequest<PoolState>('/api/pool/remove', { method: 'POST', body: JSON.stringify({ question_ids }) }),
  undoPool: () => jsonRequest<PoolState>('/api/pool/undo', { method: 'POST' }),
  createPaper: (payload: { mode: 'manual'; question_ids: string[] } | { mode: 'random'; count: number }) =>
    jsonRequest<PaperStatus>('/api/papers', { method: 'POST', body: JSON.stringify(payload) }),
  paperStatus: () => jsonRequest<PaperStatus>('/api/papers/status'),
  search: (q: string, signal?: AbortSignal) => jsonRequest<{ items: SearchResult[]; total: number }>(`/api/search?q=${encodeURIComponent(q)}`, { signal }),
  drafts: () => jsonRequest<Draft[]>('/api/drafts'),
  draft: (id: string) => jsonRequest<Draft>(`/api/drafts/${id}`, { signal: AbortSignal.timeout(3000) }),
  saveDraft: (id: string, revision: number, source_question_id: string | null, base_revision: number | null, content: DraftContent, position: PositionContext) =>
    jsonRequest<Draft>(`/api/drafts/${id}`, { method: 'PUT', signal: AbortSignal.timeout(8000), body: JSON.stringify({ revision, source_question_id, base_revision, content, ...position }) }),
  discardDraft: (id: string, revision: number) => jsonRequest(`/api/drafts/${id}?revision=${revision}`, { method: 'DELETE' }),
  publishDraft: (id: string, revision: number, as_new: boolean) => jsonRequest<{ catalog_revision: number; question: Question }>(`/api/drafts/${id}/publish`, { method: 'POST', body: JSON.stringify({ revision, as_new }) }),
  catalog: () => jsonRequest<Catalog>('/api/catalog'),
  question: (id: string, signal?: AbortSignal) => jsonRequest<Question>(`/api/questions/${id}`, { signal }),
  create: (payload: QuestionPayload) =>
    jsonRequest<{ catalog_revision: number; question: Question }>('/api/questions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: QuestionPayload & { revision: number }) =>
    jsonRequest<{ catalog_revision: number; question: Question }>(`/api/questions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  remove: (id: string, revision: number) =>
    jsonRequest<{ catalog_revision: number; deleted_id: string }>(`/api/questions/${id}?revision=${revision}`, {
      method: 'DELETE',
    }),
  exportAll: (collection_code = 'gaoyi-first') => jsonRequest<ExportStatus>('/api/exports', { method: 'POST', body: JSON.stringify({ collection_code }) }),
  exportStatus: (collection_code = 'gaoyi-first', signal?: AbortSignal) => jsonRequest<ExportStatus>(`/api/exports/status?collection_code=${encodeURIComponent(collection_code)}`, { signal }),
  preview: async (payload: QuestionPayload, view: 'question' | 'solution' = 'question', options?: { signal: AbortSignal; sessionId: string; revision: number }) => {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: options?.signal,
      body: JSON.stringify({ ...payload, view, preview_session_id: options?.sessionId, preview_revision: options?.revision }),
    })
    if (!response.ok) return parseError(response)
    return response.blob()
  },
  upload: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    const response = await fetch('/api/assets', { method: 'POST', body })
    if (!response.ok) return parseError(response)
    return response.json() as Promise<{ latex_path: string; url: string; original_name: string }>
  },
}

