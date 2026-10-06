import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { agentApi } from './agentApi'
import { api, ApiError } from './api'
import type { Catalog, QuestionPayload, QuestionType } from './types'
import type { AIImportItem, AIReviewIssue, AIAttachment, AIRegion, AIQueueItem } from './agentTypes'
import AICropper from './AICropper'
import PdfViewer from './PdfViewer'
import AIPageCanvas from './AIPageCanvas'
import {sectionNames, reviewSections, sectionSignatures, currentIssues} from './reviewChecklist'
import type {ReviewSection} from './reviewChecklist'

export interface ReviewHandle { flush: () => Promise<AIImportItem> }
const makeValue = (item: AIImportItem) => ({ form: structuredClone(item.form), uncertainties: [...item.details.uncertainties],
  classification_uncertain: item.details.classification_uncertain, answer_conflict:item.details.answer_conflict,
  allow_duplicate:item.details.allow_duplicate, figures_confirmed:item.details.figures_confirmed ?? !item.details.figures.length,
  original_number:item.details.original_number, source_title:item.form.sources.origins?.map(o => o.title).join('；') || '',
  source_missing:!!item.form.sources.source_missing })
const userSignature=(value:ReturnType<typeof makeValue>)=>JSON.stringify({...value,form:Object.fromEntries(['type','question_tex','options','answer_tex','solution_tex','collection_code','point_code'].map(key=>[key,value.form[key as keyof QuestionPayload]]))})

