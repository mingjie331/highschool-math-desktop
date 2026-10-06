// Release checks never make a remote call: the key below is a test placeholder.
const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const root = path.resolve(__dirname, '..')
const output = path.join(root, 'test-results/agent-packaged')
fs.mkdirSync(output, { recursive: true })
const home = fs.mkdtempSync(path.join(output, 'run-'))
const exe = process.argv[2]
if (!exe) throw new Error('Provide the extracted release executable')
let app, page, child
const results = []
async function open() {
  app = await electron.launch({ executablePath: exe, args: [], env: { ...process.env, QD_TEST_HOME: home, QD_TEST_HIDE_WINDOW: '1' }, timeout: 60000 })
  child = app.process(); page = await app.firstWindow()
  await page.getByRole('button', { name: 'AI 录题', exact: true }).waitFor({ timeout: 60000 })
}
async function close() { const exit = new Promise(resolve => child.once('exit', resolve)); await app.evaluate(({ app }) => { app.quit() }); assert.equal(await exit, 0) }
async function record(name, action) { await action(); results.push({ name, passed: true }); console.log(JSON.stringify(results.at(-1))) }
async function request(url, method = 'GET', body) {
  return page.evaluate(async ({ url, method, body }) => { const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }); return { status: response.status, data: await response.json() } }, { url, method, body })
}
async function main() {
  await open()
  await record('release_offline_start_and_agent_taxonomy', async () => {
    assert.equal((await request('/api/catalog')).data.total, 627)
    assert.equal((await request('/api/agent/catalog')).data.length, 57)
    assert.equal((await request('/api/agent/config')).data.configured, false)
  })
  await record('release_native_encrypted_key_restores_after_restart', async () => {
    await page.evaluate(() => window.desktop.saveAgentKey('TEST-PLACEHOLDER-DO-NOT-CALL-REMOTE'))
    assert.equal((await request('/api/agent/config')).data.configured, true)
    assert.ok(!fs.readFileSync(path.join(home, 'data/deepseek.credentials.enc')).includes(Buffer.from('TEST-PLACEHOLDER-DO-NOT-CALL-REMOTE')))
    await close(); await open()
    assert.equal((await request('/api/agent/config')).data.configured, true)
    await page.evaluate(() => window.desktop.clearAgentKey())
    assert.equal((await request('/api/agent/config')).data.configured, false)
  })
  await record('release_ai_panel_and_image_upload_without_remote_key', async () => {
    await page.getByRole('button', { name: 'AI 录题', exact: true }).click()
    const panel = page.getByRole('dialog', { name: 'AI 录题', exact: true })
    await panel.getByText(/尚未配置 DeepSeek 密钥/).waitFor()
    const chooser = page.waitForEvent('filechooser'); await panel.getByRole('button', { name: '选择图片或 PDF', exact: true }).click()
    const source = path.join(root, 'resources/seed/assets')
    await (await chooser).setFiles(path.join(source, fs.readdirSync(source).find(file => file.endsWith('.png'))))
    await panel.getByRole('button', { name: /开始识别所选页面（1\/20）/ }).waitFor()
    assert.equal(await panel.getByRole('button', { name: /开始识别所选页面（1\/20）/ }).isDisabled(), true)
    const sid = (await request('/api/agent/sessions')).data[0].id
    const session = (await request('/api/agent/sessions/' + sid)).data
    const result = await request('/api/agent/imports', 'POST', { session_id: sid, attachment_ids: [session.attachments[0].id], instruction: '提取', source_title: '', request_id: crypto.randomUUID() })
    assert.equal(result.status, 409)
    assert.equal((await request('/api/catalog')).data.total, 627)
    await page.screenshot({ path: path.join(output, 'no-key.png') })
  })
  await record('release_pdf_renders_locally_and_original_pdf_previews_without_key', async () => {
    const { spawnSync }=require('node:child_process')
    const pdf=path.join(home,'两页测试.pdf')
    const make=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c','from pypdf import PdfWriter;import sys;w=PdfWriter();w.add_blank_page(width=200,height=200);w.add_blank_page(width=200,height=200);w.write(sys.argv[1])',pdf],{windowsHide:true})
    assert.equal(make.status,0)
    const panel=page.getByRole('dialog',{name:'AI 录题',exact:true})
    const chooser=page.waitForEvent('filechooser');await panel.getByRole('button',{name:'选择图片或 PDF',exact:true}).click();await(await chooser).setFiles(pdf)
    await panel.getByText('两页测试.pdf · 2 页',{exact:true}).waitFor()
    const sid=(await request('/api/agent/sessions')).data[0].id;const session=(await request('/api/agent/sessions/'+sid)).data
    assert.equal(session.documents.length,1);assert.equal(session.attachments.filter(p=>p.document_id).length,2)
    await panel.getByRole('button',{name:'查看原 PDF',exact:true}).click()
    const preview=page.getByRole('dialog',{name:'原 PDF 预览'});await preview.getByText('共 2 页',{exact:true}).waitFor({timeout:30000})
    await preview.getByRole('button',{name:'关闭原 PDF',exact:true}).click()
    assert.equal((await request('/api/catalog')).data.total,627)
  })
  await close()
}
main().catch(async error => { console.error(error); results.push({ name: 'failure', passed: false, error: error.stack }); process.exitCode = 1 }).finally(async () => {
  if (app && child?.exitCode === null) await app.close().catch(() => {})
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ home, executable: exe, remote_calls: 0, results }, null, 2))
})
