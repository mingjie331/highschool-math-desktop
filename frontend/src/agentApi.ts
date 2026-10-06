import { jsonRequest } from './api'
import type { AIConfigStatus, AIConversation, AIImportItem, AIImportTask, AIRegion, AIAttachment, AIDocument, AIWorkbenchData, AITaskProgress } from './agentTypes'

const post = <T>(url: string, body: object = {}) => jsonRequest<T>(url, { method: 'POST', body: JSON.stringify(body) })
export const agentApi = {
  workbench: (filters: { task_id?: string; source?: string; review_stage?: string; offset?: number; limit?: number } = {}) => jsonRequest<AIWorkbenchData>('/api/agent/workbench?' + new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))),
  deleteCandidate:(item:AIImportItem,request_id:string)=>jsonRequest<{id:string;deleted:boolean}>(`/api/agent/items/${item.id}`,{method:'DELETE',body:JSON.stringify({revision:item.revision,draft_revision:item.draft_revision,request_id})}),
  materials: (id: string) => jsonRequest<AIAttachment[]>(`/api/agent/items/${id}/materials`),
  confirmReview: (item: AIImportItem, request_id: string) => post<AIImportItem>(`/api/agent/items/${item.id}/confirm-review`, { revision: item.revision, request_id }),
  returnReview: (item: { id: string; revision: number }) => post<AIImportItem>(`/api/agent/items/${item.id}/return-review`, { revision: item.revision }),
  publishBatch: (items: { id: string; revision: number }[], request_id: string) => post<{ items: { item_id: string; task_id: string; question_id: string }[] }>('/api/agent/publish', { request_id, items }),
  config: () => jsonRequest<AIConfigStatus>('/api/agent/config'),
  test: () => post<{ ok: boolean; message: string }>('/api/agent/config/test'),
  sessions: () => jsonRequest<AIConversation[]>('/api/agent/sessions'),
  createSession: () => post<AIConversation>('/api/agent/sessions'),
  session: (id: string) => jsonRequest<AIConversation>(`/api/agent/sessions/${id}?compact=true`),
  task: (id: string) => jsonRequest<AITaskProgress>(`/api/agent/imports/${id}?compact=true`),
  start: (session_id: string, attachment_ids: string[], instruction: string, source_title: string, request_id: string, input_regions?: AIRegion[], selection?: { question_numbers: string; target_document_id?: string; document_pairs?: { question_document_id: string; answer_document_id: string }[] }) =>
    post<AIImportTask>('/api/agent/imports', { session_id, attachment_ids, instruction, source_title, request_id, input_regions, ...selection }),
  chat: (id: string, text: string, request_id: string) => post<AIImportTask>(`/api/agent/imports/${id}/messages`, { text, request_id }),
  cancel: (id: string) => post<AIImportTask>(`/api/agent/imports/${id}/cancel`),
  retry: (id: string, item_ids?: string[], failure_ids?:string[]) => post<AIImportTask>(`/api/agent/imports/${id}/retry`, { item_ids,failure_ids }),
  reprocess: (id: string, item_ids: string[]) => post<AIImportTask>(`/api/agent/imports/${id}/reprocess`, { item_ids }),
  solve: (id: string, item_ids: string[]) => post<AIImportTask>(`/api/agent/imports/${id}/solve`, { item_ids }),
  item: (id: string) => jsonRequest<AIImportItem>(`/api/agent/items/${id}`),
  update: (item: AIImportItem, changes: object) => jsonRequest<AIImportItem>(`/api/agent/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ revision: item.revision, changes }) }),
  validate: (id: string) => post<AIImportItem>(`/api/agent/items/${id}/validate`),
  skip: (item: AIImportItem) => post<AIImportItem>(`/api/agent/items/${item.id}/skip`, { id: item.id, revision: item.revision }),
  figure: (item: AIImportItem, region: AIRegion, field: string, figure_id?: string) => post<AIImportItem>(`/api/agent/items/${item.id}/figure`, { revision: item.revision, region, field, figure_id }),
  restructure: (id: string, items: AIImportItem[], groups: AIRegion[][]) => post<AIImportTask>(`/api/agent/imports/${id}/restructure`, { items: items.map(item => ({ id: item.id, revision: item.revision })), groups }),
  publish: (id: string, items: AIImportItem[], request_id: string) => post<{ items: { item_id: string; question_id: string }[] }>(`/api/agent/imports/${id}/publish`, { request_id, items: items.map(item => ({ id: item.id, revision: item.revision })) }),
  upload: async (session: string, file: File): Promise<AIAttachment | AIDocument> => {
    const body = new FormData(); body.append('file', file)
    const response = await fetch(`/api/agent/sessions/${session}/attachments`, { method: 'POST', body })
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '文件上传失败')
    return data
  },
}
