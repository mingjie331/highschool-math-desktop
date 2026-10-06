const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { agentSecrets } = require('../desktop/agent-secrets.cjs')

function encryptor(key) {
  return {
    isAsyncEncryptionAvailable: async () => true,
    encryptStringAsync: async text => { const iv = crypto.randomBytes(12); const cipher = crypto.createCipheriv('aes-256-gcm', key, iv); const data = Buffer.concat([cipher.update(text, 'utf8'), cipher.final()]); return Buffer.concat([iv, cipher.getAuthTag(), data]) },
    decryptStringAsync: async bytes => { const cipher = crypto.createDecipheriv('aes-256-gcm', key, bytes.subarray(0, 12)); cipher.setAuthTag(bytes.subarray(12, 28)); return { result: Buffer.concat([cipher.update(bytes.subarray(28)), cipher.final()]).toString('utf8') } },
  }
}
async function cleanup(home) {
  assert.equal(path.dirname(path.resolve(home)), path.resolve(os.tmpdir()))
  assert.ok(path.basename(home).startsWith('agent-key-test-'))
  await fs.rm(home, { recursive: true, force: true })
}
test('credential file contains ciphertext only, roundtrips, and clears', async () => {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'agent-key-test-'))
  try {
    const manager = agentSecrets(home, encryptor(crypto.randomBytes(32)))
    await manager.save('not-a-real-key', { input: 2 })
    const bytes = await fs.readFile(path.join(home, 'data/deepseek.credentials.enc'))
    assert.ok(!bytes.includes(Buffer.from('not-a-real-key')))
    assert.equal((await manager.load()).api_key, 'not-a-real-key')
    await manager.clear(); assert.equal(await manager.load(), null)
  } finally { await cleanup(home) }
})
test('foreign credentials require reentry, never a plaintext fallback', async () => {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'agent-key-test-'))
  try {
    await agentSecrets(home, encryptor(crypto.randomBytes(32))).save('fake-key')
    const foreign = agentSecrets(home, encryptor(crypto.randomBytes(32)))
    assert.equal(await foreign.load(), null); assert.match(foreign.warning(), /重新输入/)
  } finally { await cleanup(home) }
})
