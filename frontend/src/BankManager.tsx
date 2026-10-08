import { useRef, useState } from 'react'
import DialogFrame from './DialogFrame'
import { api } from './api'
import type { Bank, Catalog } from './types'

export default function BankManager({ banks, catalog, onClose, onChanged }: {banks:Bank[];catalog:Catalog;onClose:()=>void;onChanged:(id?:string)=>Promise<void>}) {
  const transferRequest=useRef<{signature:string;id:string}|null>(null)
  const [name,setName]=useState('');const [editing,setEditing]=useState('');const [notice,setNotice]=useState('');const [busy,setBusy]=useState(false)
  const [target,setTarget]=useState(banks.find(b=>b.id!==catalog.bank_id)?.id||'');const [ids,setIds]=useState<Set<string>>(new Set());const [semester,setSemester]=useState('gaoyi-first')
  const questions=(catalog.collections.find(c=>c.code===semester)?.topics||[]).flatMap(t=>t.points.flatMap(p=>p.questions.map(q=>({...q,point:p.title}))))
  const operate=async(action:()=>Promise<void>)=>{setBusy(true);setNotice('');try{await action()}catch(e){setNotice(e instanceof Error?e.message:'操作失败')}finally{setBusy(false)}}
  return <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label="题库管理"><DialogFrame className="utility-panel bank-manager" title="题库管理" closeLabel="关闭题库管理" closeDisabled={busy} onClose={onClose}>
    {notice&&<p role="status">{notice}</p>}
    <div className="bank-list">{banks.map(b=><div key={b.id}><b>{b.name}</b><span>{b.count||0} 题</span><button disabled={busy} className="button ghost compact" onClick={()=>{setEditing(b.id);setName(b.name)}}>重命名</button>{!b.is_system&&<button disabled={busy} className="button ghost compact" onClick={()=>void operate(async()=>{await api.deleteBank(b.id);await onChanged(b.id===catalog.bank_id?'system':undefined);setNotice('空题库已删除')})}>删除空题库</button>}</div>)}</div>
    <label>{editing?'修改题库名称':'新建题库名称'}<input aria-label="题库名称" maxLength={80} value={name} onChange={e=>setName(e.target.value)} placeholder="例如：课内练习、课外补充" /></label>
    <div className="form-actions"><button className="button primary" disabled={busy||!name.trim()} onClick={()=>void operate(async()=>{if(editing){await api.renameBank(editing,name);await onChanged()}else{const bank=await api.createBank(name);await onChanged(bank.id)}setName('');setEditing('');setNotice('题库已保存')})}>{editing?'保存名称':'创建题库'}</button>{editing&&<button className="button ghost" onClick={()=>{setEditing('');setName('')}}>取消重命名</button>}</div>
    <hr/><h3>整理当前题库：{catalog.bank_name}</h3>
    <div className="field-row"><label>选择学期<select aria-label="整理学期" value={semester} onChange={e=>{setSemester(e.target.value);setIds(new Set())}}>{catalog.collections.map(c=><option key={c.code} value={c.code}>{c.title}</option>)}</select></label><label>目标题库<select aria-label="目标题库" value={target} onChange={e=>setTarget(e.target.value)}><option value="">选择目标题库</option>{banks.filter(b=>b.id!==catalog.bank_id).map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select></label></div>
    <div className="form-actions"><button className="button ghost compact" disabled={busy} onClick={()=>setIds(new Set(questions.map(q=>q.id)))}>选择当前学期全部题目</button><button className="button ghost compact" disabled={busy} onClick={()=>setIds(new Set())}>取消选择</button><span>已选 {ids.size} 题</span></div>
    <div className="bank-question-list">{questions.map(q=><label key={q.id}><input type="checkbox" checked={ids.has(q.id)} disabled={busy} onChange={()=>setIds(old=>{const next=new Set(old);next.has(q.id)?next.delete(q.id):next.add(q.id);return next})}/><span>{q.point} · 第 {q.local_number} 题 · {q.preview}</span></label>)}</div>
    <p>移动保留原题，复制后可独立修改；有编辑草稿的题目需先处理草稿。移动的题目将移出原组卷区。</p>
    <div className="form-actions">{(['move','copy'] as const).map(mode=><button key={mode} className="button primary" disabled={busy||!target||!ids.size} onClick={()=>void operate(async()=>{const selection=questions.filter(q=>ids.has(q.id)).map(q=>({id:q.id,revision:q.revision}));const signature=JSON.stringify([catalog.bank_id,target,mode,selection]);if(transferRequest.current?.signature!==signature)transferRequest.current={signature,id:crypto.randomUUID()};await api.transfer(target,mode,selection,transferRequest.current.id);setIds(new Set());await onChanged();setNotice(mode==='move'?'移动完成':'复制完成')})}>{mode==='move'?'移动到目标题库':'复制到目标题库'}</button>)}</div>
  </DialogFrame></div>
}
