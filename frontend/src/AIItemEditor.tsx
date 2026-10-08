import { useEffect, useRef, useState } from 'react'
import DialogFrame from './DialogFrame'
import { agentApi } from './agentApi'
import type { AIImportItem } from './agentTypes'
import type { Catalog, QuestionPayload, QuestionType } from './types'

export default function AIItemEditor({ item, catalog, onSaved, onClose }: {
  item: AIImportItem; catalog: Catalog; onSaved: () => Promise<void>; onClose: () => void;
}) {
  const [form, setForm] = useState<QuestionPayload>(structuredClone(item.form))
  const [uncertainties, setUncertainties] = useState(item.details.uncertainties.join('\n'))
  const [classificationUncertain, setClassificationUncertain] = useState(item.details.classification_uncertain)
  const [answerConflict, setAnswerConflict] = useState(item.details.answer_conflict)
  const [allowDuplicate, setAllowDuplicate] = useState(item.details.allow_duplicate)
  const [figuresConfirmed, setFiguresConfirmed] = useState(item.details.figures_confirmed ?? !item.details.figures.length)
  const [originalNumber, setOriginalNumber] = useState(item.details.original_number)
  const [message, setMessage] = useState('修改后自动保存，校验通过后可入库')
  const [busy, setBusy] = useState(false)
  const remote = useRef(item)
  const latest = useRef({ form, uncertainties, classificationUncertain, answerConflict, allowDuplicate, figuresConfirmed, originalNumber })
  latest.current = { form, uncertainties, classificationUncertain, answerConflict, allowDuplicate, figuresConfirmed, originalNumber }
  const encoded = JSON.stringify(latest.current)
  const saved = useRef(encoded)
  const pending = useRef<Promise<void> | null>(null)
  const alive = useRef(true)
  const report = (value: string) => { if (alive.current) setMessage(value) }
  const flush = () => {
    if (pending.current) return pending.current
    pending.current = (async () => {
      while (JSON.stringify(latest.current) !== saved.current) {
        const snapshot = structuredClone(latest.current); const signature = JSON.stringify(snapshot)
        report('正在保存候选草稿…')
        const changes = { form: snapshot.form, uncertainties: snapshot.uncertainties.split('\n').map(value => value.trim()).filter(Boolean), classification_uncertain: snapshot.classificationUncertain, answer_conflict: snapshot.answerConflict, allow_duplicate: snapshot.allowDuplicate, figures_confirmed: snapshot.figuresConfirmed, original_number: snapshot.originalNumber }
        const expected = remote.current
        try { remote.current = await agentApi.update(expected, changes) }
        catch (error) {
          const actual = await agentApi.item(item.id).catch(() => null)
          const same = actual && actual.revision === expected.revision + 1 && ['question_tex', 'answer_tex', 'solution_tex', 'type', 'collection_code', 'point_code', 'options'].every(key => JSON.stringify(actual.form[key as keyof QuestionPayload]) === JSON.stringify(snapshot.form[key as keyof QuestionPayload]))
            && JSON.stringify(actual.details.uncertainties) === JSON.stringify(changes.uncertainties) && actual.details.classification_uncertain === changes.classification_uncertain && actual.details.answer_conflict === changes.answer_conflict && actual.details.allow_duplicate === changes.allow_duplicate
            && actual.details.figures_confirmed === changes.figures_confirmed && actual.details.original_number === changes.original_number
          if (!same) throw error
          remote.current = actual!
        }
        saved.current = signature; report('候选草稿已保存')
      }
    })().catch(error => { report(error instanceof Error ? error.message : '保存失败'); throw error }).finally(() => { pending.current = null })
    return pending.current
  }
  const flushRef = useRef(flush); flushRef.current = flush
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { if (encoded === saved.current) return; const timer = window.setTimeout(() => void flushRef.current().catch(() => {}), 1000); return () => window.clearTimeout(timer) }, [encoded])
  useEffect(() => window.desktop?.onPrepareClose(async () => { setBusy(true); try { await flushRef.current() } finally { setBusy(false) } }), [])
  useEffect(() => { const before = (event: BeforeUnloadEvent) => { if (JSON.stringify(latest.current) !== saved.current) { event.preventDefault(); event.returnValue = '' } }; window.addEventListener('beforeunload', before); return () => window.removeEventListener('beforeunload', before) }, [])
  const finish = async (validate: boolean) => {
    setBusy(true)
    try { await flushRef.current(); if (validate) remote.current = await agentApi.validate(item.id); await onSaved(); if (!validate) onClose(); else report(remote.current.state === 'ready' ? '校验通过，可关闭后勾选入库。' : remote.current.details.validation_error || '仍有待核对的提示。') }
    catch (error) { report(error instanceof Error ? error.message : '操作失败') }
    finally { setBusy(false) }
  }
  const collection = catalog.collections.find(value => value.code === form.collection_code)
  return <div className="ai-subdialog" role="dialog" aria-modal="true" aria-label="修改 AI 候选题"><DialogFrame className="ai-edit-panel" title={`修改候选题 ${item.item_order}`} closeLabel="保存关闭候选题" closeDisabled={busy} onClose={() => {void finish(false)}} footer={<><span role="status">{message}</span><div className="form-actions"><button className="button ghost" disabled={busy} onClick={() => finish(false)}>保存并关闭</button><button className="button primary" disabled={busy} onClick={() => finish(true)}>保存并校验</button></div></>}>
    <fieldset disabled={busy}>
      <label>原题号<input aria-label="原题号" value={originalNumber} onChange={event => setOriginalNumber(event.target.value)} /></label>
      <div className="field-row three"><label>题库集合<select value={form.collection_code} onChange={event => { const c = catalog.collections.find(value => value.code === event.target.value)!; setForm(current => ({ ...current, collection_code: c.code, point_code: c.topics[0]?.points[0]?.code || '' })); setClassificationUncertain(false) }}>{catalog.collections.map(value => <option key={value.code} value={value.code}>{value.title}</option>)}</select></label>
      <label>知识点<select value={form.point_code} onChange={event => { setForm(current => ({ ...current, point_code: event.target.value })); setClassificationUncertain(false) }}>{!collection?.topics.some(topic => topic.points.some(point => point.code === form.point_code)) && <option value={form.point_code}>请选择有效考点</option>}{collection?.topics.map(topic => <optgroup key={topic.code} label={topic.title}>{topic.points.map(point => <option key={point.code} value={point.code}>{point.title}</option>)}</optgroup>)}</select></label>
      <label>题型<select value={form.type} onChange={event => { const type = event.target.value as QuestionType; setForm(current => ({ ...current, type, options: type === 'single' || type === 'multi' ? current.options.length === 4 ? current.options : ['', '', '', ''] : [] })) }}><option value="single">单选</option><option value="multi">多选</option><option value="fill">填空</option><option value="long">解答</option></select></label></div>
      <label>候选题干 LaTeX<textarea rows={5} value={form.question_tex} onChange={event => setForm(current => ({ ...current, question_tex: event.target.value }))} /></label>
      {(form.type === 'single' || form.type === 'multi') && <div className="options-grid">{['A', 'B', 'C', 'D'].map((letter, index) => <label key={letter}>选项 {letter}<textarea value={form.options[index] || ''} onChange={event => setForm(current => ({ ...current, options: Array.from({ length: 4 }, (_, i) => i === index ? event.target.value : current.options[i] || '') }))} /></label>)}</div>}
      <label>候选答案 LaTeX<textarea rows={2} value={form.answer_tex} onChange={event => setForm(current => ({ ...current, answer_tex: event.target.value }))} /></label>
      <label>候选解析 LaTeX<textarea rows={6} value={form.solution_tex} onChange={event => setForm(current => ({ ...current, solution_tex: event.target.value }))} /></label>
      <label>待核对问题（每行一项；修正后移除）<textarea rows={2} value={uncertainties} onChange={event => setUncertainties(event.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={classificationUncertain} onChange={event => setClassificationUncertain(event.target.checked)} />分类尚未确认</label>
      <label className="check"><input type="checkbox" checked={answerConflict} onChange={event => setAnswerConflict(event.target.checked)} />原答案与 AI 答案冲突尚未处理</label>
      {!!item.details.figures.length && <label className="check"><input type="checkbox" checked={figuresConfirmed} onChange={event => setFiguresConfirmed(event.target.checked)} />已对照原页核对所有题干图、解析图，裁剪完整</label>}
      {!!item.details.duplicates.length && <label className="check"><input type="checkbox" checked={allowDuplicate} onChange={event => setAllowDuplicate(event.target.checked)} />已核对重复候选，仍保留为新题</label>}
    </fieldset>
  </DialogFrame></div>
}