const AIReviewPane = forwardRef<ReviewHandle, { item: AIImportItem; catalog:Catalog; peers:AIQueueItem[]; configured:boolean;
  onUpdated:(item:AIImportItem)=>void; onLater:()=>void; onNext:()=>void; onPublish:()=>void; onChanged:()=>Promise<void>; onQueue:()=>void; onDelete:(item:AIImportItem)=>void; onOpenQuestion:(id:string)=>Promise<void>; workspaceNotice?:string }>(function AIReviewPane({item,catalog,peers,configured,onUpdated,onLater,onNext,onPublish,onChanged,onQueue,onDelete,onOpenQuestion,workspaceNotice},ref) {
  const [value,setValue]=useState(()=>makeValue(item));const [remote,setRemote]=useState(item)
  const remoteRef=useRef(item);const latest=useRef(value);latest.current=value
  const saved=useRef(JSON.stringify(value));const pending=useRef<Promise<AIImportItem>|null>(null)
  const [notice,setNotice]=useState('修改后自动保存；完成核对时检查所有未解决项目。')
  const [busy,setBusy]=useState(false);const [materials,setMaterials]=useState<AIAttachment[]>([])
  const [pageId,setPageId]=useState('');const [activeSection,setActiveSection]=useState<ReviewSection>('stem')
  const [mobilePane,setMobilePane]=useState('original');const [enlarged,setEnlarged]=useState(false)
  const [leftPercent,setLeftPercent]=useState(50);const comparisonRef=useRef<HTMLDivElement>(null)
  const [focusedFigure,setFocusedFigure]=useState<string|null>(null)
  const [inlineCrop,setInlineCrop]=useState<{region:AIRegion;field:string;id?:string}|null>(null)
  const inlineRef=useRef(inlineCrop);inlineRef.current=inlineCrop
  const [seen,setSeen]=useState<Partial<Record<ReviewSection,string>>>(()=>{try{const v=JSON.parse(localStorage.getItem('ai-review-seen:'+item.id)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:{}}catch{return {}}})
  const detailSignatures=sectionSignatures(value.form,{...remote.details,...value},value.source_title,value.original_number,value.source_missing,!!remote.validation_current)
  const signaturesRef=useRef(detailSignatures);signaturesRef.current=detailSignatures

  const [crop,setCrop]=useState<{mode:'question'|'figure'|'split';figureId?:string;initial:AIRegion[];field?:string}|null>(null)
  const [merge,setMerge]=useState(false);const [mergeId,setMergeId]=useState('')
  const [preview,setPreview]=useState<{url:string;view:'question'|'solution'}|null>(null)
  const [previewView,setPreviewView]=useState<'question'|'solution'>('question')
  const [errorIssues,setErrorIssues]=useState<AIReviewIssue[]>([])
  const confirmRequest=useRef<{revision:number;id:string}|null>(null)
  const conflictOriginal=useRef({answer:item.form.answer_tex,solution:item.form.solution_tex})
  const sections=useRef<Partial<Record<keyof typeof sectionNames,HTMLElement>>>({})
  const readOnly=remote.review_stage==='publish'||remote.review_stage==='published'||remote.review_stage==='skipped'
  const stateLabel=remote.review_stage==='publish'?'已完成核对':remote.review_stage==='published'?'已入库':remote.review_stage==='skipped'?'已跳过':'待核对'
  const alive=useRef(true);const previewController=useRef<AbortController|null>(null);const previewSequence=useRef(0)
  const operation=useRef<Promise<void>|null>(null)
  const setCurrent=(next:AIImportItem)=>{remoteRef.current=next;setRemote(next);onUpdated(next)}
  const adopt=(next:AIImportItem)=>{const v=makeValue(next);latest.current=v;saved.current=JSON.stringify(v);setValue(v);setCurrent(next);setErrorIssues([]);conflictOriginal.current={answer:next.form.answer_tex,solution:next.form.solution_tex}}
  const focusSection=(section:ReviewSection,field?:string,mark=true)=>{
    setActiveSection(section);previewController.current?.abort();setPreview(null);setMobilePane('result');setEnlarged(false)
    if(mark)setSeen(previous=>{const next={...previous,[section]:signaturesRef.current[section]};try{localStorage.setItem('ai-review-seen:'+item.id,JSON.stringify(next))}catch{/* Viewing progress is optional; saving a draft remains independent. */}return next})
    const role=section==='answer'?'solution':'question'
    const region=remoteRef.current.details.regions.find(r=>(r.role || 'question')===role)|| (section==='answer'?remoteRef.current.details.regions.find(r=>r.role==='answer'):undefined)
    if(region)setPageId(region.image_id)
    window.setTimeout(()=>{const target=sections.current[section];const control=field?target?.querySelector<HTMLElement>(`[data-field="${field}"]`):target?.querySelector<HTMLElement>('textarea,input,select,button');if(target?.parentElement)target.parentElement.scrollTop=0;control?.scrollIntoView({block:'nearest'});(control||target)?.focus({preventScroll:true})},0)
  }
  const focusIssue=(issue:AIReviewIssue)=>{
    focusSection(issue.section,issue.target?.field||issue.field||undefined)
    const figure=remoteRef.current.details.figures.find(f=>f.id===issue.target?.figure_id)
    setFocusedFigure(figure?.id||null)
    if(figure)setPageId(figure.image_id)
    else if(issue.target?.image_id)setPageId(issue.target.image_id)
  }
  const flush=()=>{
    if(pending.current)return pending.current
    pending.current=(async()=>{
      while(JSON.stringify(latest.current)!==saved.current){
        const snapshot=structuredClone(latest.current),signature=JSON.stringify(snapshot),expected=remoteRef.current
        setNotice('正在保存…')
        let next:AIImportItem
        try { next=await agentApi.update(expected,snapshot) }
        catch(error){
          const actual=await agentApi.item(expected.id).catch(()=>null)
          // A response can be lost after an atomic save. Compare only user fields.
          const same=actual && actual.revision===expected.revision+1 && userSignature(makeValue(actual))===userSignature(snapshot)
          if(!same)throw error
          next=actual!
        }
        saved.current=signature;setCurrent(next);confirmRequest.current=null
        if(JSON.stringify(latest.current)===signature){const canonical=makeValue(next);latest.current=canonical;saved.current=JSON.stringify(canonical);setValue(canonical)}
      }
      setNotice('草稿已保存');return remoteRef.current
    })().catch(error=>{setNotice(error instanceof Error?error.message:'保存失败，输入仍保留');throw error}).finally(()=>{pending.current=null})
    return pending.current
  }
  const flushRef=useRef(flush);flushRef.current=flush
  useImperativeHandle(ref,()=>({flush:async()=>{await operation.current;if(inlineRef.current){setNotice('请先保存或取消当前裁剪，输入仍保留。');throw new Error('请先保存或取消当前裁剪，输入仍保留。')}return flushRef.current()}}),[])
  const signature=JSON.stringify(value)
  useEffect(()=>{if(signature===saved.current||readOnly)return;const timer=window.setTimeout(()=>void flushRef.current().catch(()=>{}),1000);return()=>window.clearTimeout(timer)},[signature,readOnly])
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;previewController.current?.abort()}},[])
  useEffect(()=>{void agentApi.materials(item.id).then(pages=>{if(!alive.current)return;setMaterials(pages);setPageId(item.details.regions[0]?.image_id||pages[0]?.id||'');window.setTimeout(()=>{const first=currentIssues(item.issues,makeValue(item),false)[0];if(first)focusIssue(first);else focusSection('stem',undefined,false)},50)}).catch(e=>setNotice(e.message))},[item.id])
  useEffect(()=>{
    if((item.revision>remoteRef.current.revision || (item.draft_revision||0)>(remoteRef.current.draft_revision||0) || item.revision===remoteRef.current.revision&&item.review_stage!==remoteRef.current.review_stage) && JSON.stringify(latest.current)===saved.current){
      const invalidated=remoteRef.current.review_stage==='publish'&&item.review_stage==='review'
      const resourcesOnly=item.draft_revision===remoteRef.current.draft_revision
      if(resourcesOnly)setCurrent(item)
      else adopt(item)
      if(invalidated){
        setNotice('内容或资源已变化，人工确认已失效，请重新核对。')
        if(resourcesOnly)setSeen(previous=>{const next={...previous};delete next.figures;delete next.layout;try{localStorage.setItem('ai-review-seen:'+item.id,JSON.stringify(next))}catch{}return next})
      }
    }
  },[item.revision,item.review_stage])
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview.url)},[preview])
  const edit=(patch:Partial<typeof value>)=>{setValue(v=>({...v,...patch}));setErrorIssues([]);previewController.current?.abort();setPreview(null)}
  const editForm=(patch:Partial<QuestionPayload>)=>edit({form:{...value.form,...patch}})
  const operate=(action:()=>Promise<void>)=>{
    if(operation.current)return operation.current
    setBusy(true)
    operation.current=(async()=>{try{await action();await onChanged()}catch(error){setNotice(error instanceof Error?error.message:'操作失败')}finally{setBusy(false)}})().finally(()=>{operation.current=null})
    return operation.current
  }
  const finish=()=>operate(async()=>{
    if(inlineRef.current)throw new Error('请先保存或取消裁剪。')
    const first=problemList.find(i=>i.section!=='layout');if(first){focusIssue(first);setNotice('请先处理：'+first.message);return}
    const current=await flushRef.current()
    if(confirmRequest.current?.revision!==current.revision)confirmRequest.current={revision:current.revision,id:crypto.randomUUID()}
    setNotice('正在检查字段与 PDF 排版…');setPreview(null)
    try {const approved=await agentApi.confirmReview(current,confirmRequest.current.id);adopt(approved);setNotice('核对完成，已移至待入库。');setPreview(null)}
    catch(error){
      if(error instanceof ApiError){const problems=error.detail?.issues as AIReviewIssue[]|undefined;if(problems?.length){setErrorIssues(problems);focusIssue(problems[0])}}
      const actual=await agentApi.item(current.id).catch(()=>null)
      if(actual?.review_stage==='publish'){
        try {const approved=await agentApi.confirmReview(current,confirmRequest.current!.id);adopt(approved);setNotice('核对完成，已移至待入库。');setPreview(null);return}catch{/* Keep the original failure if the approval no longer matches. */}
      }
      if(actual&&actual.draft_revision===current.draft_revision)setCurrent(actual)
      throw error
    }
  })
  const showPreview=(view:'question'|'solution')=>operate(async()=>{
    const current=await flushRef.current();previewController.current?.abort();const controller=new AbortController();previewController.current=controller;const sequence=++previewSequence.current
    const blob=await api.preview(current.form,view,{signal:controller.signal,sessionId:current.id,revision:current.revision})
    if(!alive.current||sequence!==previewSequence.current||controller.signal.aborted)return
    setPreview({url:URL.createObjectURL(blob),view});setPreviewView(view)
  })
  const openCrop=(mode:'question'|'figure'|'split',figureId?:string)=>operate(async()=>{
    const current=await flushRef.current();const figure=current.details.figures.find(f=>f.id===figureId)
    if(mode==='figure'){
      focusSection('figures');setMobilePane('original');setFocusedFigure(figure?.id||null)
      const region=figure||{image_id:pageId||materials[0]?.id,rect:[.2,.2,.8,.8] as AIRegion['rect']}
      if(!region.image_id)throw new Error('原材料尚未加载')
      setPageId(region.image_id);setInlineCrop({region:{image_id:region.image_id,rect:[...region.rect]},field:figure?.field||'question_tex',id:figure?.id})
    }else setCrop({mode,figureId,initial:current.details.regions})
  })
  const applyCrop=async(regions:AIRegion[],field:string)=>{
    const current=await flushRef.current()
    if(crop?.mode==='figure')adopt(await agentApi.figure(current,regions[0],field,crop.figureId))
    else if(crop?.mode==='question')adopt(await agentApi.update(current,{regions}))
    else {await agentApi.restructure(current.task_id,[current],regions.map(r=>[r]));adopt(await agentApi.item(current.id))}
    await onChanged()
  }
  const doRemote=(kind:'reprocess'|'solve')=>operate(async()=>{const current=await flushRef.current();await agentApi[kind](current.task_id,[current.id]);adopt(await agentApi.item(current.id));setNotice('已提交联网处理，请在录题任务查看进度。')})
  const currentPage=materials.find(p=>p.id===pageId)
  const dirty=JSON.stringify(value)!==saved.current
  const problemList=currentIssues(errorIssues.length?errorIssues:remote.issues,value,dirty)
  const figureBlocked=!!remote.details.figure_issues?.length||remote.details.figures.length<(remote.details.expected_figures||0)
  const selectedFigure=remote.details.figures.find(f=>f.id===focusedFigure)
  const focusRect=selectedFigure?.image_id===pageId?selectedFigure.rect:remote.details.regions.find(r=>r.image_id===pageId&&(r.role||'question')===(activeSection==='answer'?'solution':'question'))?.rect
  const activeProblems=problemList.filter(i=>i.section===activeSection)
  const cropPage=inlineCrop?materials.find(p=>p.id===inlineCrop.region.image_id):null
  const cropAspect=cropPage&&inlineCrop?(cropPage.width*(inlineCrop.region.rect[2]-inlineCrop.region.rect[0]))/(cropPage.height*(inlineCrop.region.rect[3]-inlineCrop.region.rect[1])):1
  const applyInline=()=>operate(async()=>{const c=inlineRef.current;if(!c)return;const current=await flushRef.current();adopt(await agentApi.figure(current,c.region,c.field,c.id));setInlineCrop(null);setNotice('裁剪已保存，请对照结果确认完整性。')})

  const collection=catalog.collections.find(c=>c.code===value.form.collection_code)
  const section=(key:keyof typeof sectionNames)=>(element:HTMLElement|null)=>{if(element)sections.current[key]=element}
  const conflictCandidate=remote.details.alternative_answer && remote.details.alternative_answer!=='请检查解析'?remote.details.alternative_answer:''
  return <section className="ai-review-pane">
    <header className="ai-review-title"><button className="button ghost" onClick={onQueue}>题目与筛选</button><div><h3>原题号 {remote.details.original_number || '待确认'} <small>{stateLabel}</small></h3><span role="status" title={workspaceNotice||notice}>{workspaceNotice||notice}</span></div><span className="ai-remaining">{readOnly?stateLabel:`${problemList.length} 项待处理`}</span><button className="button ghost" disabled={!problemList.length||!!inlineCrop} onClick={()=>focusIssue(problemList[0])}>处理下一项</button><button className="button danger" disabled={busy||!!inlineCrop||remote.review_stage==='published'||remote.review_stage==='deleted'} onClick={()=>onDelete(remoteRef.current)}>删除候选题</button><details className="ai-more"><summary>更多操作</summary><div>
      <button disabled={busy||readOnly} onClick={()=>openCrop('question')}>调整题目范围</button><button disabled={busy||readOnly} onClick={()=>openCrop('split')}>拆分此题</button>
      <button disabled={busy||readOnly} onClick={()=>operate(async()=>{await flushRef.current();setMerge(true)})}>合并同任务题目</button>
      <button disabled={busy||readOnly||!configured} onClick={()=>doRemote('reprocess')}>重新识别（联网调用）</button>
      <button disabled={busy||readOnly} onClick={()=>operate(async()=>{const current=await flushRef.current();adopt(await agentApi.skip(current));setNotice('已跳过，草稿保留。')})}>跳过此题</button>
    </div></details></header>
    <nav className="ai-checklist" aria-label="核对清单">{reviewSections.map(key=>{
      const count=problemList.filter(i=>i.section===key).length
      const status=readOnly?(remote.review_stage==='publish'?'整题已确认':stateLabel):count?`需处理 ${count} 项`:key==='layout'?(remote.validation_current&&!dirty?'检查通过 · 待确认':'需真实检查'):seen[key]===detailSignatures[key]?'已查看 · 待整题确认':'未发现问题 · 待人工对照'
      return <button key={key} disabled={!!inlineCrop} className={`${activeSection===key?'active':''} ${count?'has-problems':''}`} aria-pressed={activeSection===key} onClick={()=>{setFocusedFigure(null);focusSection(key)}}><b>{sectionNames[key]}</b><small>{status}</small></button>
    })}</nav>
    <div className="ai-mobile-switch"><button aria-pressed={mobilePane==='original'} onClick={()=>setMobilePane('original')}>原材料</button><button aria-pressed={mobilePane==='result'} onClick={()=>setMobilePane('result')}>当前项目{inlineCrop?' · 裁剪设置':''}</button></div>
    <div className={`ai-review-comparison ${enlarged?'enlarged':''}`} data-mobile={mobilePane} ref={comparisonRef} style={{gridTemplateColumns:`minmax(0,${leftPercent}fr) 8px minmax(0,${100-leftPercent}fr)`}}>
      <aside className="ai-review-original"><div className="ai-material-controls"><select aria-label="原材料页" disabled={!!inlineCrop} value={pageId} onChange={e=>setPageId(e.target.value)}>{materials.map(p=><option key={p.id} value={p.id}>{p.filename} · 第{p.page_number||1}页</option>)}</select></div>
        {currentPage&&<AIPageCanvas page={currentPage} focus={focusRect} fitInside={!!selectedFigure} boxes={[...remote.details.regions.map(r=>({image_id:r.image_id,rect:r.rect})),...remote.details.figures.map(r=>({image_id:r.image_id,rect:r.rect,figure:true,selected:r.id===focusedFigure}))].filter(r=>r.image_id===pageId)} crop={inlineCrop?.region.rect} onCrop={inlineCrop&&!busy?(rect)=>setInlineCrop(c=>c?{...c,region:{...c.region,rect}}:c):undefined} enlarged={enlarged} onEnlarge={()=>setEnlarged(v=>!v)}/>}
      </aside>
      <div className="ai-divider" role="separator" aria-label="调整对照宽度" aria-orientation="vertical" tabIndex={0} aria-valuemin={35} aria-valuemax={65} aria-valuenow={leftPercent} onKeyDown={e=>{if(e.key==='ArrowLeft')setLeftPercent(p=>Math.max(35,p-2));if(e.key==='ArrowRight')setLeftPercent(p=>Math.min(65,p+2))}} onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId)){const box=comparisonRef.current!.getBoundingClientRect();setLeftPercent(Math.max(35,Math.min(65,(e.clientX-box.left)/box.width*100)))}}}/>
      <div className="ai-review-result"><div className="ai-result-modes"><button className="button ghost" onClick={()=>{previewController.current?.abort();setPreview(null)}}>文字编辑</button><button className="button ghost" disabled={busy} onClick={()=>showPreview(previewView)}>PDF 预览</button>{preview&&<select aria-label="预览内容" value={preview.view} onChange={e=>showPreview(e.target.value as 'question'|'solution')}><option value="question">题目</option><option value="solution">答案解析</option></select>}</div>
      {inlineCrop?<div className="ai-inline-crop" aria-label="配图裁剪设置"><h4>调整{inlineCrop.field==='question_tex'?'题干':'解析'}图 {inlineCrop.id||'新配图'}</h4><p>拖动左侧裁剪框边界，或重新框选。缩放和平移不改变原页面坐标。</p>
        {cropPage&&<div className="ai-inline-crop-preview" style={{aspectRatio:cropAspect,width:`min(100%,360px,${220*cropAspect}px)`}}><img src={cropPage.url} alt="裁剪结果预览" style={{width:`${100/(inlineCrop.region.rect[2]-inlineCrop.region.rect[0])}%`,left:`${-inlineCrop.region.rect[0]*100/(inlineCrop.region.rect[2]-inlineCrop.region.rect[0])}%`,top:`${-inlineCrop.region.rect[1]*100/(inlineCrop.region.rect[3]-inlineCrop.region.rect[1])}%`}}/></div>}
        <div className="ai-coordinate-fields">{inlineCrop.region.rect.map((v,n)=><label key={n}>{['左','上','右','下'][n]}<input aria-label={`区域${['左','上','右','下'][n]}`} disabled={busy} type="number" min="0" max="1" step=".01" value={Number(v.toFixed(4))} onChange={e=>{const rect=[...inlineCrop.region.rect] as AIRegion['rect'];rect[n]=Math.max(0,Math.min(1,Number(e.target.value)));if(rect[2]>rect[0]&&rect[3]>rect[1])setInlineCrop(c=>c?{...c,region:{...c.region,rect}}:c)}}/></label>)}</div>
        <label>插入位置<select aria-label="配图插入位置" disabled={busy} value={inlineCrop.field} onChange={e=>setInlineCrop(c=>c?{...c,field:e.target.value}:c)}><option value="question_tex">题干</option><option value="answer_tex">答案</option><option value="solution_tex">解析</option></select></label><div className="form-actions"><button disabled={busy} onClick={()=>{setInlineCrop(null);onUpdated(remoteRef.current)}}>取消裁剪</button><button className="button primary" disabled={busy} onClick={applyInline}>保存裁剪</button></div></div>:preview?<PdfViewer src={preview.url} title="核对 PDF" />:<fieldset disabled={busy||readOnly}>
        {!!activeProblems.length&&<div className="ai-section-problems" aria-label="当前项目问题">{activeProblems.map((issue,n)=><article key={issue.code+n}><b>问题 {n+1}</b><p>{issue.message}</p><button className="button ghost" onClick={()=>issue.action==='crop_figure'?openCrop('figure',issue.target?.figure_id):issue.action==='add_figure'?openCrop('figure'):focusIssue(issue)}>{issue.action==='crop_figure'?'调整裁剪范围':issue.action==='add_figure'?'补充配图':'定位处理此项'}</button></article>)}</div>}
        {!problemList.length&&!readOnly&&<p className="ai-review-guidance">程序未发现问题，仍需人工对照后确认。</p>}
        <section hidden={activeSection!=='stem'} tabIndex={-1} ref={section('stem')}><h4>题干与选项</h4><label>题型<select aria-label="题型" value={value.form.type} onChange={e=>{const type=e.target.value as QuestionType;editForm({type,options:type==='single'||type==='multi'?Array.from({length:4},(_,n)=>value.form.options[n]||''):[]})}}><option value="single">单选</option><option value="multi">多选</option><option value="fill">填空</option><option value="long">解答</option></select></label><label>题干 LaTeX<textarea aria-label="题干 LaTeX" data-field="question_tex" rows={5} value={value.form.question_tex} onChange={e=>editForm({question_tex:e.target.value})}/></label>{(value.form.type==='single'||value.form.type==='multi')&&<div className="options-grid">{value.form.options.map((option,n)=><label key={n}>选项 {'ABCD'[n]}<textarea value={option} onChange={e=>editForm({options:value.form.options.map((v,i)=>i===n?e.target.value:v)})}/></label>)}</div>}
          {!!remote.details.duplicates.length&&<div className="ai-warning">发现重复或相似题。<button className="button ghost" onClick={()=>edit({allow_duplicate:true})}>已核对，仍新增</button><p>{value.allow_duplicate?'已明确允许新增重复题':remote.details.duplicates.map(d=>`${d.collection_code||'当前批次'}/${d.point_code||''} ${d.position||''}`).join('；')}</p>{remote.details.duplicates.filter(d=>!d.candidate).map(d=><button key={d.id} onClick={()=>void onOpenQuestion(d.id).catch(e=>setNotice(e.message))}>查看已有题目</button>)}</div>}</section>
        <section hidden={activeSection!=='figures'} tabIndex={-1} ref={section('figures')}><h4>配图</h4>{!remote.details.figures.length&&<p>未提取到配图；原题有图时请补图。</p>}<div className="ai-figure-grid">{remote.details.figures.map(f=><article key={f.id}><b>{f.field==='question_tex'?'题干图':'解析图'} {f.id}</b>{f.asset_path&&<img src={`/assets/${f.asset_path.replace(/^assets\//,'')}`} alt={`配图 ${f.id}`} />}<button className="button ghost" onClick={()=>openCrop('figure',f.id)}>调整此配图</button></article>)}</div>
          <button className="button ghost" onClick={()=>openCrop('figure')}>补充配图</button>{!!remote.details.figures.length&&<label className="check"><input type="checkbox" disabled={figureBlocked} checked={value.figures_confirmed&&!figureBlocked} onChange={e=>edit({figures_confirmed:e.target.checked})}/>已对照原材料，确认所有配图完整</label>}{figureBlocked&&<p className="ai-warning">请先补齐配图、调整标记图的裁剪范围，再确认完整性。</p>}</section>
        <section hidden={activeSection!=='answer'} tabIndex={-1} ref={section('answer')}><h4>答案解析</h4><small>答案来源：{remote.details.answer_origin} · 解析来源：{remote.details.solution_origin} · 入库后仍待数学核验</small><label>答案 LaTeX<textarea aria-label="答案 LaTeX" data-field="answer_tex" rows={2} value={value.form.answer_tex} onChange={e=>editForm({answer_tex:e.target.value})}/></label><label>解析 LaTeX<textarea aria-label="解析 LaTeX" data-field="solution_tex" rows={7} value={value.form.solution_tex} onChange={e=>editForm({solution_tex:e.target.value})}/></label>
          {value.answer_conflict&&<div className="ai-conflict"><b>答案存在冲突</b><p>当前答案：{value.form.answer_tex||'缺失'}</p><p>AI 候选：{conflictCandidate||'未提供可比较答案，请对照原材料与解析核对。'}</p><div><button className="button ghost" onClick={()=>edit({answer_conflict:false})}>保留原答案</button>{conflictCandidate&&<button className="button ghost" onClick={()=>edit({form:{...value.form,answer_tex:conflictCandidate},answer_conflict:false})}>采用 AI 候选</button>}<button className="button ghost" disabled={value.form.answer_tex===conflictOriginal.current.answer && value.form.solution_tex===conflictOriginal.current.solution} onClick={()=>edit({answer_conflict:false})}>已手动修正，解除冲突</button></div></div>}
          <details><summary>需要 AI 重新解题？</summary><p>会联网调用 DeepSeek，产生费用。保留原文，有不同结果时显示冲突。</p><button className="button ghost" disabled={!configured} onClick={()=>doRemote('solve')}>AI 重新解题核对</button></details></section>
        <section hidden={activeSection!=='classification'} tabIndex={-1} ref={section('classification')}><h4>分类与题源</h4><div className="field-row"><label>集合<select aria-label="集合" value={value.form.collection_code} onChange={e=>{const c=catalog.collections.find(c=>c.code===e.target.value)!;edit({form:{...value.form,collection_code:c.code,point_code:c.topics[0]?.points[0]?.code||''},classification_uncertain:false})}}>{catalog.collections.map(c=><option key={c.code} value={c.code}>{c.title}</option>)}</select></label><label>知识点<select aria-label="知识点" data-field="point_code" value={value.form.point_code} onChange={e=>edit({form:{...value.form,point_code:e.target.value},classification_uncertain:false})}>{collection?.topics.map(t=><optgroup key={t.code} label={t.title}>{t.points.map(p=><option key={p.code} value={p.code}>{p.title}</option>)}</optgroup>)}</select></label></div><p>{remote.details.classification_reason}</p>{value.classification_uncertain&&<button className="button ghost" onClick={()=>edit({classification_uncertain:false})}>确认当前分类</button>}
          <label>原题号<input aria-label="原题号" data-field="original_number" value={value.original_number} onChange={e=>edit({original_number:e.target.value})}/></label><label>题源<input aria-label="题源" data-field="source_title" disabled={value.source_missing} value={value.source_title} onChange={e=>edit({source_title:e.target.value})}/></label><label className="check"><input type="checkbox" checked={value.source_missing} onChange={e=>edit({source_missing:e.target.checked})}/>题源确实暂缺</label></section>
        {!!value.uncertainties.length&&<section hidden={!activeProblems.some(i=>i.code.startsWith('uncertainty:'))}><h4>需要核对的识别提示</h4>{value.uncertainties.map((message,n)=>activeProblems.some(i=>i.message===message)&&<div className="ai-review-note" key={n}><p>{message}</p><button className="button ghost" onClick={()=>edit({uncertainties:value.uncertainties.filter((_,i)=>i!==n)})}>已对照并修正此项</button></div>)}</section>}
        <section hidden={activeSection!=='layout'} tabIndex={-1} ref={section('layout')}><h4>排版检查</h4><p>{dirty?'内容已修改，需重新检查。':remote.details.validation_error||(remote.validation_current?'当前内容真实编译通过，仍需整题人工确认。':'当前内容需真实 PDF 编译检查。')}</p><button className="button ghost" onClick={()=>operate(async()=>{const current=await flushRef.current();adopt(await agentApi.validate(current.id));setNotice('排版检查已完成。')})}>检查排版</button></section>
      </fieldset>}</div>
    </div>
    <footer className="ai-review-footer">{readOnly?<><span>{remote.review_stage==='publish'?'已移至待入库，当前内容只读。':remote.review_stage==='published'?'已加入题库，仍待数学核验。':'已跳过此题，草稿保留；没有完成人工确认。'}</span><div className="form-actions"><button className="button ghost" onClick={onNext}>下一题</button>{remote.review_stage==='publish'&&<button className="button primary" onClick={onPublish}>查看待入库</button>}{remote.review_stage==='published'&&remote.question_id&&<button className="button primary" onClick={()=>void onOpenQuestion(remote.question_id!).catch(e=>setNotice(e.message))}>查看已入库题目</button>}{remote.review_stage==='skipped'&&<button className="button ghost" onClick={onLater}>回到题目列表</button>}{remote.review_stage==='publish'&&<button className="button ghost" disabled={busy} onClick={()=>operate(async()=>{adopt(await agentApi.returnReview(remoteRef.current));setNotice('已退回，可继续修改。')})}>退回修改</button>}</div></>:<><span>{problemList.length?`${problemList.length} 项待处理，完成按钮将定位首个问题`:'待人工整题确认 · 入库后仍待数学核验'}</span><div className="form-actions"><button className="button ghost" disabled={busy} onClick={()=>operate(async()=>{await flushRef.current();onLater()})}>保存，稍后继续</button><button className="button primary" disabled={busy||remote.review_stage==='processing'} onClick={finish}>核对完成，移至待入库</button></div></>}</footer>
    {crop&&<AICropper attachments={materials} initial={crop.initial} mode={crop.mode} initialField={crop.field} onApply={applyCrop} onClose={()=>setCrop(null)}/>}
    {merge&&<div className="ai-subdialog" role="dialog" aria-label="合并同任务题目"><section className="ai-edit-panel"><h3>选择合并的另一题</h3><p>会重新调用 AI 识别；原草稿保留为已跳过。</p><select aria-label="合并目标题" value={mergeId} onChange={e=>setMergeId(e.target.value)}><option value="">请选择</option>{peers.filter(p=>p.task_id===remote.task_id&&p.id!==remote.id&&p.review_stage==='review').map(p=><option key={p.id} value={p.id}>原题号 {p.original_number} · {p.summary.slice(0,40)}</option>)}</select><div className="form-actions"><button className="button ghost" onClick={()=>setMerge(false)}>取消</button><button className="button primary" disabled={busy||!mergeId||!configured} onClick={()=>operate(async()=>{const current=await flushRef.current();const other=await agentApi.item(mergeId);await agentApi.restructure(current.task_id,[current,other],[[...current.details.regions,...other.details.regions]]);adopt(await agentApi.item(current.id));setMerge(false)})}>合并并重新识别</button></div></section></div>}
  </section>
})
export default AIReviewPane
