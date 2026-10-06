const fs = require('node:fs/promises')
const path = require('node:path')
const crypto = require('node:crypto')

// Never expose decrypted configuration to the renderer or write it to settings.json.
function agentSecrets(home, safeStorage) {
  const file = path.join(home, 'data', 'deepseek.credentials.enc')
  let warning = ''
  return {
    warning: () => warning,
    async load() {
      try {
        const encrypted = await fs.readFile(file)
        if (!(await safeStorage.isAsyncEncryptionAvailable())) throw new Error('unavailable')
        const value = await safeStorage.decryptStringAsync(encrypted)
        const parsed = JSON.parse(value.result)
        if (typeof parsed.api_key !== 'string' || parsed.api_key.length > 512) throw new Error('invalid')
        warning = ''
        return parsed
      } catch (error) {
        if (error.code !== 'ENOENT') warning = '本机无法解密 DeepSeek 配置，请重新输入密钥；题库数据不受影响。'
        return null
      }
    },
    async save(api_key, prices) {
      if (typeof api_key !== 'string' || !api_key.trim() || api_key.length > 512 || /[\r\n]/.test(api_key) || /[^\x21-\x7e]/.test(api_key.trim())) throw new Error('API Key 格式无效')
      if (!(await safeStorage.isAsyncEncryptionAvailable())) throw new Error('系统加密暂不可用，密钥未保存，请稍后重试。')
      const encrypted = await safeStorage.encryptStringAsync(JSON.stringify({ api_key: api_key.trim(), prices }))
      await fs.mkdir(path.dirname(file), { recursive: true })
      const temporary = file + '.' + crypto.randomUUID() + '.tmp'
      try { await fs.writeFile(temporary, encrypted); await fs.rename(temporary, file) }
      finally { await fs.rm(temporary, { force: true }) }
      warning = ''
    },
    async clear() { await fs.rm(file, { force: true }); warning = '' },
  }
}
module.exports = { agentSecrets }
