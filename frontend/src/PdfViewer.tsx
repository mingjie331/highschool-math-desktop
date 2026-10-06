import { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfViewer({ src, title }: { src: string; title: string }) {
  const pagesRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(600)
  const [status, setStatus] = useState('正在载入 PDF…')
  const [error, setError] = useState('')
  useEffect(() => {
    const target = pagesRef.current
    if (!target) return
    const observer = new ResizeObserver(entries => setWidth(Math.max(220, entries[0].contentRect.width - 32)))
    observer.observe(target)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let cancelled = false
    let task: ReturnType<typeof getDocument> | undefined
    const abort = new AbortController()
    const target = pagesRef.current
    setStatus('正在载入 PDF…')
    setError('')
    target?.replaceChildren()
    ;(async () => {
      try {
        const response = await fetch(src, { signal: abort.signal })
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}))
          throw new Error(detail.detail || 'PDF 载入失败')
        }
        const data = await response.arrayBuffer()
        if (cancelled) return
        task = getDocument({ data, cMapUrl: '/pdfjs/cmaps/', cMapPacked: true, standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/' })
        const pdf = await task.promise
        for (let number = 1; number <= pdf.numPages; number++) {
          if (cancelled) return
          const page = await pdf.getPage(number)
          const base = page.getViewport({ scale: 1 })
          const scale = width / base.width * zoom
          const ratio = window.devicePixelRatio || 1
          const viewport = page.getViewport({ scale: scale * ratio })
          const canvas = document.createElement('canvas')
          canvas.setAttribute('aria-label', `${title} 第 ${number} 页`)
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          canvas.style.width = `${viewport.width / ratio}px`
          canvas.style.height = `${viewport.height / ratio}px`
          if (cancelled) return
          target?.append(canvas)
          await page.render({ canvas, viewport }).promise
        }
        if (!cancelled) setStatus(`共 ${pdf.numPages} 页`)
      } catch (err) {
        if (!cancelled) { setError(err instanceof Error ? err.message : 'PDF 载入失败'); setStatus('') }
      }
    })()
    return () => { cancelled = true; abort.abort(); void task?.destroy() }
  }, [src, title, zoom, width])
  return <div className="pdf-viewer" aria-label={title}>
    <div className="pdf-toolbar"><span>{status}</span><div><button aria-label="缩小" disabled={zoom <= .6} onClick={() => setZoom(value => Math.max(.6, value - .2))}>−</button><span>{Math.round(zoom * 100)}%</span><button aria-label="放大" disabled={zoom >= 2} onClick={() => setZoom(value => Math.min(2, value + .2))}>＋</button></div></div>
    {error && <div className="pdf-error" role="alert">{error}</div>}
    <div className="pdf-pages" ref={pagesRef} />
  </div>
}
