import type { AIAttachment } from './agentTypes'
export const RECOGNITION_PAGE_LIMIT = 20
export function selectFirstPages(pages: AIAttachment[]): Set<string> {
  return new Set(pages.slice(0, RECOGNITION_PAGE_LIMIT).map(page => page.id))
}
export function selectDocumentPages(pages: AIAttachment[], selected: Set<string>, documentId: string): Set<string> {
  const document = pages.filter(page => page.document_id === documentId).sort((a, b) => (a.page_number || 1) - (b.page_number || 1))
  const ids = new Set(document.map(page => page.id))
  const other = new Set([...selected].filter(id => !ids.has(id)))
  for (const page of document.slice(0, Math.max(0, RECOGNITION_PAGE_LIMIT - other.size))) other.add(page.id)
  return other
}
