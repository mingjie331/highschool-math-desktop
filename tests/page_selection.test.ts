import { test } from 'node:test'
import assert from 'node:assert/strict'
import { selectFirstPages, selectDocumentPages } from '../frontend/src/pageSelection.ts'
import type { AIAttachment } from '../frontend/src/agentTypes.ts'
const pages = Array.from({length:35},(_,i)=>({id:String(i+1),document_id:'pdf',page_number:i+1}) as AIAttachment)
test('35 pages select only the first twenty and can be replaced by the last fifteen',()=>{
  assert.deepEqual([...selectFirstPages(pages)],pages.slice(0,20).map(p=>p.id))
  assert.deepEqual([...selectFirstPages(pages.slice(20))],pages.slice(20).map(p=>p.id))
})
test('per PDF selection preserves other files and follows page numbers within remaining capacity',()=>{
  const selected=new Set(['other-a','other-b','35'])
  const result=selectDocumentPages([...pages].reverse(),selected,'pdf')
  assert.equal(result.size,20)
  assert.deepEqual([...result],['other-a','other-b',...pages.slice(0,18).map(p=>p.id)])
})
