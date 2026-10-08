import DialogFrame from './DialogFrame'
import { useEffect, useRef, useState } from 'react'
import { agentApi } from './agentApi'
import { api, ApiError } from './api'
import type { Catalog } from './types'
import type { AIWorkbenchData, AIImportItem, AIQueueItem } from './agentTypes'
import AIImportPanel from './AIImportPanel'
import AIReviewPane from './AIReviewPane'
import type { ReviewHandle } from './AIReviewPane'
import PdfViewer from './PdfViewer'

type Tab = 'tasks'|'review'|'publish'
export default function AIWorkbench({catalog,onClose,onSettings,onPublished,onOpenQuestion}:{catalog:Catalog;onClose:()=>void;onSettings:()=>void;onPublished:()=>Promise<void>;onOpenQuestion:(id:string)=>Promise<void>}){
  const [tab,setTab]=useState<Tab>('tasks');const [data,setData]=useState<AIWorkbenchData|null>(null)
  const [deleting,setDeleting]=useState<AIImportItem|null>(null);const deletionRequest=useRef<string>('')
  const [queueOpen,setQueueOpen]=useState(true);const [loadedQuery,setLoadedQuery]=useState('');const autoQuery=useRef('')
  const [queue,setQueue]=useState<AIQueueItem[]>([]);const [total,setTotal]=useState(0);const [page,setPage]=useState(0)
  const [taskFilter,setTaskFilter]=useState('');const [sourceFilter,setSourceFilter]=useState('');const [sourceInput,setSourceInput]=useState('')
  const [active,setActive]=useState<AIImportItem|null>(null);const [configured,setConfigured]=useState(false)
  const [busy,setBusy]=useState(false);const [notice,setNotice]=useState('');const [selected,setSelected]=useState<Set<string>>(new Set())
  const selectedRef=useRef(selected);selectedRef.current=selected
  const [published,setPublished]=useState<{item_id:string;question_id:string}[]>([])
  const [preview,setPreview]=useState<{id:string;url:string;view:'question'|'solution'}|null>(null)
  const editorRef=useRef<ReviewHandle|null>(null);const activeRef=useRef(active);activeRef.current=active
  const query=useRef({tab,taskFilter,sourceFilter,page});query.current={tab,taskFilter,sourceFilter,page}
  const publishRequest=useRef<{signature:string;id:string}|null>(null);const alive=useRef(true)
  const taskFlush=useRef<()=>Promise<void>>(async()=>{})
  const fetchSequence=useRef(0);const openSequence=useRef(0);const pendingNavigation=useRef<Promise<void>|null>(null)
  const refresh=async()=>{
    const snapshot={...query.current};const sequence=++fetchSequence.current
    const value=await agentApi.workbench({task_id:snapshot.taskFilter,source:snapshot.sourceFilter,review_stage:snapshot.tab==='tasks'?undefined:snapshot.tab,offset:snapshot.page*100,limit:100})
    if(!alive.current||sequence!==fetchSequence.current)return
    setData(value);setQueue(value.items);setTotal(value.total);setLoadedQuery(JSON.stringify([snapshot.tab,snapshot.taskFilter,snapshot.sourceFilter,snapshot.page]))
    // Recheck every selected ID, including selections from previous list pages.
    setSelected(previous=>{const visible=new Map(value.items.map(i=>[i.id,i]));return new Set([...previous].filter(id=>!visible.has(id)||visible.get(id)?.review_stage==='publish'))})
    if(selectedRef.current.size){
      const states=await Promise.all([...selectedRef.current].map(id=>agentApi.item(id)))
      const invalid=states.filter(i=>i.review_stage!=='publish')
      if(invalid.length&&alive.current){setSelected(previous=>new Set([...previous].filter(id=>!invalid.some(i=>i.id===id))));setNotice('所选题目内容已变化，已取消勾选并退回待核对。')}
    }
    const config=await agentApi.config();if(alive.current)setConfigured(config.configured)
    const current=activeRef.current
    if(current){
      const next=await agentApi.item(current.id)
      if(alive.current&&activeRef.current?.id===next.id){
        if(next.review_stage==='deleted'||!next.form.sources){setActive(null);setQueueOpen(true);setNotice(next.review_stage==='deleted'?'候选题及草稿已删除，原材料与其他题目保留。':'该草稿已关闭，请选择其他题。')}
        else setActive(next)
      }
    }
  }
  const refreshRef=useRef(refresh);refreshRef.current=refresh
  useEffect(()=>{alive.current=true;void agentApi.config().then(set=>{if(alive.current)setConfigured(set.configured)});return()=>{alive.current=false}},[])
  useEffect(()=>{void refreshRef.current().catch(e=>setNotice(e.message))},[tab,taskFilter,sourceFilter,page])
  useEffect(()=>{let inFlight=false;const timer=window.setInterval(()=>{if(inFlight)return;inFlight=true;void refreshRef.current().catch(e=>setNotice(e.message)).finally(()=>{inFlight=false})},2000);return()=>window.clearInterval(timer)},[])
  useEffect(()=>window.desktop?.onPrepareClose(async()=>{await taskFlush.current();await editorRef.current?.flush()}),[])
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview.url)},[preview])
  const navigate=(action:()=>void)=>{
    if(pendingNavigation.current)return pendingNavigation.current
    setBusy(true)
    pendingNavigation.current=(async()=>{try{await taskFlush.current();await editorRef.current?.flush();action()}catch(error){setNotice(error instanceof Error?error.message:'保存失败，继续保留当前输入')}finally{setBusy(false)}})().finally(()=>{pendingNavigation.current=null})
    return pendingNavigation.current
  }
  const switchTab=(next:Tab)=>navigate(()=>{setTab(next);setQueueOpen(true);autoQuery.current='';setSelected(new Set());setPage(0);if(next!=='review')setActive(null);setNotice('')})
  const jump=(next:'review'|'publish',taskId:string)=>navigate(()=>{setTab(next);setQueueOpen(true);autoQuery.current='';setTaskFilter(taskId);setPage(0);setSelected(new Set());setActive(null);setNotice('')})
  const openItem=(id:string)=>navigate(()=>{
    const sequence=++openSequence.current;setNotice('正在打开题目…')
    void agentApi.item(id).then(item=>{if(alive.current&&sequence===openSequence.current){setActive(item);setQueueOpen(false);setNotice('')}}).catch(e=>setNotice(e.message))
  })
  const operate=async(action:()=>Promise<void>)=>{setBusy(true);try{await editorRef.current?.flush();await action();await refreshRef.current()}catch(error){setNotice(error instanceof Error?error.message:'操作失败')}finally{setBusy(false)}}
  const previewItem=(id:string,view:'question'|'solution')=>operate(async()=>{
    const item=await agentApi.item(id);const blob=await api.preview(item.form,view);setPreview({id,url:URL.createObjectURL(blob),view})
  })
  const returnItems=(items:{id:string;revision:number}[])=>operate(async()=>{for(const item of items)await agentApi.returnReview(item);setSelected(new Set());setNotice(`已退回 ${items.length} 道题，请切换待核对继续。`)})
  const publish=()=>operate(async()=>{
    const items=await Promise.all([...selected].map(id=>agentApi.item(id)));const invalid=items.filter(i=>i.review_stage!=='publish')
    if(invalid.length){setSelected(current=>new Set([...current].filter(id=>!invalid.some(i=>i.id===id))));throw new Error('部分题目确认已失效，已退回待核对；其他选择保留。')}
    const selection=items.map(i=>({id:i.id,revision:i.revision}));const signature=JSON.stringify(selection)
    if(publishRequest.current?.signature!==signature)publishRequest.current={signature,id:crypto.randomUUID()}
    try {
      let result
      try {result=await agentApi.publishBatch(selection,publishRequest.current.id)}
      catch(error){if(error instanceof ApiError && error.status<500)throw error;result=await agentApi.publishBatch(selection,publishRequest.current.id)}
      setPublished(result.items);setSelected(new Set());publishRequest.current=null;await onPublished();setNotice(`已加入题库 ${result.items.length} 道题，核验状态仍为待核验。`)
    }
    catch(error){
      if(error instanceof ApiError){const ids=error.detail?.item_ids as string[]|undefined;if(ids?.length){const affected=items.filter(i=>ids.includes(i.id));for(const item of affected){const latest=await agentApi.item(item.id);if(latest.review_stage==='publish')await agentApi.returnReview(latest)};setSelected(previous=>new Set([...previous].filter(id=>!ids.includes(id))));throw new Error(error.message+' · 受影响题目：'+affected.map(i=>i.details.original_number).join('、')+'；已退回核对，其他选择保留。')}}
      throw error
    }
  })
  const topic=(item:AIQueueItem)=>{const c=catalog.collections.find(c=>c.code===item.collection_code);const p=c?.topics.flatMap(t=>t.points).find(p=>p.code===item.point_code);return `${c?.title||item.collection_code} / ${p?.title||item.point_code}`}
  const askDelete=async(id:string)=>{
    try {await editorRef.current?.flush();const current=await agentApi.item(id);deletionRequest.current=crypto.randomUUID();setDeleting(current)}
    catch(e){setNotice(e instanceof Error?e.message:'保存失败，内容保留')}
  }
  const deleteCurrent=()=>operate(async()=>{
    if(!deleting)return
    try{await agentApi.deleteCandidate(deleting,deletionRequest.current)}
    catch(error){if(error instanceof ApiError&&error.status<500)throw error;await agentApi.deleteCandidate(deleting,deletionRequest.current)}
    setSelected(previous=>new Set([...previous].filter(id=>id!==deleting.id)));setActive(null);setDeleting(null);setQueueOpen(true);setNotice('候选题及草稿已删除，原材料与其他题目保留。')
  })
  const next=()=>{
    const index=queue.findIndex(i=>i.id===active?.id);const item=queue.slice(Math.max(0,index+1)).find(i=>i.review_stage==='review')||queue.find(i=>i.id!==active?.id&&i.review_stage==='review')
    if(item)void openItem(item.id);else setNotice('当前筛选范围内已没有下一题，可以查看待入库。')
  }
  useEffect(()=>{
    const key=JSON.stringify([tab,taskFilter,sourceFilter,page])
    if(tab!=='review'||loadedQuery!==key||autoQuery.current===key)return
    autoQuery.current=key
    if(total===1&&queue[0]&&!activeRef.current)void openItem(queue[0].id)
    else if(!activeRef.current)setQueueOpen(true)
  },[loadedQuery,tab,taskFilter,sourceFilter,page,total])
  const filterControls=<div className="ai-queue-filters" aria-label="题目筛选"><label>任务批次<select title={data?.tasks.find(t=>t.id===taskFilter)?.filenames.join('；')||'全部任务'} aria-label="任务批次" value={taskFilter} disabled={busy} onChange={e=>{const id=e.target.value;void navigate(()=>{setTaskFilter(id);setPage(0);setActive(null);setSelected(new Set())})}}><option value="">全部任务</option>{data?.tasks.map(t=><option key={t.id} value={t.id}>{t.filenames.join('；')||t.message} · {new Date(t.created_at).toLocaleString()}</option>)}</select>{taskFilter&&<small className="ai-filter-task-name">{data?.tasks.find(t=>t.id===taskFilter)?.filenames.join('；')}</small>}</label><label>题源筛选<input aria-label="题源筛选" value={sourceInput} onChange={e=>setSourceInput(e.target.value)}/></label><button className="button ghost" disabled={busy} onClick={()=>navigate(()=>{setSourceFilter(sourceInput);setPage(0);setActive(null);setSelected(new Set())})}>筛选</button><button className="button ghost" disabled={busy} onClick={()=>navigate(()=>{setTaskFilter('');setSourceFilter('');setSourceInput('');setPage(0);setActive(null);setSelected(new Set())})}>重置筛选</button><span className="ai-filter-count">共 {total} 题</span>{total>100&&<div className="form-actions"><button disabled={busy||page===0} onClick={()=>navigate(()=>{setPage(p=>p-1);setActive(null)})}>上一页</button><span>{page+1}</span><button disabled={busy||(page+1)*100>=total} onClick={()=>navigate(()=>{setPage(p=>p+1);setActive(null)})}>下一页</button></div>}</div>
  return <div className="editor-backdrop ai-backdrop" role="dialog" aria-modal="true" aria-label="AI 录题"><section className="ai-panel ai-workbench">
    <header className="ai-header"><strong>AI 录题工作台</strong><nav className="ai-tabs" role="tablist" aria-label="录题流程">{(['tasks','review','publish'] as Tab[]).map((name,index)=><button key={name} role="tab" aria-selected={tab===name} className={tab===name?'active':''} disabled={busy} onClick={()=>switchTab(name)}>{['录题任务','待核对','待入库'][index]}{name!=='tasks'&&<span>{data?.counts[name]||0}</span>}</button>)}</nav><div className="form-actions"><button className="button ghost" onClick={onSettings}>DeepSeek 设置</button><button className="icon-button" disabled={busy} aria-label="关闭 AI 录题" onClick={()=>navigate(onClose)}>×</button></div></header>
    <div className="ai-workbench-content">
      {notice&&!(tab==='review'&&active)&&<div className="notice" role="status">{notice}</div>}
      <div hidden={tab!=='tasks'} className="ai-task-tab"><AIImportPanel catalog={catalog} onClose={()=>navigate(onClose)} onSettings={onSettings} onPublished={refresh} onJump={jump} tasks={data?.tasks||[]} onFlushReady={flush=>{taskFlush.current=flush}} onOpenQuestion={async id=>{await editorRef.current?.flush();await onOpenQuestion(id)}}/></div>
      {tab!=='tasks'&&<>{(tab!=='review'||!active)&&filterControls}
      {tab==='review'?<div className="ai-review-workspace"><aside className={`ai-review-browser ${active?'drawer':'list-page'}`} hidden={!!active&&!queueOpen} aria-label="待核对题目列表">{active&&<><header className="ai-drawer-heading"><b>题目与筛选</b><button className="ai-drawer-close" onClick={()=>setQueueOpen(false)}>收起题目与筛选</button></header>{filterControls}</>}<div className="ai-review-list">{queue.map(i=><article key={i.id} className="ai-queue-row"><button className={active?.id===i.id?'active':''} disabled={busy} onClick={()=>openItem(i.id)}><b className="ai-queue-number">第 {i.original_number||'待确认'} 题</b><p className="ai-queue-summary" title={i.summary}>{i.summary.slice(0,160)||'提取未完成'}</p><small className="ai-queue-source" title={(i.source_title||i.task_title)+' · '+(data?.tasks.find(t=>t.id===i.task_id)?.filenames.join('；')||i.task_title)}><span className="ai-queue-source-name">{i.source_title||i.task_title}</span><em>批次：{data?.tasks.find(t=>t.id===i.task_id)?.created_at?new Date(data.tasks.find(t=>t.id===i.task_id)!.created_at).toLocaleString():i.task_title}</em></small><span className="ai-queue-status">{i.issues.length?i.issues.map(issue=>({stem:'题干',figures:'配图',answer:'答案解析',classification:'分类题源',layout:'排版'}[issue.section])).filter((v,n,a)=>a.indexOf(v)===n).join(' · '):'待人工确认'}</span><span className="ai-queue-open">打开核对 →</span></button><button className="ai-queue-delete" disabled={busy} onClick={()=>void askDelete(i.id)}>删除候选题</button></article>)}{!queue.length&&<p>此范围暂无待核对题目，请调整筛选或返回录题任务。</p>}</div></aside>
        {active?<AIReviewPane key={active.id} ref={editorRef} item={active} catalog={catalog} peers={queue} configured={configured} onUpdated={next=>{setActive(next);setNotice('')}} workspaceNotice={notice} onLater={()=>{setActive(null);setQueueOpen(true)}} onNext={next} onPublish={()=>switchTab('publish')} onChanged={refresh} onDelete={item=>void askDelete(item.id)} onQueue={()=>void navigate(()=>setQueueOpen(v=>!v))} onOpenQuestion={async id=>{await editorRef.current?.flush();await onOpenQuestion(id)}}/>:null}</div>:
      <div className="ai-publish-panel">{!!published.length&&<div className="notice"><b>发布结果</b>{published.map((result,n)=><button key={result.question_id} className="button ghost" onClick={()=>onOpenQuestion(result.question_id)}>查看已入库题目 {n+1}</button>)}</div>}
        <div className="ai-publish-controls"><button className="button ghost" disabled={busy} onClick={()=>setSelected(new Set(queue.filter(i=>i.review_stage==='publish').map(i=>i.id)))}>选择当前筛选结果</button><button className="button ghost" disabled={busy||!selected.size} onClick={()=>operate(async()=>{const current=await Promise.all([...selected].map(id=>agentApi.item(id)));for(const item of current)await agentApi.returnReview(item);setSelected(new Set());setNotice('已退回核对，草稿保留。')})}>所选退回核对</button></div>
        <div className="ai-publish-scroll"><table className="ai-publish-table"><thead><tr><th>选择</th><th>原题号与摘要</th><th>集合与知识点</th><th>题源 / 任务</th><th>操作</th></tr></thead><tbody>{queue.map(i=><tr key={i.id}><td><input type="checkbox" aria-label={`待入库 ${i.original_number} ${i.id}`} checked={selected.has(i.id)} disabled={busy} onChange={()=>setSelected(current=>{const next=new Set(current);next.has(i.id)?next.delete(i.id):next.add(i.id);return next})}/></td><td><b>第 {i.original_number} 题</b><p>{i.summary.slice(0,90)}</p></td><td>{topic(i)}</td><td>{i.source_title}<small>{i.task_title}</small></td><td><button className="button ghost" disabled={busy} onClick={()=>previewItem(i.id,'question')}>预览</button><button className="button ghost" disabled={busy} onClick={()=>returnItems([i])}>退回核对</button></td></tr>)}</tbody></table>{!queue.length&&<p className="ai-review-empty">尚无已完成人工核对的题目；请先在待核对中确认。</p>}</div>
        <footer className="ai-publish-footer"><span>已选 {selected.size} 道题 · 入库后仍待核验</span><button className="button primary" disabled={busy||!selected.size} onClick={publish}>加入题库（{selected.size}）</button></footer>
      </div>}</>}
    </div>
    {deleting&&<div className="ai-subdialog" role="dialog" aria-modal="true" aria-label="删除候选题"><DialogFrame className="ai-edit-panel" title={`删除第 ${deleting.details.original_number||'未明确题号'} 题？`} closeLabel="关闭删除确认" closeDisabled={busy} onClose={()=>setDeleting(null)} footer={<div className="form-actions"><button className="button ghost" disabled={busy} onClick={()=>setDeleting(null)}>取消删除</button><button className="button danger" disabled={busy} onClick={deleteCurrent}>确认删除候选题</button></div>}><p>{deleting.form.question_tex.slice(0,180)}</p><p>删除该题候选内容和草稿；保留原图片／PDF、任务摘要、其他候选和正式题库。此操作不能恢复该草稿。</p>{notice&&<p role="alert">{notice}</p>}</DialogFrame></div>}
    {preview&&<div className="ai-subdialog" role="dialog" aria-label="待入库预览"><DialogFrame className="ai-pdf-panel" bodyClassName="pdf-dialog-body" title="待入库预览" closeLabel="关闭待入库预览" onClose={()=>setPreview(null)} headerActions={<select aria-label="待入库预览内容" value={preview.view} onChange={e=>previewItem(preview.id,e.target.value as 'question'|'solution')}><option value="question">题目</option><option value="solution">答案解析</option></select>}><PdfViewer src={preview.url} title="待入库题目"/></DialogFrame></div>}
  </section></div>
}
