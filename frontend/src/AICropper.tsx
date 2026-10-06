import { useRef, useState } from 'react'
import type { AIAttachment, AIRegion } from './agentTypes'

export default function AICropper({ attachments, initial, mode, initialField, onApply, onClose }: {
  attachments: AIAttachment[]; initial: AIRegion[]; mode: 'question' | 'figure' | 'split';
  onApply: (regions: AIRegion[], field: string) => Promise<void>; onClose: () => void;
  initialField?: string;
}) {
  const [regions, setRegions] = useState<AIRegion[]>(mode === 'question' || initialField ? structuredClone(initial) : [])
  const [imageId, setImageId] = useState(initial[0]?.image_id || attachments[0]?.id || '')
  const [selected, setSelected] = useState<number | null>((mode === 'question' || initialField) && initial.length ? 0 : null)
  const [drawing, setDrawing] = useState<AIRegion['rect'] | null>(null)
  const [field, setField] = useState(initialField || 'question_tex')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const start = useRef<[number, number] | null>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const point = (event: React.PointerEvent) => {
    const box = imageRef.current!.getBoundingClientRect()
    return [Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)), Math.max(0, Math.min(1, (event.clientY - box.top) / box.height))] as [number, number]
  }
  const selectedRegion = selected === null ? null : regions[selected]
  const shown = drawing || (selectedRegion?.image_id === imageId ? selectedRegion.rect : null)
  const apply = async () => {
    setBusy(true)
    try {
      if (!regions.length || (mode === 'split' && regions.length < 2)) throw new Error(mode === 'split' ? '请至少框出两个题目区域' : '请先框出区域')
      if (mode === 'figure' && regions.length !== 1) throw new Error('每次添加一张配图，请保留一个区域')
      await onApply(regions, field); onClose()
    } catch (error) { setMessage(error instanceof Error ? error.message : '裁剪失败') }
    finally { setBusy(false) }
  }
  return <div className="ai-subdialog" role="dialog" aria-modal="true" aria-label="图片裁剪">
    <section className="ai-crop-panel"><header><h3>{mode === 'figure' ? '裁剪配图' : mode === 'split' ? '拆分题目区域' : '调整题目区域'}</h3><button className="icon-button" disabled={busy} onClick={onClose} aria-label="关闭裁剪">×</button></header>
      <p>在原图上拖动框选。点击“新增区域”可继续框选；点击已有区域可调整。跨图题可添加多张图的区域。</p>
      <div className="ai-crop-layout"><aside>
        <label>原图<select aria-label="裁剪原图" value={imageId} onChange={event => { setImageId(event.target.value); setSelected(null) }}>{attachments.map(image => <option key={image.id} value={image.id}>{image.filename}{image.document_id ? ` · 第 ${image.page_number} 页` : ""}</option>)}</select></label>
        <button className="button ghost" onClick={() => { setSelected(null); setDrawing(null) }}>新增区域</button>
        {regions.map((region, index) => <div className="ai-region-row" key={index}><button className={selected === index ? 'active' : ''} onClick={() => { setSelected(index); setImageId(region.image_id) }}>区域 {index + 1} · {attachments.find(image => image.id === region.image_id)?.filename}</button><button aria-label={`删除区域 ${index + 1}`} onClick={() => { setRegions(current => current.filter((_, i) => i !== index)); setSelected(null) }}>×</button></div>)}
        {selectedRegion && <div className="ai-coordinate-fields">{selectedRegion.rect.map((value, index) => <label key={index}>{['左', '上', '右', '下'][index]}<input aria-label={`区域${['左', '上', '右', '下'][index]}`} type="number" min={0} max={1} step="0.01" value={Number(value.toFixed(3))} onChange={event => setRegions(current => current.map((region, i) => i === selected ? { ...region, rect: region.rect.map((v, j) => j === index ? Number(event.target.value) : v) as AIRegion['rect'] } : region))} /></label>)}</div>}
        {mode === 'figure' && <label>插入位置<select value={field} onChange={event => setField(event.target.value)}><option value="question_tex">题干</option><option value="answer_tex">答案</option><option value="solution_tex">解析</option></select></label>}
      </aside><div className="ai-crop-scroll"><div className="ai-crop-image" onPointerDown={event => { if (!imageRef.current) return; event.currentTarget.setPointerCapture(event.pointerId); start.current = point(event); setDrawing(null) }}
        onPointerMove={event => { if (!start.current) return; const [x, y] = point(event); const [a, b] = start.current; setDrawing([Math.min(a, x), Math.min(b, y), Math.max(a, x), Math.max(b, y)]) }}
        onPointerUp={event => { if (!start.current) return; const [x, y] = point(event); const [a, b] = start.current; start.current = null; setDrawing(null); const rect: AIRegion['rect'] = [Math.min(a, x), Math.min(b, y), Math.max(a, x), Math.max(b, y)]; if (rect[2] - rect[0] < .005 || rect[3] - rect[1] < .005) return; const region = { image_id: imageId, rect, role: selectedRegion?.role }; if (selected === null) { setSelected(regions.length); setRegions(current => [...current, region]) } else setRegions(current => current.map((old, i) => i === selected ? region : old)) }}>
          <img ref={imageRef} draggable={false} src={attachments.find(image => image.id === imageId)?.url} alt="待框选原图" />
          {shown && <div className="ai-crop-box" style={{ left: `${shown[0] * 100}%`, top: `${shown[1] * 100}%`, width: `${(shown[2] - shown[0]) * 100}%`, height: `${(shown[3] - shown[1]) * 100}%` }} />}
        </div></div></div>
      <footer><span role="alert">{message}</span><button className="button primary" disabled={busy} onClick={apply}>{busy ? '保存中…' : mode === 'split' ? '拆为多个候选题' : mode === 'figure' ? '裁图并插入' : '保存题目区域'}</button></footer>
    </section>
  </div>
}
