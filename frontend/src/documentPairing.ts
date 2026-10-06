import type { AIDocument,AIAttachment } from './agentTypes'
export const isAnswer=(name:string)=>/(?:答案|解析)\.pdf$/i.test(name)&&!name.includes('试卷')
const key=(name:string)=>name.replace(/\.pdf$/i,'').replace(/[_\s+＋-]*(试卷|答案|解析)$/,'').trim()
export function documentPairing(documents:AIDocument[],pages:AIAttachment[],selected:Set<string>,overrides:Record<string,string>) {
  const selectedDocs=new Set(pages.filter(p=>selected.has(p.id)).map(p=>p.document_id))
  const values:Record<string,string>={},errors:string[]=[],pairs:{question_document_id:string;answer_document_id:string}[]=[]
  const used=new Set<string>()
  for(const doc of documents){
    if(isAnswer(doc.filename))continue
    const candidates=documents.filter(a=>a.id!==doc.id&&isAnswer(a.filename)&&key(a.filename)===key(doc.filename))
    const automatic=candidates.length===1?candidates[0].id:''
    const answer=overrides[doc.id]??automatic;values[doc.id]=answer
    if(!answer||!selectedDocs.has(doc.id))continue
    const name=documents.find(d=>d.id===answer)?.filename||'所配对答案'
    if(answer===doc.id)errors.push(doc.filename+' 不能与自身配对')
    else if(!selectedDocs.has(answer))errors.push(doc.filename+' 已配对 '+name+'，请选中答案页面或取消配对')
    else if(used.has(doc.id)||used.has(answer))errors.push(doc.filename+' / '+name+' 被重复配对')
    else {pairs.push({question_document_id:doc.id,answer_document_id:answer});used.add(doc.id);used.add(answer)}
  }
  return {values,errors,pairs}
}
