// Source and packaged-app regression checks use a separate portable data directory.
const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const assert = require('node:assert/strict')

const root = path.resolve(__dirname, '..')
const output = path.join(root, 'test-results', 'desktop')
fs.mkdirSync(output, { recursive: true })
const home = fs.mkdtempSync(path.join(output, '独立 数据-'))
const executable = process.argv[2]
const results = []
let application, page, childProcess
async function record(name, action) {
  await action()
  results.push({ name, passed: true })
  console.log(JSON.stringify(results.at(-1)))
}
async function request(route, method = 'GET', data) {
  return page.evaluate(async ({ route, method, data }) => {
    const response = await fetch(route, { method, headers: { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) })
    return { status: response.status, data: await response.json() }
  }, { route, method, data })
}
async function main() {
  application = await electron.launch({
    ...(executable ? { executablePath: executable, args: [] } : { args: [root] }),
    env: { ...process.env, QD_TEST_HOME: home, QD_TEST_HIDE_WINDOW: '1', QUESTION_VIEWER_SKIP_LATEX_VALIDATION: '1' },
    timeout: 60000,
  })
  childProcess = application.process()
  page = await application.firstWindow()
  await page.getByRole('button', { name: '增加题目', exact: true }).waitFor({ timeout: 60000 })
  await record('desktop_start_and_migration', async () => {
    const result = await request('/api/catalog')
    assert.equal(result.data.total, 627)
    assert.equal(result.data.collections[0].count, 518)
    assert.ok(fs.existsSync(path.join(home, 'data', 'backups')))
  })
  await record('editor_return_to_original_collection_is_valid', async () => {
    await page.getByRole('button', { name: '修改', exact: true }).click()
    const dialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '修改题目' }) })
    await dialog.waitFor()
    const original = await dialog.getByLabel('插入序号').inputValue()
    await dialog.getByLabel('所属集合').selectOption('gaoyi-second')
    assert.equal(await dialog.getByLabel('插入序号').inputValue(), '1')
    await dialog.getByLabel('所属集合').selectOption('gaoyi-first')
    assert.equal(await dialog.getByLabel('插入序号').inputValue(), original)
    const value = await dialog.getByLabel('插入序号').evaluate(input => ({ value: Number(input.value), max: Number(input.max) }))
    assert.ok(value.value <= value.max)
    await dialog.getByRole('button', { name: '保存并关闭', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
  })
  await record('legacy_draft_adopts_position_policy_before_publish', async () => {
    const catalog=(await request('/api/catalog')).data
    const id=catalog.collections[0].topics[0].points[0].questions[0].id
    const question=(await request('/api/questions/'+id)).data
    for(const draft of (await request('/api/drafts')).data) {
      if(draft.source_question_id===id) await request('/api/drafts/'+draft.id+'?revision='+draft.revision,'DELETE')
    }
    const legacyId=require('node:crypto').randomUUID()
    const fields=['collection_code','point_code','position','type','question_tex','options','answer_tex','solution_tex','sources','verified']
    const form=Object.fromEntries(fields.map(key=>[key,question[key]]))
    const source_rows=(question.sources.origins||[]).map(origin=>({title:origin.title||origin.paper_id||'',originalNumber:String(origin.original_number??''),metadata:origin}))
    const saved=await request('/api/drafts/'+legacyId,'PUT',{revision:0,source_question_id:id,base_revision:question.revision,content:{form,source_rows}})
    assert.equal(saved.status,200)
    assert.equal(saved.data.position_mode,null)
    await page.getByRole('button',{name:'修改',exact:true}).click()
    const editor=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:'修改题目'})})
    await editor.getByText('草稿已保存',{exact:true}).waitFor({timeout:15000})
    const restored=(await request('/api/drafts/'+legacyId)).data
    assert.equal(restored.position_mode,'keep')
    assert.equal(restored.revision,2)
    await editor.getByRole('button',{name:'保存并关闭',exact:true}).click()
    await editor.waitFor({state:'hidden'})
  })
  await record('corrupt_settings_recover_in_real_desktop', async () => {
    fs.writeFileSync(path.join(home, 'data', 'settings.json'), '{broken')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '桌面设置' })
    await dialog.getByText(/设置文件损坏/).waitFor()
    await dialog.getByRole('button', { name: '保存设置', exact: true }).click()
    await dialog.getByText('已找到 XeLaTeX，可运行编译测试', { exact: true }).waitFor()
    await dialog.getByRole('button', { name: '关闭设置' }).click()
  })
  await page.getByRole('button', { name: '增加题目', exact: true }).click()
  const editor = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: '增加题目' }) })
  await editor.getByLabel('所属集合').selectOption('gaoyi-second')
  await editor.getByLabel('题型', { exact: true }).selectOption('fill')
  await editor.getByLabel('题干 LaTeX').fill('界面回归测试：$1+1=$？')
  await editor.getByLabel('答案 LaTeX', { exact: true }).fill('2')
  await editor.getByLabel('解析 LaTeX').fill('$1+1=2$。')
  await record('real_preview_and_stale_indicator', async () => {
    await editor.getByText('预览已更新', { exact: true }).first().waitFor({ timeout: 30000 })
    await editor.getByText('共 1 页', { exact: true }).waitFor({timeout:15000})
    await editor.locator('canvas').first().waitFor({timeout:15000})
    assert.ok(await editor.locator('canvas').count())
    await editor.getByLabel('题干 LaTeX').fill('界面回归测试修改：$1+1=$？')
    await editor.getByText('当前画面是上一次预览，尚未反映最新修改。').waitFor()
    await editor.getByText('预览已更新', { exact: true }).first().waitFor({ timeout: 30000 })
    await editor.getByText('共 1 页', { exact: true }).waitFor({timeout:15000})
    await page.screenshot({path:path.join(output,executable?'packaged-preview.png':'source-preview.png')})
  })
  await record('autosave_recovers_committed_response_loss', async () => {
    await page.evaluate(() => {
      const original=window.fetch.bind(window)
      window.fetch=async(input,init)=>{
        const response=await original(input,init)
        if(init?.method==='PUT' && String(input).startsWith('/api/drafts/')) {
          window.fetch=original
          throw new Error('test: response lost after commit')
        }
        return response
      }
    })
    await editor.getByLabel('解析 LaTeX').fill('$1+1=2$。响应丢失后保留内容。')
    await editor.getByText('草稿已保存',{exact:true}).waitFor({timeout:15000})
    const drafts=(await request('/api/drafts')).data
    assert.ok(drafts.some(draft=>draft.content.form.solution_tex.includes('响应丢失后保留内容')))
  })
  await record('disconnected_preview_stops_real_compiler', async () => {
    await editor.getByText('预览已更新',{exact:true}).first().waitFor({timeout:30000})
    await page.evaluate(() => {
      window.cancelProbe=new AbortController()
      window.probePromise=fetch('/api/preview',{
        method:'POST',headers:{'Content-Type':'application/json'},signal:window.cancelProbe.signal,
        body:JSON.stringify({type:'fill',question_tex:'\\loop\\iftrue\\repeat',solution_tex:'测试',options:[],sources:{},preview_session_id:crypto.randomUUID(),preview_revision:1}),
      }).catch(()=>null)
    })
    await new Promise(resolve=>setTimeout(resolve,1500))
    await page.evaluate(()=>window.cancelProbe.abort())
    const start=Date.now()
    const status=await page.evaluate(async()=>{
      const result=await fetch('/api/desktop/latex/test',{method:'POST',signal:AbortSignal.timeout(12000)})
      return result.status
    })
    assert.equal(status,200)
    assert.ok(Date.now()-start<12000)
  })
  await record('position_conflict_reconfirmation_in_ui', async () => {
    await request('/api/questions', 'POST', {
      collection_code: 'gaoyi-second', point_code: '6.1', position: 1, type: 'fill', question_tex: '$2+2=$？',
      options: [], answer_tex: '4', solution_tex: '$2+2=4$。', sources: {},
    })
    await editor.getByRole('button', { name: '校验并保存', exact: true }).click()
    await editor.getByRole('button', { name: '重新确认位置', exact: true }).waitFor({ timeout: 30000 })
    assert.ok(await editor.getByRole('button', { name: '校验并保存', exact: true }).isDisabled())
    await editor.getByRole('button', { name: '重新确认位置', exact: true }).click()
    await editor.getByText('插入位置已重新确认，可以校验并保存。').waitFor()
    await editor.getByRole('button', { name: '校验并保存', exact: true }).click()
    await editor.waitFor({ state: 'hidden', timeout: 30000 })
  })
  await record('valid_image_upload_and_invalid_bytes_rejected', async () => {
    const png = fs.readFileSync(path.join(root, 'resources', 'seed', 'assets', fs.readdirSync(path.join(root, 'resources', 'seed', 'assets')).find(name => name.endsWith('.png')))).toString('base64')
    const {spawnSync}=require('node:child_process')
    const fixture=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import io,base64;from pypdf import PdfWriter;w=PdfWriter();w.add_blank_page(100,100);b=io.BytesIO();w.write(b);print(base64.b64encode(b.getvalue()).decode())"],{encoding:'utf8',windowsHide:true})
    assert.equal(fixture.status,0,fixture.stderr)
    const values = await page.evaluate(async ({png,pdf}) => {
      const post = async (bytes, name) => { const body = new FormData();body.append('file',new Blob([bytes],{type:'image/png'}),name);return (await fetch('/api/assets',{method:'POST',body})).status }
      return [await post(Uint8Array.from(atob(png),c=>c.charCodeAt(0)),'图.png'),await post('fake','fake.png'),
        await post(Uint8Array.from(atob(pdf),c=>c.charCodeAt(0)),'图.pdf')]
    }, {png,pdf:fixture.stdout.trim()})
    assert.deepEqual(values,[201,422,201])
  })
  await record('collection_export_in_real_desktop', async () => {
    const started = await request('/api/exports','POST',{collection_code:'gaoyi-second'})
    assert.equal(started.status,200)
    const deadline=Date.now()+120000
    let status
    while(Date.now()<deadline) {
      status=(await request('/api/exports/status?collection_code=gaoyi-second')).data
      if(status.state==='ready') break
      if(status.state==='failed') throw new Error(status.error)
      await new Promise(resolve=>setTimeout(resolve,250))
    }
    assert.equal(status.state,'ready',JSON.stringify(status))
    const pointer=JSON.parse(fs.readFileSync(path.join(home,'output/current-gaoyi-second.json'),'utf8'))
    const folder=path.join(home,'output/versions/gaoyi-second',pointer.generation)
    assert.ok(fs.existsSync(path.join(folder,'preamble.tex')))
  })
  await record('close_flushes_draft_and_exits', async () => {
    await page.getByRole('button', { name:'增加题目', exact:true }).click()
    const editor=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:'增加题目'})})
    await editor.getByLabel('题干 LaTeX').fill('退出保存回归测试')
    const exportRequest = await request('/api/exports','POST',{collection_code:'gaoyi-first'})
    assert.equal(exportRequest.status,200)
    const log = fs.readFileSync(path.join(home,'logs/desktop.log'),'utf8')
    const backendPid = Number(log.match(/Started server process \[(\d+)\]/)?.[1])
    const exit = new Promise((resolve,reject) => { const timer=setTimeout(()=>reject(new Error('desktop did not exit')),15000);childProcess.once('exit',code=>{clearTimeout(timer);resolve(code)}) })
    await application.evaluate(({app})=>{app.quit()})
    assert.equal(await exit,0)
    const { spawnSync } = require('node:child_process')
    const code = "import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); rows=[json.loads(r[0]) for r in c.execute('select content_json from drafts')]; assert any('退出保存回归测试' in r['form']['question_tex'] for r in rows); print('draft flushed')"
    const result=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',code,path.join(home,'data/question_bank.sqlite3')],{encoding:'utf8',windowsHide:true})
    assert.equal(result.status,0,result.stdout+result.stderr)
    assert.ok(!fs.existsSync(path.join(home,'output/current-gaoyi-first.json')))
    if(backendPid) {
      let alive=true
      try { process.kill(backendPid,0) } catch(error) { if(error.code==='ESRCH') alive=false;else throw error }
      assert.equal(alive,false,'backend remained after application exit')
    }
  })
}
main().catch(error=>{console.error(error);results.push({name:'failure',passed:false,error:error.stack});process.exitCode=1}).finally(async()=>{
  if(application && childProcess && childProcess.exitCode===null) await application.close().catch(()=>{})
  fs.writeFileSync(path.join(output,executable?'packaged-results.json':'source-results.json'),JSON.stringify({home,executable:executable||'source',results},null,2))
})
