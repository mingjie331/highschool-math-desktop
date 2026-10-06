import type { AIAttachment,AIDocument } from './agentTypes'
import {isAnswer} from './documentPairing.ts'
export type SourceChoice={mode:'auto'|'manual';manual:string}
export function sourceDefaults(pages:AIAttachment[],documents:AIDocument[],selected:Set<string>,target:string,pairs:{question_document_id:string;answer_document_id:string}[]) {
  const answerIds=new Set(pairs.map(p=>p.answer_document_id))
  const group=(id:string)=>pairs.find(p=>p.answer_document_id===id)?.question_document_id||id
  const names=pages.filter(p=>selected.has(p.id)&&(!target||!!p.document_id&&group(p.document_id)===group(target)))
    .filter(p=>!p.document_id||!answerIds.has(p.document_id)&&!isAnswer(documents.find(d=>d.id===p.document_id)?.filename||p.filename))
    .map(p=>(documents.find(d=>d.id===p.document_id)?.filename||p.filename).replace(/\.(png|jpe?g|pdf)$/i,''))
  return [...new Set(names)]
}
export function readSourceChoice(storage:Pick<Storage,'getItem'>,sid:string):SourceChoice {
  try {const value=JSON.parse(storage.getItem('ai-import-source:'+sid)||'{}');if((value.mode==='auto'||value.mode==='manual')&&typeof value.manual==='string')return value}catch{/* Private browsing or damaged local preferences. */}
  return {mode:'auto',manual:''}
}
export const submittedSource=(choice:SourceChoice)=>choice.mode==='manual'?choice.manual:''
