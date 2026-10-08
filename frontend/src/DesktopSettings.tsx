import { useEffect, useState } from 'react'
import DialogFrame from './DialogFrame'
import AISettings from './AISettings'
export type LatexStatus = { path: string; configured_path: string; available: boolean; message: string }

async function request(url: string, method = 'GET', body?: object) {
  const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || '操作失败')
  return data
}

export default function DesktopSettings({ onClose }: { onClose: () => void }) {
  const [info,setInfo]=useState<{version:string;program_directory:string;data_directory:string}|null>(null)
  const [path, setPath] = useState('')
  const [message, setMessage] = useState('正在检测 LaTeX…')
  const [busy, setBusy] = useState(false)
  useEffect(() => { void window.desktop?.appInfo().then(setInfo).catch(()=>{}); request('/api/desktop/latex').then((status: LatexStatus) => { setPath(status.configured_path); setMessage(status.message + (status.path ? `：${status.path}` : '')) }).catch(err => setMessage(err.message)) }, [])
  const save = async (test: boolean) => {
    setBusy(true)
    try {
      const result: LatexStatus = await request('/api/desktop/latex', 'PUT', { path })
      setMessage(result.message)
      if (test) { setMessage('正在进行真实编译测试…'); const result = await request('/api/desktop/latex/test', 'POST'); setMessage(result.message) }
    } catch (err) { setMessage(err instanceof Error ? err.message : '设置失败') }
    finally { setBusy(false) }
  }
  return <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label="桌面设置"><DialogFrame className="settings-panel" title="桌面设置" closeLabel="关闭设置" onClose={onClose}>
    {info&&<section className="installation-info" aria-label="程序与数据位置"><h3>程序与数据位置</h3><dl><dt>实际程序版本</dt><dd>{info.version}</dd><dt>当前程序目录</dt><dd>{info.program_directory}</dd><dt>当前数据目录</dt><dd>{info.data_directory}</dd></dl></section>}
    <label>XeLaTeX 路径<input value={path} placeholder="留空则从系统 PATH 自动检测" onChange={e => setPath(e.target.value)} /></label>
    <p>使用电脑已经安装的 LaTeX。可选择 xelatex.exe，并测试中文字体和排版宏包是否齐全。</p>
    <div className="form-actions"><button className="button ghost" disabled={busy} onClick={async () => { const selected = await window.desktop?.chooseLatex(); if (selected) setPath(selected) }}>选择文件</button><button className="button ghost" disabled={busy} onClick={() => { setPath(''); setMessage('点击保存，使用系统 PATH 中的 XeLaTeX。') }}>自动检测</button></div>
    <div role="status" className="settings-status">{message}</div>
    <div className="form-actions"><button className="button ghost" disabled={busy} onClick={() => save(false)}>保存设置</button><button className="button primary" disabled={busy} onClick={() => save(true)}>{busy ? '检测中…' : '保存并测试编译'}</button></div>
    <AISettings />
    <footer><button className="button ghost" onClick={() => window.desktop?.openFolder('data')}>打开数据目录</button><button className="button ghost" onClick={() => window.desktop?.openFolder('logs')}>打开日志目录</button></footer>
  </DialogFrame></div>
}
