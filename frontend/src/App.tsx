import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Download,
  FileCode2,
  FileText,
  ImagePlus,
  LoaderCircle,
  Menu,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { api, ApiError } from './api'
import PdfViewer from './PdfViewer'
import { useDraft } from './useDraft'
import { flushSync } from 'react-dom'
import DesktopSettings from './DesktopSettings'
import AIWorkbench from './AIWorkbench'
import BankManager from './BankManager'
import { agentApi } from './agentApi'
import type { Bank, ExportScope } from './types'
import { recognizeQuestion } from './pasteRecognition'
import { defaultPosition, restoredPosition, samePoint, targetPoint } from './position'
import type { PositionContext } from './position'
import type { RecognizedQuestion } from './pasteRecognition'
import type { Catalog, Collection, ExportStatus, KnowledgePoint, Question, QuestionOrigin, QuestionPayload, QuestionSources, QuestionType, Draft, DraftForm, SourceDraft, SearchResult, PoolState, PaperStatus } from './types'

const TYPE_LABELS: Record<QuestionType, string> = {
  single: '单选',
  multi: '多选',
  fill: '填空',
  long: '解答',
}

const EMPTY_PAYLOAD: QuestionPayload = {
  collection_code: 'gaoyi-first',
  point_code: '1.1',
  position: 1,
  type: 'single',
  question_tex: '',
  options: ['', '', '', ''],
  answer_tex: '',
  solution_tex: '',
  sources: { origins: [] },
  verified: false,
}

type Tab = 'question' | 'solution' | 'latex' | 'source'

function collectionList(catalog: Catalog | null): Collection[] {
  return catalog?.collections || []
}
function pointList(catalog: Catalog | null, collectionCode = 'gaoyi-first'): KnowledgePoint[] {
  return collectionList(catalog).find(collection => collection.code === collectionCode)?.topics.flatMap((topic) => topic.points) || []
}


function sourceDrafts(sources: QuestionSources | unknown): SourceDraft[] {
  const origins = sources && typeof sources === 'object' && !Array.isArray(sources)
    ? (sources as { origins?: unknown }).origins
    : []
  if (!Array.isArray(origins)) return []
  return origins.flatMap((origin) => {
    if (origin && typeof origin === 'object' && !Array.isArray(origin)) {
      const item = origin as QuestionOrigin
      return [{
        title: String(item.title ?? item.paper_id ?? ''),
        originalNumber: item.original_number == null ? '' : String(item.original_number),
        metadata: { ...item },
      }]
    }
    if (typeof origin === 'string' && origin.trim()) {
      return [{ title: origin.trim(), originalNumber: '', metadata: {} }]
    }
    return []
  })
}

function sourceText(row: SourceDraft): string {
  return row.title + (row.originalNumber.trim() ? `第${row.originalNumber.trim()}题` : '')
}

function originText(origin: QuestionOrigin): string {
  const title = String(origin.title ?? origin.paper_id ?? '')
  const number = origin.original_number == null ? '' : String(origin.original_number).trim()
  return title + (number ? `第${number}题` : '')
}

function sourcesFromDrafts(base: QuestionSources, drafts: SourceDraft[], missing = false): QuestionSources {
  const origins: QuestionOrigin[] = []
  if (missing) return { ...base, origins: [], source_missing: true }
  for (const draft of drafts) {
    const title = draft.title.trim()
    const originalNumber = draft.originalNumber.trim()
    if (!title && !originalNumber) continue
    const item: QuestionOrigin = { ...draft.metadata, title }
    if (originalNumber) item.original_number = originalNumber
    else delete item.original_number
    origins.push(item)
  }
  return {
    ...base,
    origins,
    source_missing: false,
  }
}

