import DialogFrame from './DialogFrame'
import { useEffect, useRef, useState } from 'react'
import { agentApi } from './agentApi'
import type { Catalog } from './types'
import type { AIConfigStatus, AIConversation, AIRegion, AIAttachment, AITaskSummary, AITaskProgress } from './agentTypes'
import AICropper from './AICropper'
import PdfViewer from './PdfViewer'
import {documentPairing,isAnswer} from './documentPairing'
import {sourceDefaults,readSourceChoice,submittedSource} from './importSource'
import type {SourceChoice} from './importSource'
import {selectFirstPages, selectDocumentPages} from './pageSelection'

const ACTIVE = new Set(['pending', 'recognizing', 'processing', 'chatting'])
const LABELS: Record<string, string> = { pending: '等待处理', recognizing: '提取原解析', solving: '补充答案解析', classifying: '判断分类', validating: '编译校验', ready: '可确认入库', needs_review: '待核对', failed: '处理失败', published: '已入库', skipped: '已跳过' }

export default function AIImportPanel({ catalog, onClose, onSettings, onPublished, onJump, tasks = [], onOpenQuestion, onFlushReady }: {
  catalog: Catalog; onClose: () => void; onSettings: () => void; onPublished: () => Promise<void>; onJump: (tab: "review" | "publish", taskId: string) => void; tasks?: AITaskSummary[]; onOpenQuestion: (id: string) => Promise<void>;
  onFlushReady: (flush: () => Promise<void>) => void;
}) {
  const [sessions, setSessions] = useState<AIConversation[]>([])
  const [session, setSession] = useState<AIConversation | null>(null)
  const [task, setTask] = useState<AITaskProgress | null>(null)
  const [config, setConfig] = useState<AIConfigStatus | null>(null)
  const [instruction, setInstruction] = useState('提取这些图片中的题目，补充缺失答案解析，并按知识点分类。')
  const [sourceChoice,setSourceChoice]=useState<SourceChoice>({mode:'auto',manual:''})
  const sourcePending=useRef<Promise<unknown>>(Promise.resolve())
  const changeSource=(choice:SourceChoice)=>{setSourceChoice(choice);const sid=sessionRef.current;if(sid)try{localStorage.setItem('ai-import-source:'+sid,JSON.stringify(choice))}catch{/* Browser fallback is optional. */}
    if(sid&&window.desktop){sourcePending.current=sourcePending.current.catch(()=>{}).then(()=>window.desktop!.saveImportSource(sid,choice));void sourcePending.current.catch(error=>setNotice('题源偏好尚未保存：'+error.message))}
  }
  const [questionNumbers, setQuestionNumbers] = useState('')
  const [targetDocument, setTargetDocument] = useState('')
  const [pairOverrides, setPairOverrides] = useState<Record<string, string>>({})
  const [text, setText] = useState('')
  const [selectedImages, setSelectedImages] = useState<Set<string>>(new Set())
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [sourceCropping, setSourceCropping] = useState<AIAttachment | null>(null)
  const [sourceRegions, setSourceRegions] = useState<Record<string, AIRegion[]>>({})
  const [originalDocument, setOriginalDocument] = useState<{ url: string; filename: string } | null>(null)
  const sessionRef = useRef<string | null>(null)
  const taskRef = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const uploadPending = useRef<Promise<void> | null>(null)
  const alive = useRef(true)
  const mainRef = useRef<HTMLElement>(null)
  const reviewRef = useRef<HTMLDivElement>(null)
  const pendingStart = useRef<{ signature: string; id: string } | null>(null)
  const pendingChat = useRef<{ text: string; id: string } | null>(null)
  const working = !!task && (ACTIVE.has(task.state) || task.worker_active)
  const scrollReview = () => { if (mainRef.current && reviewRef.current) mainRef.current.scrollTo({ top: reviewRef.current.offsetTop - mainRef.current.offsetTop, behavior: 'smooth' }) }

  const refresh = async () => {
    const sid = sessionRef.current; const tid = taskRef.current
    if (!sid) return
    const value = await agentApi.session(sid)
    if (!alive.current || sid !== sessionRef.current) return
    setSession(value)
    if (tid) {
      const current = await agentApi.task(tid)
      if (alive.current && tid === taskRef.current) {
        setTask(current)

      }
    }
    setConfig(await agentApi.config())
  }
  const switchSession = async (id: string) => {
    await sourcePending.current
    sessionRef.current = id; setSourceChoice(readSourceChoice(localStorage,id)); taskRef.current = null; setTask(null); setSelectedImages(new Set()); setPairOverrides({}); setTargetDocument(''); setQuestionNumbers(''); setSourceRegions({})
    const value = await agentApi.session(id)
    const stored=window.desktop?await window.desktop.getImportSource(id):null
    if (sessionRef.current !== id) return
    if(stored)setSourceChoice(stored)
    setSession(value)
    if (value.tasks[0]) { taskRef.current = value.tasks[0].id; setTask(await agentApi.task(value.tasks[0].id)) }
  }
  const newSession = async () => {
    const value = await agentApi.createSession(); setSessions(current => [value, ...current]); await switchSession(value.id)
  }
  useEffect(() => {
    alive.current = true
    void (async () => {
      setConfig(await agentApi.config())
      const values = await agentApi.sessions(); if (!alive.current) return; setSessions(values)
      if (values[0]) await switchSession(values[0].id); else await newSession()
    })().catch(error => setNotice(error.message))
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    let fetching = false
    const timer = window.setInterval(() => { if (fetching) return; fetching = true; void refresh().catch(error => setNotice(error.message)).finally(() => { fetching = false }) }, working ? 1000 : 3000)
    return () => window.clearInterval(timer)
  }, [working])
  useEffect(() => { onFlushReady(async () => { await uploadPending.current;await sourcePending.current }) }, [])
  const operate = async (action: () => Promise<unknown>) => {
    setBusy(true); setNotice('')
    try { await action(); await refresh(); await onPublished() }
    catch (error) { setNotice(error instanceof Error ? error.message : '操作失败'); await refresh().catch(() => {}) }
    finally { setBusy(false) }
  }
  const upload = (files: File[]) => {
    if (!files.length || uploadPending.current) return
    if (!sessionRef.current) { setNotice('正在建立录题会话，请稍后选择图片'); return }
    if (files.length > 20) { setNotice('每批最多 20 页，请拆批上传'); return }
    const sid = sessionRef.current
    setBusy(true); setNotice('正在保存原图…')
    uploadPending.current = (async () => {
      let count = selectedImages.size; let overflow = false
      for (const file of files) {
        if (!/\.(png|jpe?g|pdf)$/i.test(file.name)) throw new Error('只支持 PNG/JPEG/PDF')
        const image = await agentApi.upload(sid, file)
        const ids = 'page_count' in image ? (image.pages || []).map(page => page.id) : [image.id]
        if (sid === sessionRef.current) {
          const picked = ids.slice(0, Math.max(0, 20 - count)); count += picked.length
          setSelectedImages(current => new Set([...current, ...picked])); overflow ||= picked.length < ids.length
        }
      }
      await refresh(); await onPublished(); setNotice(overflow ? '全部文件已保存；超出本批 20 页的文件未自动勾选，请拆批选择。' : '文件已保存在本地；每批最多选 20 页。点击“开始识别”后，所选页面发送给 DeepSeek。')
    })().catch(async error => {await refresh().catch(()=>{});setNotice(error.message)}).finally(() => { uploadPending.current = null; setBusy(false); if (fileRef.current) fileRef.current.value = '' })
  }
  const pairing=documentPairing(session?.documents||[],session?.attachments||[],selectedImages,pairOverrides)
  const defaultSources=sourceDefaults(session?.attachments||[],session?.documents||[],selectedImages,targetDocument,pairing.pairs)
  const sourceValue=sourceChoice.mode==='manual'?sourceChoice.manual:defaultSources.join('；')
  const source=submittedSource(sourceChoice)
  const start = () => operate(async () => {
    if (!sessionRef.current) return
    const orderedImages = session?.attachments.filter(image => selectedImages.has(image.id)).map(image => image.id) || []
    const inputRegions = orderedImages.flatMap(id => sourceRegions[id] || [{ image_id: id, rect: [0, 0, 1, 1] as AIRegion['rect'] }])
    if(sourceChoice.mode==='manual'&&!source.trim())throw new Error('请填写整批统一题源，或恢复按文件自动。')
    if(pairing.errors.length)throw new Error(pairing.errors.join('；'))
    const selection = { question_numbers: questionNumbers, target_document_id: targetDocument || undefined, document_pairs: pairing.pairs }
    const signature = JSON.stringify([sessionRef.current, orderedImages, inputRegions, instruction, source, selection])
    if (pendingStart.current?.signature !== signature) pendingStart.current = { signature, id: crypto.randomUUID() }
    const value = await agentApi.start(sessionRef.current, orderedImages, instruction, source, pendingStart.current.id, inputRegions, selection)
    taskRef.current = value.id; setTask(value); pendingStart.current = null
  })
  const send = () => operate(async () => {
    if (!task || !text.trim()) return
    if (pendingChat.current?.text !== text) pendingChat.current = { text, id: crypto.randomUUID() }
    const value = await agentApi.chat(task.id, text, pendingChat.current.id); taskRef.current = value.id; setTask(value); setText(''); pendingChat.current = null
  })
  return <div className="ai-task-board"><section className="ai-task-board-inner">
    <div className="ai-workspace"><aside className="ai-chat-column">
      <div className="ai-session-controls"><select aria-label="录题会话" value={session?.id || ''} disabled={busy} onChange={event => void operate(() => switchSession(event.target.value))}>{sessions.map(value => <option key={value.id} value={value.id}>{value.title} · {new Date(value.created_at).toLocaleString()}</option>)}</select><button className="button ghost" disabled={busy} onClick={() => void operate(newSession)}>新会话</button></div>
      <div className="ai-messages">{session?.messages.map(message => <article key={message.id} className={`ai-message ai-message-${message.role}`}><b>{message.role === 'user' ? '你' : '录题助手'}</b><p>{message.content}</p></article>)}{!session?.messages.length && <p>上传截图或照片，并说明要提取哪些题。可在结果出现后对话修改题目或分类。</p>}</div>
      <textarea aria-label="录题修正对话" value={text} onChange={event => setText(event.target.value)} placeholder="例如：第3题应归入高二下学期的导数；请保留原答案。" rows={3} />
      <button className="button primary" disabled={busy || working || !task || !config?.configured || !text.trim()} onClick={send}>发送修正指令</button>
    </aside><section className="ai-main-column" ref={mainRef}>
      {notice && <div className="notice" role="status">{notice}</div>}
      {!config?.configured && <div className="ai-warning">尚未配置 DeepSeek 密钥。原图可先保存在本地，在设置中配置后开始识别。</div>}
      <section className="ai-upload-section" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); upload(Array.from(event.dataTransfer.files)) }} onPaste={event => {
        const files = Array.from(event.clipboardData.items).filter(item => item.kind === 'file').map(item => item.getAsFile()).filter((file): file is File => !!file)
        if (files.length) { event.preventDefault(); upload(files.map((file, i) => new File([file], `粘贴截图-${Date.now()}-${i}.${file.type === 'image/jpeg' ? 'jpg' : 'png'}`, { type: file.type }))) }
      }} tabIndex={0} aria-label="图片上传区">
        <div className="ai-upload-heading"><b>原材料 · 拖入图片 / PDF 或粘贴截图</b><div className="form-actions"><button className="button ghost" disabled={busy || !session} onClick={() => fileRef.current?.click()}>选择图片或 PDF</button></div><input ref={fileRef} hidden disabled={!session} type="file" multiple accept=".png,.jpg,.jpeg,.pdf" onChange={event => upload(Array.from(event.target.files || []))} /></div>
        <small>单 PDF 最多 35 页；每批识别最多 20 页、50 道题（含答案页），图片 12 MiB / PDF 32 MiB。已选 {selectedImages.size} 页，剩余 {Math.max(0, 20-selectedImages.size)} 页。</small>
        <div className="form-actions"><button className="button ghost compact" disabled={busy || !session?.attachments.length} onClick={() => {setSelectedImages(selectFirstPages(session?.attachments || []));setNotice('已按显示顺序选择前 20 页以内的原材料，其余页可另起一批。')}}>全选（最多20页）</button><button className="button ghost compact" disabled={busy || !selectedImages.size} onClick={() => setSelectedImages(new Set())}>取消选择</button></div>
        {session?.documents?.map(doc => <div key={doc.id}><b>{doc.filename} · {doc.page_count} 页</b><button className="button ghost" onClick={() => setOriginalDocument(doc)}>查看原 PDF</button><button className="button ghost" disabled={busy} onClick={() => setSelectedImages(current => {
          return selectDocumentPages(session.attachments, current, doc.id)
        })}>全选（最多20页）</button><button className="button ghost compact" disabled={busy} onClick={() => setSelectedImages(current => new Set([...current].filter(id => !session.attachments.some(page => page.id === id && page.document_id === doc.id))))}>取消选择</button>{!isAnswer(doc.filename) && <label>配对答案<select aria-label={`配对答案 ${doc.filename}`} value={pairing.values[doc.id]||''} onChange={event => setPairOverrides(current => ({ ...current, [doc.id]: event.target.value }))}><option value="">不配对（本文件可能已含解析）</option>{session.documents?.filter(answer => answer.id !== doc.id).map(answer => <option key={answer.id} value={answer.id}>{answer.filename}</option>)}</select></label>}</div>)}
        {pairing.errors.map(error=><p className="ai-warning" role="alert" key={error}>{error}</p>)}<div className="ai-attachments">{session?.attachments.map(image => <label className={selectedImages.has(image.id) ? 'selected' : ''} key={image.id}><input type="checkbox" aria-label={`选择图片 ${image.filename}`} checked={selectedImages.has(image.id)} disabled={busy} onChange={() => setSelectedImages(current => { const next = new Set(current); if (next.has(image.id)) next.delete(image.id); else if (next.size < 20) next.add(image.id); else setNotice('每批识别最多 20 页，请先取消部分页面或拆批。'); return next })} /><img src={image.url} alt={image.filename} /><span>{image.filename}{image.document_id ? ` · 第 ${image.page_number} 页` : ""}</span><button className="button ghost" disabled={busy || working} onClick={event => { event.preventDefault(); setSourceCropping(image) }}>裁剪识别范围{sourceRegions[image.id] ? ' ✓' : ''}</button></label>)}</div>
        <section className="ai-source-choice"><div className="ai-source-heading"><b>本批题源</b><div className="ai-source-modes" aria-label="题源填写方式"><button type="button" aria-pressed={sourceChoice.mode==='auto'} onClick={()=>changeSource({...sourceChoice,mode:'auto'})}>按文件自动</button><button type="button" aria-pressed={sourceChoice.mode==='manual'} onClick={()=>changeSource({...sourceChoice,mode:'manual',manual:sourceChoice.manual|| (defaultSources.length===1?defaultSources[0]:'')})}>整批统一题源</button></div></div><input aria-label="本批题源" maxLength={1000} value={sourceValue} onChange={event=>changeSource({mode:'manual',manual:event.target.value})} placeholder={sourceChoice.mode==='auto'?'上传并选择材料后自动填入文件名':'输入整批统一使用的题源'}/><small>{sourceChoice.mode==='auto'?(defaultSources.length>1?'按文件分别使用：每题采用其题干文件名；修改此栏将统一覆盖整批。':defaultSources.length?'已自动使用文件名，原题号在识别后另行记录。':'尚未选择题干材料；配对答案文件不会替代题干题源。'):'整批使用此题源，后续上传不会覆盖；可恢复按文件自动。'}</small></section>
        <div className="field-row"><label>提取题号（留空提取全部）<input aria-label="提取题号" value={questionNumbers} onChange={event => setQuestionNumbers(event.target.value)} placeholder="19 / 1,3,19 / 17–19" /></label><label>指定 PDF 文件<select aria-label="指定 PDF 文件" value={targetDocument} onChange={event => setTargetDocument(event.target.value)}><option value="">自动判断（多套同号题需选文件）</option>{session?.documents?.map(doc => <option key={doc.id} value={doc.id}>{doc.filename}</option>)}</select></label></div>
        <label>识别要求<textarea aria-label="识别要求" value={instruction} onChange={event => setInstruction(event.target.value)} rows={2} /></label>
        <button className="button primary" disabled={busy || working || !config?.configured || !selectedImages.size || selectedImages.size > 20 || !!pairing.errors.length || sourceChoice.mode==='manual'&&!source.trim()} onClick={start}>开始识别所选页面（{selectedImages.size}/20）</button>
      </section>
      {!!session?.tasks.length && <label className="ai-task-select">导入批次<select aria-label="导入批次" value={task?.id || ''} disabled={busy} onChange={event => { taskRef.current = event.target.value; void operate(async () => setTask(await agentApi.task(event.target.value))) }}>{session.tasks.map(value => <option key={value.id} value={value.id}>{new Date(value.created_at).toLocaleString()} · {value.message}</option>)}</select></label>}
      {task && <><div className="ai-task-status" ref={reviewRef}><div><b>{task.message}</b><details><summary>调用用量与诊断</summary><small>调用 {task.calls} 次 · 输入 {task.usage.prompt_tokens || 0} / 输出 {task.usage.completion_tokens || 0} tokens · 参考费用 ¥{task.estimated_cost_cny.toFixed(4)}</small><small>{task.cost_note}</small></details></div><div className="form-actions">{working ? <button className="button danger" disabled={busy} onClick={() => operate(() => agentApi.cancel(task.id))}>取消处理</button> : <button className="button ghost" disabled={busy || !config?.configured || task.state === 'complete'} onClick={() => operate(() => agentApi.retry(task.id))}>重试失败项</button>}</div></div>
        {!!task.failures?.length&&<section className="ai-task-failures"><h4>提取失败（未进入待核对）</h4>{task.failures.map(f=><article key={f.id}><b>第 {f.original_number||'未明确题号'} 题</b><p>{f.message}</p><small>{f.sources?.map(s=>`${s.filename} · 第${s.page_number}页`).join('；')}</small><button className="button ghost" disabled={busy||working||!config?.configured} onClick={()=>operate(()=>agentApi.retry(task.id,undefined,[f.id]))}>重试此失败项</button></article>)}</section>}
        {task.error && <div className="ai-warning" role="alert">{task.error}</div>}
        <p>识别出的草稿进入“待核对”，人工确认后才能进入“待入库”。</p>
      </>}
      <div className="ai-task-cards">{tasks.map(summary => <article className="ai-task-card" key={summary.id}>
        <header><h3>{summary.filenames.join('；') || '录题任务'}</h3><span>{summary.page_count} 页 · {new Date(summary.created_at).toLocaleString()}</span></header>
        <p>{summary.message}</p>{summary.error&&<p className="ai-warning">{summary.error}</p>}<p>处理中 {summary.counts.processing} · 待核对 {summary.counts.review} · 待入库 {summary.counts.publish} · 已入库 {summary.counts.published} · 已跳过 {summary.counts.skipped} · 失败 {summary.counts.failed||0} · 已删除 {summary.counts.deleted||0}</p>
        <div className="form-actions"><button className="button ghost" onClick={() => operate(async () => { await switchSession(summary.session_id); taskRef.current = summary.id; setTask(await agentApi.task(summary.id)) })}>查看任务</button>
        <button className="button primary" disabled={!summary.counts.review} onClick={() => onJump('review', summary.id)}>核对 {summary.counts.review} 题</button><button className="button ghost" disabled={!summary.counts.publish} onClick={() => onJump('publish', summary.id)}>待入库 {summary.counts.publish} 题</button>
        {summary.counts.published > 0 && <button className="button ghost" onClick={() => operate(async () => { const value = await agentApi.task(summary.id); const question = value.items.find(item => item.question_id); if(question?.question_id) await onOpenQuestion(question.question_id) })}>查看已入库题目</button>}</div>
      </article>)}</div>

    </section></div>
    <footer className="ai-footer">候选题保存在本机草稿中。关闭窗口不会取消后台任务；退出程序会停止处理，已识别的草稿保留。</footer>
    {sourceCropping && <AICropper attachments={[sourceCropping]} initial={sourceRegions[sourceCropping.id] || [{ image_id: sourceCropping.id, rect: [0, 0, 1, 1] }]} mode="question" onApply={async regions => { setSourceRegions(current => ({ ...current, [sourceCropping.id]: regions })); setNotice('本次识别范围已调整，完整原图仍保留在本地。') }} onClose={() => setSourceCropping(null)} />}
    {originalDocument && <div className="ai-subdialog" role="dialog" aria-label="原 PDF 预览"><DialogFrame className="ai-pdf-panel" bodyClassName="pdf-dialog-body" title={originalDocument.filename} closeLabel="关闭原 PDF" onClose={() => setOriginalDocument(null)}><PdfViewer src={originalDocument.url} title={originalDocument.filename} /></DialogFrame></div>}
  </section></div>
}
