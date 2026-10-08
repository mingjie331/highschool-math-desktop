import type { Catalog, ExportStatus, Question, QuestionPayload, Draft, DraftContent, SearchResult, PoolState, PaperStatus } from './types'
import type { Bank, ExportScope } from './types'
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

let bankId = 'system'
function scoped(url: string, bank = bankId) { return url + (url.includes('?') ? '&' : '?') + 'bank_id=' + encodeURIComponent(bank) }
export const api = {
  setBank: (id: string) => { bankId = id },
  banks: () => jsonRequest<Bank[]>('/api/banks'),
  createBank: (name: string) => jsonRequest<Bank>('/api/banks', { method:'POST', body:JSON.stringify({name}) }),
  renameBank: (id: string, name: string) => jsonRequest<Bank>(`/api/banks/${id}`, {method:'PATCH', body:JSON.stringify({name})}),
  deleteBank: (id: string) => jsonRequest(`/api/banks/${id}`, {method:'DELETE'}),
  transfer: (target_bank_id: string, mode: 'move' | 'copy', selection: {id:string;revision:number}[], request_id: string) => jsonRequest('/api/banks/transfer', {method:'POST',body:JSON.stringify({source_bank_id:bankId,target_bank_id,mode,selection,request_id})}),
  pool: () => jsonRequest<PoolState>(scoped('/api/pool')),
  addPool: (id: string) => jsonRequest<PoolState>(scoped(`/api/pool/${encodeURIComponent(id)}`), { method: 'PUT' }),
  removePool: (id: string) => jsonRequest<PoolState>(scoped(`/api/pool/${encodeURIComponent(id)}`), { method: 'DELETE' }),
  removePoolBatch: (question_ids: string[]) => jsonRequest<PoolState>('/api/pool/remove', { method: 'POST', body: JSON.stringify({ question_ids, bank_id:bankId }) }),
  undoPool: () => jsonRequest<PoolState>(scoped('/api/pool/undo'), { method: 'POST' }),
  createPaper: (payload: { mode: 'manual'; question_ids: string[] } | { mode: 'random'; count: number }) =>
    jsonRequest<PaperStatus>('/api/papers', { method: 'POST', body: JSON.stringify({...payload,bank_id:bankId}) }),
  paperStatus: () => jsonRequest<PaperStatus>(scoped('/api/papers/status')),
  search: (q: string, signal?: AbortSignal, allBanks=false) => jsonRequest<{ items: SearchResult[]; total: number }>(scoped(`/api/search?q=${encodeURIComponent(q)}&all_banks=${allBanks}`), { signal }),
  drafts: () => jsonRequest<Draft[]>(scoped('/api/drafts')),
  draft: (id: string) => jsonRequest<Draft>(`/api/drafts/${id}`, { signal: AbortSignal.timeout(3000) }),
  saveDraft: (id: string, revision: number, source_question_id: string | null, base_revision: number | null, content: DraftContent, position: PositionContext) =>
    jsonRequest<Draft>(`/api/drafts/${id}`, { method: 'PUT', signal: AbortSignal.timeout(8000), body: JSON.stringify({ revision, source_question_id, base_revision, content, ...position }) }),
  discardDraft: (id: string, revision: number) => jsonRequest(`/api/drafts/${id}?revision=${revision}`, { method: 'DELETE' }),
  publishDraft: (id: string, revision: number, as_new: boolean) => jsonRequest<{ catalog_revision: number; question: Question }>(`/api/drafts/${id}/publish`, { method: 'POST', body: JSON.stringify({ revision, as_new }) }),
  catalog: () => jsonRequest<Catalog>(scoped('/api/catalog')),
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
  exportAll: (collection_code = 'gaoyi-first', scope: ExportScope = {kind:'semester'}) => jsonRequest<ExportStatus>('/api/exports', { method: 'POST', body: JSON.stringify({ collection_code,bank_id:bankId,scope }) }),
  exportStatus: (collection_code = 'gaoyi-first', signal?: AbortSignal,scope: ExportScope = {kind:'semester'}) => jsonRequest<ExportStatus>(scoped(`/api/exports/status?collection_code=${encodeURIComponent(collection_code)}&scope=${encodeURIComponent(JSON.stringify(scope))}`), { signal }),
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