function Editor({
  catalog,
  initial,
  draft,
  defaultCollection = 'gaoyi-first',
  onClose,
  onSaved,
  onRefreshCatalog,
}: {
  catalog: Catalog
  initial: Question | null
  draft: Draft | null
  defaultCollection?: string
  onClose: () => void
  onSaved: (question: Question) => void
  onRefreshCatalog: () => Promise<Catalog>
}) {
  const [form, setForm] = useState<DraftForm>(() =>
    draft ? { ...structuredClone(draft.content.form), bank_id:draft.bank_id||draft.content.form.bank_id||catalog.bank_id||'system', position: initial && draft.position_mode !== 'move'
      && samePoint(initial, draft.content.form.collection_code, draft.content.form.point_code) ? initial.position : draft.content.form.position } : initial
      ? {
          bank_id:initial.bank_id||catalog.bank_id||'system',
          collection_code: initial.collection_code,
          point_code: initial.point_code,
          position: initial.position,
          type: initial.type,
          question_tex: initial.question_tex,
          options: initial.options,
          answer_tex: initial.answer_tex,
          solution_tex: initial.solution_tex,
          sources: initial.sources,
          verified: initial.verified,
        }
      : { ...EMPTY_PAYLOAD, bank_id:catalog.bank_id||'system', collection_code: defaultCollection, point_code: pointList(catalog, defaultCollection)[0]?.code || '1.1',
          position: (pointList(catalog, defaultCollection)[0]?.count || 0) + 1 },
  )
  const [sourceBase] = useState<QuestionSources>(() => draft?.content.form.sources || initial?.sources || {})
  const [positionContext, setPositionContext] = useState<PositionContext>(() => {
    const point = targetPoint(catalog, form.collection_code, form.point_code)
    return point ? restoredPosition(initial, draft, form.collection_code, point) : { position_mode: 'move', target_order_revision: null }
  })
  const [positionConflict, setPositionConflict] = useState(positionContext.position_mode === 'move' && positionContext.target_order_revision === null)
  const [sourceRows, setSourceRows] = useState<SourceDraft[]>(() => {
    if (draft) return structuredClone(draft.content.source_rows)
    const rows = sourceDrafts(initial?.sources || {})
    return rows.length ? rows : [{ title: '', originalNumber: '', metadata: {} }]
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('填写题干和解析后自动生成预览')
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewView, setPreviewView] = useState<'question' | 'solution'>('question')
  const [previewState, setPreviewState] = useState<'empty' | 'stale' | 'building' | 'ready' | 'failed'>('empty')
  const previewSession = useRef(crypto.randomUUID())
  const previewSequence = useRef(0)
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [operationError, setOperationError] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const uploadPending = useRef<Promise<void> | null>(null)
  const operation = useRef<Promise<void> | null>(null)
  const draftState = useDraft({ form, source_rows: sourceRows }, initial, draft, positionContext)
  const close = async () => {
    if (operation.current) return
    setBusy(true)
    try { await uploadPending.current; await draftState.flush(); draftState.finish(); onClose() }
    catch (error) { setOperationError(error instanceof Error ? error.message : '草稿保存失败，请重试') }
    finally { setBusy(false) }
  }
  const prepareClose = useRef<() => Promise<void>>(async () => {})
  prepareClose.current = async () => {
    await uploadPending.current
    await operation.current
    await draftState.flush()
  }
  useEffect(() => window.desktop?.onPrepareClose(async () => {
    setBusy(true)
    try { await prepareClose.current() } finally { setBusy(false) }
  }), [])
  const discard = async () => {
    const message = '丢弃这份草稿？正式题目不受影响。此操作不可恢复。'
    const ok = window.desktop ? await window.desktop.confirmDiscard(message) : window.confirm(message)
    if (!ok) return
    setBusy(true)
    try { await uploadPending.current; await draftState.discard(); onClose() }
    catch (error) { setMessage(error instanceof Error ? error.message : '丢弃失败'); draftState.resume() }
    finally { setBusy(false) }
  }

  const currentPoint = pointList(catalog, form.collection_code).find((point) => point.code === form.point_code)
  const maxPosition = (currentPoint?.count || 0) + (initial?.collection_code === form.collection_code && initial?.point_code === form.point_code ? 0 : 1)
  const sourceMissing = form.sources?.source_missing === true
  const parsedPaste = useMemo<{ result: RecognizedQuestion | null; error: string }>(() => {
    if (!pasteText.trim()) return { result: null, error: '' }
    try { return { result: recognizeQuestion(pasteText), error: '' } }
    catch (error) { return { result: null, error: error instanceof Error ? error.message : '无法识别粘贴文本' } }
  }, [pasteText])
  const pasteConflicts = parsedPaste.result ? [
    parsedPaste.result.question && form.question_tex.trim() && '题干',
    parsedPaste.result.answer && form.answer_tex.trim() && '答案',
    parsedPaste.result.solution && form.solution_tex.trim() && '解析',
    ...(parsedPaste.result.options || []).map((value, index) => value && form.options[index]?.trim() && `选项 ${'ABCD'[index]}`),
  ].filter(Boolean) : []

  useEffect(() => {
    const sequence = ++previewSequence.current
    const abort = new AbortController()
    setPreviewState('stale')
    setMessage('预览已过期，等待最新内容编译…')
    if (!form.question_tex.trim() || !form.solution_tex.trim() || saving || busy) {
      if (!form.question_tex.trim() || !form.solution_tex.trim()) setMessage('题干或解析未填写完整，当前预览尚未更新。')
      return () => abort.abort()
    }
    const timeout = window.setTimeout(async () => {
      setPreviewState('building')
      setMessage('正在编译预览…')
      try {
        const blob = await api.preview({ ...form, position: Number(form.position), sources: sourcesFromDrafts(sourceBase, sourceRows, sourceMissing) }, previewView,
          { signal: abort.signal, sessionId: previewSession.current, revision: sequence })
        if (abort.signal.aborted || sequence !== previewSequence.current) return
        const url = URL.createObjectURL(blob)
        setPreviewUrl((old) => {
          if (old) URL.revokeObjectURL(old)
          return url
        })
        setPreviewState('ready')
        setMessage('预览已更新')
      } catch (error) {
        if (!abort.signal.aborted && sequence === previewSequence.current) {
          setPreviewState('failed')
          setMessage(error instanceof Error ? error.message : '预览失败')
        }
      }
    }, 500)
    return () => { abort.abort(); window.clearTimeout(timeout) }
  }, [form, previewView, sourceRows, sourceBase, saving, busy])

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  const setField = <K extends keyof DraftForm>(key: K, value: DraftForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }))

  const updateSourceRows = (rows: SourceDraft[]) => {
    setSourceRows(rows)
    setField('sources', sourcesFromDrafts(sourceBase, rows))
  }
  const setSourceMissing = async (missing: boolean) => {
    if (missing && sourceRows.some(row => sourceText(row).trim())) {
      const message = '勾选“题源暂缺”会清空当前题源输入，确定继续吗？'
      const confirmed = window.confirm(message)
      if (!confirmed) return
    }
    const rows = [{ title: '', originalNumber: '', metadata: {} }]
    setSourceRows(rows)
    setField('sources', sourcesFromDrafts(sourceBase, rows, missing))
  }

  const applyPaste = (result: RecognizedQuestion) => {
    setForm(current => {
      const hasOptions = !!result.options
      const existingOptions = current.options.length === 4 ? current.options : ['', '', '', '']
      const options = hasOptions ? existingOptions.map((value, index) => value.trim() ? value : result.options![index]) : current.options
      const filledOptions = hasOptions && options.some((value, index) => value !== existingOptions[index])
      return {
        ...current,
        question_tex: current.question_tex.trim() ? current.question_tex : result.question,
        answer_tex: current.answer_tex.trim() ? current.answer_tex : result.answer,
        solution_tex: current.solution_tex.trim() ? current.solution_tex : result.solution,
        options,
        type: filledOptions && result.suggestedType ? result.suggestedType : current.type,
      }
    })
    setPasteOpen(false)
    setPasteText('')
  }

  const changeType = (type: QuestionType) => {
    setForm((current) => ({
      ...current,
      type,
      options: type === 'single' || type === 'multi'
        ? current.options.length === 4 ? current.options : ['', '', '', '']
        : [],
    }))
  }

  const uploadFile = async (file?: File) => {
    if (!file) return
    setBusy(true)
    try {
      setMessage('正在上传配图…')
      const uploaded = await api.upload(file)
      const snippet = `\\par\\includegraphics[width=.45\\linewidth]{${uploaded.latex_path}}`
      flushSync(() => setForm(current => ({ ...current, question_tex: `${current.question_tex}${current.question_tex ? '\n' : ''}${snippet}` })))
      setMessage(`已插入配图：${uploaded.original_name}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '上传失败')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const save = (asNew = false) => {
    if (operation.current) return
    setSaving(true)
    setOperationError('')
    draftState.pause()
    operation.current = (async () => {
      try {
        await uploadPending.current
        const question = await draftState.publish(asNew)
        onSaved(question)
      } catch (error) {
        setOperationError(error instanceof Error ? error.message : '保存失败')
        if (error instanceof ApiError && error.code === 'position_conflict') {
          setPositionConflict(true)
          await onRefreshCatalog().catch(() => {})
        } else if (error instanceof ApiError && error.status === 409 && draftState.sourceId) setConflict(true)
        draftState.resume()
      } finally { setSaving(false); operation.current = null }
    })()
  }

  const confirmPosition = async () => {
    setBusy(true)
    try {
      const refreshed = await onRefreshCatalog()
      const point = targetPoint(refreshed, form.collection_code, form.point_code)
      if (!point) throw new Error('考点不存在，请重新选择')
      const max = defaultPosition(initial, form.collection_code, point).max
      const position = Number(form.position)
      if (!Number.isInteger(position) || position < 1 || position > max) throw new Error(`插入序号须为 1 至 ${max}，请修改后重新确认`)
      setPositionContext({ position_mode: 'move', target_order_revision: point.order_revision })
      setPositionConflict(false)
      setOperationError('插入位置已重新确认，可以校验并保存。')
    } catch (error) { setOperationError(error instanceof Error ? error.message : '位置确认失败') }
    finally { setBusy(false) }
  }

  return (
    <div className="editor-backdrop" role="dialog" aria-modal="true">
      <section className="editor-panel">
        <header className="editor-header">
          <div>
            <span className="eyebrow">题库管理</span>
            <h2>{draftState.sourceId ? '修改题目' : '增加题目'}</h2>
          </div>
          <button className="icon-button" disabled={busy || saving} onClick={close} aria-label="关闭"><X size={20} /></button>
        </header>
        <div className="editor-body">
          <fieldset className="form-column" disabled={saving || busy}>
            <label>所属集合
              <select aria-label="所属集合" value={form.collection_code} onChange={e => {
                const collection_code = e.target.value
                const firstPoint = (initial?.collection_code === collection_code ? targetPoint(catalog, collection_code, initial.point_code) : null) || pointList(catalog, collection_code)[0]
                if (!firstPoint) return
                const target = defaultPosition(initial, collection_code, firstPoint)
                setForm(current => ({ ...current, collection_code, point_code: firstPoint.code, position: target.position }))
                setPositionContext(target.context)
                setPositionConflict(false)
              }}>{collectionList(catalog).map(item => <option key={item.code} value={item.code}>{item.title}（{item.material}）</option>)}</select>
            </label>
            {!currentPoint && <p role="alert">草稿的原集合或考点已不存在，内容已保留。请选择有效考点后再发布。</p>}
            <div className="field-row three">
              <label>考点
                <select aria-label="考点" value={form.point_code} onChange={e => {
                  const point_code = e.target.value
                  const point = targetPoint(catalog, form.collection_code, point_code)
                  if (!point) return
                  const target = defaultPosition(initial, form.collection_code, point)
                  setForm(current => ({ ...current, point_code, position: target.position }))
                  setPositionContext(target.context)
                  setPositionConflict(false)
                }}>
                  {!currentPoint && <option value={form.point_code}>原考点 {form.point_code} 不存在，请重新选择</option>}
                  {collectionList(catalog).find(item => item.code === form.collection_code)?.topics.map(topic =>
                    <optgroup key={topic.code} label={topic.title}>
                      {topic.points.map(point => <option key={point.code} value={point.code}>{point.title}</option>)}
                    </optgroup>)}
                </select>
              </label>
              <label>插入序号
                <input type="number" min={1} max={Math.max(1, maxPosition)} value={form.position ?? ''}
                  onChange={(e) => {
                    setField('position', e.target.value)
                    if (!positionConflict) setPositionContext({ position_mode: 'move', target_order_revision: currentPoint?.order_revision ?? null })
                  }} />
              </label>
              <label>题型
                <select aria-label="题型" value={form.type} onChange={(e) => changeType(e.target.value as QuestionType)}>
                  {Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </div>
            {positionConflict && <p role="alert">插入位置需要重新确认。草稿内容已保留；核对序号后点击“重新确认位置”。</p>}
            {!draftState.sourceId && <button className="button ghost paste-entry" type="button" onClick={() => setPasteOpen(true)}>粘贴识别</button>}
            <label>题干 LaTeX
              <textarea rows={7} value={form.question_tex} onChange={(e) => setField('question_tex', e.target.value)} />
            </label>
            {(form.type === 'single' || form.type === 'multi') && (
              <div className="options-grid">
                {['A', 'B', 'C', 'D'].map((label, index) => (
                  <label key={label}>选项 {label}
                    <textarea rows={2} value={form.options[index] || ''} onChange={(e) => {
                      const options = [...form.options]
                      options[index] = e.target.value
                      setField('options', options)
                    }} />
                  </label>
                ))}
              </div>
            )}
            <label>答案 LaTeX
              <textarea rows={2} value={form.answer_tex} onChange={(e) => setField('answer_tex', e.target.value)} />
            </label>
            <label>解析 LaTeX
              <textarea rows={8} value={form.solution_tex} onChange={(e) => setField('solution_tex', e.target.value)} />
            </label>
            <div className="source-editor">
              <div className="source-editor-heading">
                <div><b>题源</b><span>可直接填写“月考卷第8题”，也可添加多个来源</span></div>
                <button className="button ghost compact" type="button" disabled={sourceMissing} onClick={() => updateSourceRows([...sourceRows, { title: '', originalNumber: '', metadata: {} }])}><Plus size={15} />添加题源</button>
              </div>
              <label className="check source-missing"><input type="checkbox" checked={sourceMissing} onChange={e => { void setSourceMissing(e.target.checked) }} />题源暂缺</label>
              {sourceRows.map((row, index) => (
                <div className="source-row" key={index}>
                  <label>题源信息
                    <input value={sourceText(row)} disabled={sourceMissing} placeholder="如：月考卷第8题" onChange={(e) => {
                      const { original_number, ...metadata } = row.metadata
                      const rows = sourceRows.map((item, i) => i === index ? { title: e.target.value, originalNumber: '', metadata } : item)
                      updateSourceRows(rows)
                    }} />
                  </label>
                  <button className="icon-button source-remove" type="button" disabled={sourceMissing} aria-label={`移除题源 ${index + 1}`} onClick={() => updateSourceRows(sourceRows.length === 1 ? [{ title: '', originalNumber: '', metadata: {} }] : sourceRows.filter((_, i) => i !== index))}><X size={17} /></button>
                </div>
              ))}
            </div>
            <div className="form-actions secondary-actions">
              <label className="check"><input type="checkbox" checked={form.verified} onChange={(e) => setField('verified', e.target.checked)} /> 已核验</label>
              <input ref={fileRef} hidden type="file" accept=".png,.jpg,.jpeg,.pdf" onChange={(e) => { uploadPending.current = uploadFile(e.target.files?.[0]).finally(() => { uploadPending.current = null }) }} />
              <button className="button ghost" onClick={() => fileRef.current?.click()}><ImagePlus size={17} />上传并插入配图</button>
            </div>
          </fieldset>
          <div className="editor-preview">
            <div className="preview-toolbar">
              <div className="segmented">
                <button className={previewView === 'question' ? 'active' : ''} onClick={() => setPreviewView('question')}>题目</button>
                <button className={previewView === 'solution' ? 'active' : ''} onClick={() => setPreviewView('solution')}>解析</button>
              </div>
              <span>{message}</span>
            </div>
            <div className="preview-feedback">{previewUrl && previewState !== 'ready' && <p className="preview-warning" role="status">当前画面是上一次预览，尚未反映最新修改。</p>}</div>
            {previewUrl ? <div className={previewState === 'ready' ? 'preview-document' : 'preview-document preview-stale'}><PdfViewer title="LaTeX 实时预览" src={previewUrl} /></div> : <div className="empty-preview"><FileText size={36} /><p>预览将在此显示</p></div>}
          </div>
        </div>
        <div className="editor-messages"><span role="status" className="draft-status">{draftState.status}</span><span role="alert">{operationError || message}</span></div>
        <footer className="editor-footer">
          <span>{initial ? `当前版本 ${initial.revision}` : `可插入 1–${Math.max(1, maxPosition)}`}</span>
          <div className="form-actions">
            <button className="button ghost" disabled={saving || busy} onClick={discard}>丢弃草稿</button>
            <button className="button ghost" disabled={saving || busy} onClick={() => { void draftState.flush(true).catch(() => {}) }}>保存草稿</button>
            <button className="button ghost" disabled={saving || busy} onClick={close}>保存并关闭</button>
            {positionConflict && <button className="button ghost" disabled={saving || busy || !currentPoint} onClick={confirmPosition}>重新确认位置</button>}
            {conflict && <button className="button ghost" disabled={saving || busy || !currentPoint || positionConflict} onClick={() => save(true)}>另存为新题</button>}
            <button className="button primary" disabled={saving || busy || !currentPoint || positionConflict} onClick={() => save()}>
              {saving && <LoaderCircle className="spin" size={17} />}{saving ? '校验并保存…' : '校验并保存'}
            </button>
          </div>
        </footer>
      </section>
      {pasteOpen && <div className="paste-backdrop" role="dialog" aria-modal="true" aria-label="粘贴识别"><section className="paste-panel">
        <header><h3>粘贴识别</h3><button className="icon-button" type="button" aria-label="关闭粘贴识别" onClick={() => setPasteOpen(false)}><X size={19} /></button></header>
        <label>粘贴题目文本<textarea value={pasteText} onChange={e => setPasteText(e.target.value)} placeholder={'【题目】\n题干\nA. 选项一\nB. 选项二\nC. 选项三\nD. 选项四\n【答案】\nA\n【解析】\n解析内容'} rows={9} /></label>
        {parsedPaste.error && <p role="alert" className="paste-error">{parsedPaste.error}</p>}
        {parsedPaste.result && <div className="paste-review"><h4>识别结果，请确认</h4>
          <section><b>题干</b><pre>{parsedPaste.result.question || '（空）'}</pre></section>
          {parsedPaste.result.options?.map((option, index) => <section key={index}><b>选项 {'ABCD'[index]}</b><pre>{option || '（空）'}</pre></section>)}
          <section><b>答案</b><pre>{parsedPaste.result.answer || '（空）'}</pre></section>
          <section><b>解析</b><pre>{parsedPaste.result.solution || '（空）'}</pre></section>
          <p>建议题型：{parsedPaste.result.suggestedType ? TYPE_LABELS[parsedPaste.result.suggestedType] : '保持当前题型，请核对'}</p>
          {parsedPaste.result.warnings.map(warning => <p className="paste-warning" key={warning}>{warning}</p>)}
          {pasteConflicts.length > 0 && <p className="paste-warning">已有内容将保留：{pasteConflicts.join('、')}</p>}
        </div>}
        <footer><button className="button ghost" type="button" onClick={() => setPasteOpen(false)}>取消</button><button className="button primary" type="button" disabled={!parsedPaste.result} onClick={() => parsedPaste.result && applyPaste(parsedPaste.result)}>确认填入空字段</button></footer>
      </section></div>}
    </div>
  )
}

export default function App() {
  const [bankId,setBankId]=useState(()=>localStorage.getItem('question-bank')||'system')
  const bankRef=useRef(bankId);bankRef.current=bankId
  const pendingFocus=useRef<{id:string;collection:string}|null>(null)
  api.setBank(bankId);agentApi.setBank(bankId)
  const [banks,setBanks]=useState<Bank[]>([]);const [bankOpen,setBankOpen]=useState(false);const [allBanks,setAllBanks]=useState(false)
  const [exportScope,setExportScope]=useState<ExportScope>({kind:'semester'})
  const scopeSignature=JSON.stringify(exportScope)

  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [question, setQuestion] = useState<Question | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [tab, setTab] = useState<Tab>('question')
  const [search, setSearch] = useState('')
  const [openTopics, setOpenTopics] = useState<Set<string>>(new Set(['1']))
  const [openPoints, setOpenPoints] = useState<Set<string>>(new Set(['1.1']))
  const [editing, setEditing] = useState<{ initial: Question | null; draft: Draft | null; key: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [selectedCollection, setSelectedCollection] = useState(()=>localStorage.getItem('question-semester')||'gaoyi-first')
  const collectionRef = useRef(selectedCollection)
  collectionRef.current = selectedCollection
  const [exportOpen, setExportOpen] = useState(false)
  const [poolOpen, setPoolOpen] = useState(false)
  const [pool, setPool] = useState<PoolState | null>(null)
  const [checkedPoolIds, setCheckedPoolIds] = useState<Set<string>>(new Set())
  const [poolSelected, setPoolSelected] = useState<Set<string>>(new Set())
  const [poolBusy, setPoolBusy] = useState(false)
  const [randomCount, setRandomCount] = useState(1)
  const [paperStatus, setPaperStatus] = useState<PaperStatus | null>(null)
  const [drafts, setDrafts] = useState<Draft[] | null>(null)
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchStatus, setSearchStatus] = useState('')
  const [questionLoading, setQuestionLoading] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const loadSequence = useRef(0)
  const selectedRef = useRef(selectedId)
  selectedRef.current = selectedId
  const ready = !!question && question.id === selectedId && question.collection_code === selectedCollection && question.bank_id === bankId && !questionLoading && !actionBusy
  const poolIds = useMemo(() => new Set(pool?.items.map(item => item.id) || []), [pool])
  useEffect(() => {
    setCheckedPoolIds(new Set(poolIds))
    setPoolSelected(current => new Set([...current].filter(id => poolIds.has(id))))
  }, [poolIds])

  useEffect(() => {
    const requestBank=bankId;let cancelled=false
    api.pool().then(value=>{if(!cancelled&&bankRef.current===requestBank)setPool(value)}).catch(error => setNotice(error.message))
    api.paperStatus().then(value=>{if(!cancelled&&bankRef.current===requestBank)setPaperStatus(value)}).catch(error => setNotice(error.message))
    return ()=>{cancelled=true}
  }, [bankId])
  useEffect(() => {
    if (!poolOpen && paperStatus?.state !== 'pending' && paperStatus?.state !== 'building') return
    const requestBank=bankId;let cancelled=false
    const timer = window.setInterval(() => { api.paperStatus().then(value=>{if(!cancelled&&bankRef.current===requestBank)setPaperStatus(value)}).catch(() => {}) }, 1800)
    return () => {cancelled=true;window.clearInterval(timer)}
  }, [poolOpen, paperStatus?.state, bankId])

  const togglePool = async (id: string) => {
    const wasChecked = poolIds.has(id)
    setCheckedPoolIds(current => { const next = new Set(current); wasChecked ? next.delete(id) : next.add(id); return next })
    setPoolBusy(true)
    try {
      const result = wasChecked ? await api.removePool(id) : await api.addPool(id)
      setPool(result)
      if (wasChecked) setPoolSelected(current => { const next = new Set(current); next.delete(id); return next })
    } catch (error) { setCheckedPoolIds(new Set(poolIds)); setNotice(error instanceof Error ? error.message : '组卷区操作失败') }
    finally { setPoolBusy(false) }
  }

  const removePoolSelected = async () => {
    if (!poolSelected.size) return
    setPoolBusy(true)
    try { setPool(await api.removePoolBatch([...poolSelected])); setPoolSelected(new Set()) }
    catch (error) { setNotice(error instanceof Error ? error.message : '批量移除失败') }
    finally { setPoolBusy(false) }
  }
  const undoPool = async () => {
    setPoolBusy(true)
    try { setPool(await api.undoPool()) }
    catch (error) { setNotice(error instanceof Error ? error.message : '撤销失败') }
    finally { setPoolBusy(false) }
  }
  const createPaper = async (mode: 'manual' | 'random') => {
    setPoolBusy(true)
    try {
      const status = await api.createPaper(mode === 'manual'
        ? { mode, question_ids: [...poolSelected] }
        : { mode, count: randomCount })
      setPaperStatus(status)
      setNotice('训练卷已提交编译，题目卷和解析卷使用同一份快照。')
    } catch (error) { setNotice(error instanceof Error ? error.message : '组卷失败') }
    finally { setPoolBusy(false) }
  }
  const paperFile = async (kind: 'question' | 'solution', action: 'open' | 'save') => {
    try {
      if (window.desktop) await window.desktop.paperFile(kind, action,bankId)
      else {
        const link = document.createElement('a')
        link.href = `/api/papers/files/${kind}?bank_id=${encodeURIComponent(bankId)}`
        if (action === 'save') link.download = paperStatus?.files[kind] || '训练卷.pdf'
        else link.target = '_blank'
        link.click()
      }
    } catch (error) { setNotice(error instanceof Error ? error.message : '文件操作失败') }
  }

  const openEditor = async (initial: Question | null, recovered: Draft | null = null) => {
    setActionBusy(true)
    try {
      const found = recovered || (initial ? (await api.drafts()).find(item => item.source_question_id === initial.id) || null : null)
      const existing = found ? await api.draft(found.id) : null
      let original = initial
      if (existing?.source_question_id) {
        try { original = await api.question(existing.source_question_id) }
        catch (error) { if (!(error instanceof ApiError && error.status === 404)) throw error }
      }
      setEditing({ initial: original ? structuredClone(original) : null, draft: existing, key: existing?.id || crypto.randomUUID() })
      setDrafts(null)
    } catch (error) { setNotice(error instanceof Error ? error.message : '无法打开编辑器') }
    finally { setActionBusy(false) }
  }
  const openDrafts = async () => {
    try { setDrafts(await api.drafts()) }
    catch (error) { setNotice(error instanceof Error ? error.message : '草稿箱加载失败') }
  }
  const discardFromList = async (draft: Draft) => {
    const message = '丢弃这份草稿？正式题目不受影响。此操作不可恢复。'
    if (!(window.desktop ? await window.desktop.confirmDiscard(message) : window.confirm(message))) return
    try { await api.discardDraft(draft.id, draft.revision); await openDrafts() }
    catch (error) { setNotice(error instanceof Error ? error.message : '丢弃失败'); await openDrafts() }
  }
  useEffect(() => {
    if (editing || aiOpen) return
    return window.desktop?.onPrepareClose(async () => {})
  }, [editing, aiOpen])
  useEffect(() => {
    const abort = new AbortController()
    setSearchResults([])
    if (!search.trim()) { setSearchStatus(''); return }
    setSearchStatus('搜索中…')
    const timer = window.setTimeout(() => {
      api.search(search, abort.signal, allBanks).then(result => {
        if (!abort.signal.aborted) { setSearchResults(result.items); setSearchStatus(`找到 ${result.total} 道题`) }
      }).catch(error => { if (!abort.signal.aborted) setSearchStatus(error.message) })
    }, 200)
    return () => { window.clearTimeout(timer); abort.abort() }
  }, [search, catalog, allBanks, bankId])

  const loadCatalog = async (keepId = selectedRef.current, scope = collectionRef.current) => {
    const sequence = ++loadSequence.current
    const requestBank=bankRef.current
    const data = await api.catalog()
    if (sequence !== loadSequence.current || requestBank!==bankRef.current) return data
    setQuestionLoading(true)
    setQuestion(null)
    setCatalog(data)
    void api.banks().then(value=>{if(requestBank===bankRef.current)setBanks(value)})
    const current = data.collections.find(collection => collection.code === (collectionRef.current === scope ? scope : collectionRef.current)) || data.collections[0]
    const exists = current?.topics.some((topic) => topic.points.some((point) => point.questions.some((q) => q.id === keepId)))
    const nextId = exists ? keepId : current?.topics.flatMap((t) => t.points).flatMap((p) => p.questions)[0]?.id || ''
    selectedRef.current = nextId
    setSelectedId(nextId)
    if (nextId) {
      const point = current?.topics.flatMap(t => t.points).find(p => p.questions.some(q => q.id === nextId))
      const topic = current?.topics.find(t => t.points.some(p => p.code === point?.code))
      if (point && topic) { setOpenTopics(new Set([topic.code])); setOpenPoints(new Set([point.code])) }
    }
    return data
  }

  useEffect(() => {
    void api.banks().then(value=>{setBanks(value);if(!value.some(b=>b.id===bankRef.current))switchBank('system')})
    const focus=pendingFocus.current;pendingFocus.current=null
    loadCatalog(focus?.id||'',focus?.collection||collectionRef.current)
      .catch((error) => setNotice(error instanceof Error ? error.message : '题库加载失败'))
      .finally(() => setLoading(false))
  }, [bankId])

  useEffect(() => {
    const abort = new AbortController()
    setQuestion(null)
    if (!selectedId) { setQuestionLoading(false); return }
    setQuestionLoading(true)
    api.question(selectedId, abort.signal).then(result => {
      if (!abort.signal.aborted && result.id === selectedRef.current) setQuestion(result)
    }).catch(error => { if (!abort.signal.aborted) setNotice(error.message) })
      .finally(() => { if (!abort.signal.aborted) setQuestionLoading(false) })
    return () => abort.abort()
  }, [selectedId, catalog, selectedCollection, bankId])

  useEffect(() => {
    const abort = new AbortController()
    setExportStatus(null)
    let fetching = false
    const refresh = async () => {
      if (fetching) return
      fetching = true
      try {
        const status = await api.exportStatus(selectedCollection, abort.signal,exportScope)
        if (!abort.signal.aborted && status.collection_code === collectionRef.current) setExportStatus(status)
      } catch (error) { if (!abort.signal.aborted) setNotice(error instanceof Error ? error.message : '导出状态加载失败') }
      finally { fetching = false }
    }
    void refresh()
    const timer = window.setInterval(refresh, 2000)
    return () => { abort.abort(); window.clearInterval(timer) }
  }, [selectedCollection, catalog, bankId, scopeSignature])

  const selectedMeta = useMemo(() => {
    if (!catalog || !selectedId) return null
    const collection = catalog.collections.find(item => item.code === selectedCollection)
    for (const topic of collection?.topics || []) for (const point of topic.points) {
      const summary = point.questions.find((item) => item.id === selectedId)
      if (summary) return { topic, point, summary }
    }
    return null
  }, [catalog, selectedId, selectedCollection])

  const toggleSet = (setter: (value: Set<string>) => void, current: Set<string>, code: string) => {
    const next = new Set(current)
    next.has(code) ? next.delete(code) : next.add(code)
    setter(next)
  }

  const chooseQuestion = (id: string, topicCode: string, pointCode: string, collectionCode = selectedCollection) => {
    collectionRef.current = collectionCode
    setSelectedCollection(collectionCode)
    selectedRef.current = id
    setSearch('')
    if (id !== selectedId) { setQuestion(null); setQuestionLoading(true); setSelectedId(id) }
    setOpenTopics((current) => new Set(current).add(topicCode))
    setOpenPoints((current) => new Set(current).add(pointCode))
    setSidebarOpen(false)
    setTab('question')
  }

  const switchBank=(id:string,focus?:{id:string;collection:string},savedNavigation=false)=>{
    if((editing||aiOpen)&&!savedNavigation){setNotice('请先保存并关闭当前编辑窗口');return}
    pendingFocus.current=focus||null;if(focus){collectionRef.current=focus.collection;setSelectedCollection(focus.collection)}
    bankRef.current=id;api.setBank(id);agentApi.setBank(id);setBankId(id);localStorage.setItem('question-bank',id)
    ++loadSequence.current;setSelectedId('');selectedRef.current='';setQuestion(null);setCatalog(null);setSearch('');setDrafts(null);setPool(null);setPaperStatus(null);setPoolSelected(new Set());setCheckedPoolIds(new Set());setExportScope({kind:'semester'});setExportStatus(null)
  }

  const chooseCollection = (code: string) => {
    if (code === collectionRef.current) { setSearch(''); return }
    collectionRef.current = code
    setSelectedCollection(code)
    localStorage.setItem('question-semester',code);setExportScope({kind:'semester'})
    setExportStatus(null)
    setSearch('')
    const collection = catalog?.collections.find(item => item.code === code)
    const first = collection?.topics.flatMap(topic => topic.points).flatMap(point => point.questions)[0]
    const topic = collection?.topics.find(t => t.points.some(p => p.questions.some(q => q.id === first?.id))) || collection?.topics[0]
    const point = topic?.points.find(p => p.questions.some(q => q.id === first?.id)) || topic?.points[0]
    selectedRef.current = first?.id || ''
    setSelectedId(first?.id || '')
    setQuestion(null)
    setQuestionLoading(!!first)
    setOpenTopics(new Set(topic ? [topic.code] : []))
    setOpenPoints(new Set(point ? [point.code] : []))
  }

  const remove = async () => {
    if (!ready || !question || !selectedMeta) return
    const prompt = `永久删除“${selectedMeta.point.title}”中的第 ${question.position} 题？\n\n删除后不可从系统恢复，后续题号将自动前移。`
    setActionBusy(true)
    try {
      const ok = window.desktop ? await window.desktop.confirmDelete(prompt) : window.confirm(prompt)
      if (!ok) return
      await api.remove(question.id, question.revision)
      setPool(await api.pool())
      setNotice('题目已永久删除，考点内题号已重新连续排列。')
      await loadCatalog('')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '删除失败')
      if (error instanceof ApiError && error.status === 409) await loadCatalog(question.id)
    } finally { setActionBusy(false) }
  }

  const saved = async (savedQuestion: Question) => {
    setEditing(null)
    setNotice('保存成功。相关集合的导出已过期，可点击“导出当前集合”更新。')
    collectionRef.current = savedQuestion.collection_code
    setSelectedCollection(savedQuestion.collection_code)
    await loadCatalog(savedQuestion.id, savedQuestion.collection_code).catch(error => setNotice(`保存成功，但刷新失败：${error.message}`))

  }

  const exportAll = async () => {
    const code = collectionRef.current
    const requestBank=bankRef.current
    try {
      const status = await api.exportAll(code,exportScope)
      if (collectionRef.current === code && bankRef.current===requestBank) setExportStatus(status)
      setNotice('已提交当前集合导出任务，题目册和解析册使用同一份快照。')
    } catch (error) {
      if (collectionRef.current === code && bankRef.current===requestBank) {
        setNotice(error instanceof Error ? error.message : '导出任务启动失败')
        const status = await api.exportStatus(code,undefined,exportScope).catch(() => null)
        if (collectionRef.current === code && bankRef.current===requestBank) setExportStatus(status)
      }
    }
  }

  const exportFile = async (kind: 'question' | 'solution', action: 'open' | 'save') => {
    try { await window.desktop?.exportFile(kind, action, selectedCollection, exportStatus?.key) }
    catch (error) { setNotice(error instanceof Error ? error.message : '文件操作失败') }
  }

  const exportControls = <>
          <span className="eyebrow">题库导出 · {catalog?.bank_name}</span>
          <label className="export-collection-select">当前集合<select aria-label="当前集合" value={selectedCollection} onChange={e => chooseCollection(e.target.value)}>{collectionList(catalog).map(item => <option key={item.code} value={item.code}>{item.title}（{item.material}）</option>)}</select></label>
          <label className="export-collection-select">导出范围<select aria-label="导出范围" value={exportScope.kind} onChange={e=>{const kind=e.target.value as ExportScope['kind'];setExportScope(kind==='topic'?{kind,topic_code:selectedMeta?.topic.code||catalog?.collections.find(c=>c.code===selectedCollection)?.topics[0]?.code}:kind==='point'?{kind,point_code:selectedMeta?.point.code||catalog?.collections.find(c=>c.code===selectedCollection)?.topics[0]?.points[0]?.code}:kind==='selected'?{kind,question_ids:[]}: {kind})}}><option value="semester">当前学期全部</option><option value="topic">单个专题</option><option value="point">单个考点</option><option value="selected">勾选题目</option></select></label>
          {exportScope.kind==='topic'&&<select aria-label="导出专题" value={exportScope.topic_code} onChange={e=>setExportScope({kind:'topic',topic_code:e.target.value})}>{catalog?.collections.find(c=>c.code===selectedCollection)?.topics.map(t=><option key={t.code} value={t.code}>{t.title}</option>)}</select>}
          {exportScope.kind==='point'&&<select aria-label="导出考点" value={exportScope.point_code} onChange={e=>setExportScope({kind:'point',point_code:e.target.value})}>{catalog?.collections.find(c=>c.code===selectedCollection)?.topics.flatMap(t=>t.points.map(p=><option key={p.code} value={p.code}>{p.title}</option>))}</select>}
          {exportScope.kind==='selected'&&<div className="bank-question-list" style={{maxHeight:160}}>{catalog?.collections.find(c=>c.code===selectedCollection)?.topics.flatMap(t=>t.points.flatMap(p=>p.questions.map(q=><label key={q.id}><input type="checkbox" checked={exportScope.question_ids?.includes(q.id)||false} onChange={()=>setExportScope(old=>({...old,question_ids:old.question_ids?.includes(q.id)?old.question_ids.filter(id=>id!==q.id):[...(old.question_ids||[]),q.id]}))}/><span>{p.code} · 第{q.local_number}题</span></label>)))}</div>}
          <p>{catalog?.bank_name} / {catalog?.collections.find(c=>c.code===selectedCollection)?.title} · 当前范围 {exportStatus?.current_count||0} 题</p>
          <button className="button primary export-panel-action" disabled={exportScope.kind==='selected'&&!exportScope.question_ids?.length} onClick={exportAll}>生成当前集合 PDF</button>
          <h3>编译状态</h3>
          <div className={`status-card status-${exportStatus?.state || 'idle'}`}>
            {(exportStatus?.state === 'pending' || exportStatus?.state === 'building') ? <LoaderCircle className="spin" size={19} /> : <RefreshCw size={19} />}
            <div><b>{exportStatus?.message || '未知'}</b><small>当前 {catalog?.collections.find(item => item.code === selectedCollection)?.count || 0} 道题 · 已导出 {exportStatus?.count || 0} 道</small></div>
          </div>
          {exportStatus?.error && <div className="export-error">{exportStatus.error}</div>}
          <p>每次只导出当前题库的指定范围，题号从 1 开始，其他题库的结果不会被覆盖。</p>
          {exportStatus?.stale && <p className="stale-note">导出尚未生成或已过期，请导出当前集合更新。</p>}
          <div className="export-files">
          <button className="download-link" disabled={!exportStatus?.available} onClick={() => exportFile('question', 'open')}><FileText size={17} />打开题目册</button>
          <button className="download-link" disabled={!exportStatus?.available} onClick={() => exportFile('solution', 'open')}><BookOpen size={17} />打开解析册</button>
          <button className="download-link" disabled={!exportStatus?.available} onClick={() => exportFile('question', 'save')}>题目册另存为…</button>
          <button className="download-link" disabled={!exportStatus?.available} onClick={() => exportFile('solution', 'save')}>解析册另存为…</button>
          <button className="download-link" onClick={() => window.desktop?.openFolder('output', selectedCollection,exportStatus?.key)}>打开导出目录</button>
          </div>
  </>

  if (loading) return <div className="loading-screen"><LoaderCircle className="spin" /><span>正在载入题库…</span></div>

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="icon-button mobile-only" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button>
        <div className="brand"><span className="brand-mark">∑</span><div><b>高中数学题库</b><small>{catalog?.bank_name} · {catalog?.total || 0} 道题</small></div></div>
        <label className="check"><input type="checkbox" checked={allBanks} onChange={e=>setAllBanks(e.target.checked)}/>全部题库搜索</label><div className="search-box"><Search size={18} /><input placeholder="搜索题号、题型、题干或题源" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="toolbar-actions">
          <button className="button ghost" onClick={() => setSettingsOpen(true)}>设置</button>
          <button className="button ghost" disabled={!catalog} onClick={() => setAiOpen(true)}>AI 录题</button>
          <button className="button ghost" disabled={actionBusy} onClick={() => openEditor(null)}><Plus size={17} />增加题目</button>
          <button className="button ghost" disabled={!ready} onClick={() => openEditor(question)}><Pencil size={16} />修改</button>
          <button className="button danger" disabled={!ready} onClick={remove}><Trash2 size={16} />永久删除</button>
          <button className="button ghost" onClick={openDrafts}>草稿箱</button>
          <button className="button ghost pool-toolbar" onClick={() => setPoolOpen(true)}>组卷区 {pool?.count || 0}/100</button>
          <button className="button ghost narrow-export" onClick={() => setExportOpen(true)}>导出文件</button>
          <button className="button primary" onClick={exportAll}><Download size={17} />导出当前集合</button>
        </div>
      </header>

      <main className="workspace">
        <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
          <div className="bank-picker"><label>当前题库<select aria-label="当前题库" value={bankId} disabled={editing!==null||aiOpen||actionBusy||poolBusy} onChange={e=>switchBank(e.target.value)}>{banks.map(b=><option key={b.id} value={b.id}>{b.name}（{b.count||0}题）</option>)}</select></label><button className="button ghost compact" onClick={()=>setBankOpen(true)}>新建 / 管理题库</button></div>
          <div className="sidebar-heading"><div><span className="eyebrow">题库集合</span><h2>选择学期</h2></div><button className="icon-button mobile-only" onClick={() => setSidebarOpen(false)}><X size={18} /></button></div>
          <nav className="collection-list" aria-label="题库集合">
            {collectionList(catalog).map(item => <button key={item.code} aria-current={item.code === selectedCollection ? 'true' : undefined}
              className={`collection-button ${item.code === selectedCollection ? 'active' : ''}`} onClick={() => chooseCollection(item.code)}>
              <span>{item.title}</span><em>{item.count}</em><small>{item.material}</small>
            </button>)}
          </nav>
          <div className="tree">
            {search.trim() ? <div className="search-results"><p role="status">{searchStatus}</p>{searchResults.map(item =>
              <div className="pool-row" key={item.id}><input type="checkbox" aria-label={`将搜索结果第 ${item.local_number} 题加入组卷区`} checked={checkedPoolIds.has(item.id)} disabled={poolBusy || item.bank_id!==bankId} onChange={() => togglePool(item.id)} /><button className={`search-result ${selectedId === item.id ? 'active' : ''}`} onClick={() => {if(item.bank_id && item.bank_id!==bankId){switchBank(item.bank_id,{id:item.id,collection:item.collection_code})}else chooseQuestion(item.id,item.topic_code,item.point_code,item.collection_code)}}>
                <b>第 {item.local_number} 题 · {item.type_name}</b><small>{item.bank_name} / {item.collection_title} / {item.topic_title} / {item.point_title}</small><span>{item.snippet}</span>
              </button></div>)}</div> : catalog?.collections.find(collection => collection.code === selectedCollection)?.topics.map((topic) => {
              const topicOpen = openTopics.has(topic.code)
              return <div className="topic-node" key={topic.code}>
                <button className="tree-heading topic-heading" onClick={() => toggleSet(setOpenTopics, openTopics, topic.code)}>
                  {topicOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span>{topic.title}</span><em>{topic.count}</em>
                </button>
                {topicOpen && <div className="point-list">{topic.points.map((point) => {
                  const pointOpen = openPoints.has(point.code)
                  const filtered = point.questions.filter((item) => {
                    const needle = search.trim().toLowerCase()
                    return !needle || `${item.local_number} ${item.type_name} ${item.preview}`.toLowerCase().includes(needle)
                  })
                  return <div className="point-node" key={point.code}>
                    <button className="tree-heading point-heading" onClick={() => toggleSet(setOpenPoints, openPoints, point.code)}>
                      {pointOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      <span>{point.title}</span><em>{point.count}</em>
                    </button>
                    {pointOpen && <div className="question-list">
                      {filtered.map((item) => <div className="pool-row" key={item.id}><input type="checkbox" aria-label={`将第 ${item.local_number} 题加入组卷区`} checked={checkedPoolIds.has(item.id)} disabled={poolBusy || item.bank_id!==bankId} onChange={() => togglePool(item.id)} /><button className={`question-row ${selectedId === item.id ? 'active' : ''}`}
                        onClick={() => chooseQuestion(item.id, topic.code, point.code)}>
                        <span className="number">{item.local_number}</span>
                        <span className={`type type-${item.type}`}>{item.type_name}</span>
                        <span className="summary">{item.preview}</span>
                      </button></div>)}
                      {!filtered.length && <div className="no-results">{search ? '没有匹配题目' : '暂无题目'}</div>}
                    </div>}
                  </div>
                })}</div>}
              </div>
            })}
          </div>
        </aside>

        <section className="content">
          {notice && <div className="notice"><CircleAlert size={17} /><span>{notice}</span><button onClick={() => setNotice('')}><X size={15} /></button></div>}
          {question && question.id === selectedId && question.collection_code === selectedCollection && question.bank_id === bankId && !questionLoading && selectedMeta ? <>
            <div className="question-header">
              <div><span className="breadcrumb">{catalog?.bank_name} / {catalog?.collections.find(item => item.code === selectedCollection)?.title} / {selectedMeta.topic.title} / {selectedMeta.point.title}</span><h1>第 {question.position} 题 <span className={`type type-${question.type}`}>{TYPE_LABELS[question.type]}</span></h1></div>
              <div className="version">内部 ID：{question.legacy_uid || question.id.slice(0, 8)} · 版本 {question.revision}</div>
            </div>
            <div className="tabs">
              <button className={tab === 'question' ? 'active' : ''} onClick={() => setTab('question')}><BookOpen size={17} />题目预览</button>
              <button className={tab === 'solution' ? 'active' : ''} onClick={() => setTab('solution')}><FileText size={17} />答案解析</button>
              <button className={tab === 'latex' ? 'active' : ''} onClick={() => setTab('latex')}><FileCode2 size={17} />LaTeX 源码</button>
              <button className={tab === 'source' ? 'active' : ''} onClick={() => setTab('source')}><Search size={17} />来源信息</button>
            </div>
            <div className="viewer-card">
              {(tab === 'question' || tab === 'solution') && <PdfViewer title={tab === 'question' ? '题目预览' : '答案解析'}
                src={`/api/questions/${question.id}/pdf?view=${tab}&revision=${question.revision}&catalog_revision=${catalog?.revision}`} />}
              {tab === 'latex' && <div className="source-panels" tabIndex={0} aria-label="源码与题源滚动区">
                <section><h3>题干</h3><pre>{question.question_tex}</pre></section>
                {question.options.length > 0 && <section><h3>选项</h3><pre>{question.options.map((value, i) => `${String.fromCharCode(65 + i)}. ${value}`).join('\n')}</pre></section>}
                <section><h3>答案</h3><pre>{question.answer_tex || '（答案写在解析中）'}</pre></section>
                <section><h3>解析</h3><pre>{question.solution_tex}</pre></section>
              </div>}
              {tab === 'source' && <div className="source-panels" tabIndex={0} aria-label="源码与题源滚动区"><section><h3>题源信息</h3><div className="origin-list">{question.sources.origins?.length ? question.sources.origins.map((origin, index) => <div className="origin-item" key={`${origin.title}-${index}`}><b>{originText(origin)}</b></div>) : <p className="empty-origin">题源暂缺</p>}</div></section><section className="meta-grid"><span>考点</span><b>{question.point_code}</b><span>考点内题号</span><b>{question.position}</b><span>核验状态</span><b>{question.verified ? '已核验' : '待核验'}</b><span>更新时间</span><b>{question.updated_at}</b></section></div>}
            </div>
          </> : <div className="welcome"><BookOpen size={48} /><h1>{questionLoading ? '正在加载题目…' : '选择一道题目'}</h1><p>从左侧依次展开专题和考点，然后点击题号查看 LaTeX 排版结果。</p></div>}
        </section>

        <aside className="export-panel">
          {exportControls}
        </aside>
      </main>
      {bankOpen && catalog && <BankManager banks={banks} catalog={catalog} onClose={()=>setBankOpen(false)} onChanged={async id=>{setBanks(await api.banks());if(id&&id!==bankId)switchBank(id);else await loadCatalog()}} />}
      {editing && catalog && <Editor key={editing.key} catalog={catalog} defaultCollection={selectedCollection} initial={editing.initial} draft={editing.draft} onClose={() => setEditing(null)} onSaved={saved}
        onRefreshCatalog={async () => { const refreshed = await api.catalog(); setCatalog(refreshed); return refreshed }} />}
      {exportOpen && <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label="导出文件"><section className="utility-panel export-dialog"><button className="icon-button utility-close" aria-label="关闭导出文件" onClick={() => setExportOpen(false)}><X /></button>{exportControls}</section></div>}
      {poolOpen && <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label="组卷区"><section className="utility-panel pool-dialog">
        <header><div><span className="eyebrow">训练卷</span><h2>组卷区 {pool?.count || 0}/100</h2></div><button className="icon-button" aria-label="关闭组卷区" onClick={() => setPoolOpen(false)}><X /></button></header>
        <p>勾选 1–20 道题生成训练卷；手动卷按加入顺序排列。随机组卷从全部候选题中抽取。</p>
        <div className="pool-items">{pool?.items.map(item => <label className="pool-item" key={item.id}><input type="checkbox" checked={poolSelected.has(item.id)} onChange={() => setPoolSelected(current => { const next = new Set(current); next.has(item.id) ? next.delete(item.id) : next.add(item.id); return next })} /><span><b>{catalog?.collections.find(c => c.code === item.collection_code)?.title} · {item.point_code} · 第 {item.position} 题</b><small>{item.preview}</small></span><button className="button ghost" disabled={poolBusy} onClick={event => { event.preventDefault(); togglePool(item.id) }}>移除</button></label>)}
          {!pool?.count && <p>组卷区暂无题目。可在目录或搜索结果旁勾选题目。</p>}
        </div>
        <div className="pool-actions"><button className="button ghost" disabled={poolBusy || !poolSelected.size} onClick={removePoolSelected}>批量移除已选</button><button className="button ghost" disabled={poolBusy || !pool?.can_undo} onClick={undoPool}>撤销最近一次移除{pool?.can_undo ? `（${pool.undo_count}题）` : ''}</button></div>
        <div className="pool-actions"><button className="button primary" disabled={poolBusy || poolSelected.size < 1 || poolSelected.size > 20} onClick={() => createPaper('manual')}>按已选题生成双卷（{poolSelected.size}/20）</button><label>随机题数 <input aria-label="随机题数" type="number" min={1} max={Math.min(20, pool?.count || 0)} value={randomCount} onChange={event => setRandomCount(Number(event.target.value))} /></label><button className="button primary" disabled={poolBusy || !pool?.count || randomCount < 1 || randomCount > Math.min(20, pool?.count || 0)} onClick={() => createPaper('random')}>随机组卷</button></div>
        <div className={`status-card status-${paperStatus?.state || 'idle'}`}><RefreshCw size={18} /><div><b>{paperStatus?.message || '尚未生成训练卷'}</b><small>{paperStatus?.available ? `最近成功：${paperStatus.generated_at} · ${paperStatus.count} 题` : '暂无成功版本'}</small></div></div>
        {paperStatus?.error && <div className="export-error">{paperStatus.error}</div>}
        <div className="pool-files"><button className="download-link" disabled={!paperStatus?.available} onClick={() => paperFile('question', 'open')}>打开题目卷</button><button className="download-link" disabled={!paperStatus?.available} onClick={() => paperFile('solution', 'open')}>打开解析卷</button><button className="download-link" disabled={!paperStatus?.available} onClick={() => paperFile('question', 'save')}>题目卷另存为…</button><button className="download-link" disabled={!paperStatus?.available} onClick={() => paperFile('solution', 'save')}>解析卷另存为…</button><button className="download-link" onClick={() => window.desktop?.openFolder('papers')}>打开训练卷目录</button></div>
      </section></div>}
      {drafts && <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label="草稿箱"><section className="utility-panel draft-list"><header><h2>草稿箱</h2><button className="icon-button" aria-label="关闭草稿箱" onClick={() => setDrafts(null)}><X /></button></header>
        <p>草稿不会进入正式题库或导出。共 {drafts.length} 份。</p>
        {drafts.map(draft => <article key={draft.id}><b>{draft.content.form.question_tex.trim().slice(0, 70) || '未命名草稿'}</b><small>{catalog?.collections.find(item => item.code === draft.content.form.collection_code)?.title} · {draft.source_question_id ? '修改已有题目' : '新建题目'} · {new Date(draft.updated_at).toLocaleString()}</small><div className="form-actions"><button className="button primary" onClick={() => openEditor(null, draft)}>继续编辑</button><button className="button ghost" onClick={() => discardFromList(draft)}>丢弃</button></div></article>)}
      </section></div>}
      {aiOpen && catalog && <AIWorkbench catalog={catalog} onClose={() => setAiOpen(false)} onSettings={() => setSettingsOpen(true)} onPublished={async () => { await loadCatalog(); setNotice('AI 候选题已入库，相关集合导出已过期。') }} onOpenQuestion={async id => { const q = await api.question(id); if(q.bank_id&&q.bank_id!==bankRef.current){setAiOpen(false);switchBank(q.bank_id,{id:q.id,collection:q.collection_code},true);return} const updated = await api.catalog(); setCatalog(updated); const collection = updated.collections.find(c => c.code === q.collection_code); const topic = collection?.topics.find(t => t.points.some(p => p.code === q.point_code)); chooseQuestion(id, topic?.code || '', q.point_code, q.collection_code); setAiOpen(false) }} />}
      {settingsOpen && <DesktopSettings onClose={() => setSettingsOpen(false)} />}
    </div>
  )
}
