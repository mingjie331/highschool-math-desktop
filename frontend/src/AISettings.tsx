import { useEffect, useState } from 'react'
import { agentApi } from './agentApi'
import type { AIConfigStatus } from './agentTypes'

export default function AISettings() {
  const [status, setStatus] = useState<AIConfigStatus | null>(null)
  const [key, setKey] = useState('')
  const [prices, setPrices] = useState<Record<string, number>>({ input: 2, cached_input: .04, output: 8 })
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = async () => {
    const value = window.desktop ? await window.desktop.agentStatus() : await agentApi.config()
    setStatus(value); setPrices(value.prices); if (value.credential_warning) setMessage(value.credential_warning)
  }
  useEffect(() => { void refresh().catch(error => setMessage(error.message)) }, [])
  const action = async (kind: 'save' | 'clear' | 'test') => {
    setBusy(true); setMessage('处理中…')
    try {
      if (kind === 'save') {
        if (!window.desktop) throw new Error('请在桌面应用中加密保存密钥')
        setStatus(await window.desktop.saveAgentKey(key, prices)); setKey(''); setMessage('密钥已加密保存。可以测试连接。')
      } else if (kind === 'clear') {
        if (!window.desktop) throw new Error('请在桌面应用中清除密钥')
        setStatus(await window.desktop.clearAgentKey()); setKey(''); setMessage('DeepSeek 密钥已清除。')
      } else { const value = await agentApi.test(); setMessage(value.message) }
    } catch (error) { setMessage(error instanceof Error ? error.message : 'DeepSeek 设置失败') }
    finally { setBusy(false) }
  }
  return <section className="ai-settings" aria-label="DeepSeek 配置">
    <h3>DeepSeek 配置 <span className="ai-config-state">{status?.configured ? '已配置' : '未配置'}</span></h3>
    <p>官方接口 · deepseek-flash。AI 识别需要联网，所选题目图片会发送给 DeepSeek；普通题库功能继续离线可用。</p>
    <label>DeepSeek API Key<input type="password" autoComplete="off" spellCheck={false} value={key} onChange={event => setKey(event.target.value)} placeholder="输入新密钥，已保存密钥不会回显" /></label>
    <small>密钥由 Windows 账户加密保存；换电脑或账户后可能需要重新输入。不会写入题库、聊天记录或日志。</small>
    <details><summary>费用参考单价（元／百万 token）</summary><div className="field-row three">
      {(['input', 'cached_input', 'output'] as const).map((name, index) => <label key={name}>{['输入', '缓存命中输入', '输出'][index]}<input type="number" min={0} step="0.01" value={prices[name]} onChange={event => setPrices(current => ({ ...current, [name]: Number(event.target.value) }))} /></label>)}
    </div><p>默认为高峰参考价，可按官网修改；保存配置时输入密钥。费用估计以实际 token 为依据，最终以官方账单为准。</p></details>
    <div className="form-actions"><button className="button primary" disabled={busy || !key.trim()} onClick={() => action('save')}>加密保存密钥</button>
      <button className="button ghost" disabled={busy || !status?.configured} onClick={() => action('test')}>测试 DeepSeek 连接</button>
      <button className="button danger" disabled={busy || !status?.configured} onClick={() => action('clear')}>清除密钥</button></div>
    <p role="status">{message}</p>
  </section>
}
