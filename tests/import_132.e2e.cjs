const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/import-132');fs.mkdirSync(output,{recursive:true})
const home=fs.mkdtempSync(path.join(output,'run-'));const executable=process.argv[2];let app,page;const checks=[]
async function request(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return{status:response.status,data:await response.json()}},{url,method,body})}
async function record(name,fn){await fn();checks.push({name,passed:true});console.log(JSON.stringify(checks.at(-1)))}
async function main(){
 if(!fs.existsSync(require('./private_paths.cjs').materials)){console.log('SKIPPED_PRIVATE_MATERIALS: use --materials or QD_TEST_MATERIALS');checks.push({name:'private_materials_unavailable',passed:true,skipped:true});return}
 if(executable){const r=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys;sys.argv=['seed','--home',sys.argv[1],'--resources',sys.argv[2],'--frontend',sys.argv[3]];import tests.mock_review_runner",home,path.join(root,'resources'),path.join(root,'frontend/dist')],{encoding:'utf8',windowsHide:true,env:{...process.env,QD_IMPORT_132:'1'}});assert.equal(r.status,0,r.stderr)}
 app=await electron.launch({...(executable?{executablePath:executable,args:[]}:{args:[path.join(root,'tests/electron_review_fixture.cjs')]}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1',QD_IMPORT_132:'1'},timeout:60000});page=await app.firstWindow()
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setBackgroundThrottling(false))
 await page.getByRole('button',{name:'AI 录题',exact:true}).click();const panel=page.getByRole('dialog',{name:'AI 录题',exact:true})
 await record('legacy_empty_placeholder_visible_in_task_failures_only',async()=>{
  await panel.getByRole('button',{name:'查看任务',exact:true}).first().waitFor()
  const data=(await request('/api/agent/workbench')).data;assert.equal(data.counts.review,5);assert.equal(data.counts.failed,1)
  assert.ok(data.items.every(i=>i.summary.trim()))
  const failureTask=data.tasks.find(t=>t.counts.failed===1);assert.ok(failureTask)
  await panel.locator('.ai-task-card').filter({hasText:'失败 1'}).getByRole('button',{name:'查看任务',exact:true}).click()
  await panel.getByRole('heading',{name:'提取失败（未进入待核对）',exact:true}).waitFor()
  assert.equal((await request('/api/agent/imports/'+failureTask.id)).data.failures[0].code,'legacy_empty_stem')
 })
 await record('delete_button_cancel_then_atomic_delete_lost_response_retry',async()=>{
  await panel.getByRole('tab',{name:/待核对/}).click();await panel.getByLabel('待核对题目列表').getByRole('button',{name:/^第 22 /}).click()
  const queue=(await request('/api/agent/workbench')).data;const row=queue.items.find(i=>i.original_number==='22');const old=(await request('/api/agent/items/'+row.id)).data
  await panel.getByRole('button',{name:'删除候选题',exact:true}).first().click();const confirm=page.getByRole('dialog',{name:'删除候选题',exact:true});await confirm.getByRole('button',{name:'取消删除',exact:true}).click()
  assert.equal((await request('/api/agent/items/'+row.id)).data.review_stage,'review')
  await page.evaluate(()=>{const original=window.fetch;let dropped=false;window.fetch=async(...args)=>{const r=await original(...args);if(args[1]?.method==='DELETE'&&!dropped){dropped=true;await new Promise(resolve=>setTimeout(resolve,2400));throw new TypeError('响应丢失')}return r}})
  await panel.getByRole('button',{name:'删除候选题',exact:true}).first().click();await confirm.getByRole('button',{name:'确认删除候选题',exact:true}).click()
  await confirm.waitFor({state:'hidden'});await panel.getByText('候选题及草稿已删除，原材料与其他题目保留。',{exact:true}).first().waitFor()
  assert.equal((await request('/api/agent/items/'+row.id)).data.review_stage,'deleted');assert.equal((await request('/api/drafts/'+old.draft_id)).status,404)
  assert.equal((await request('/api/catalog')).data.total,627)
  const task=(await request('/api/agent/imports/'+row.task_id)).data;assert.equal(task.deleted_count,1)
 })
 await record('combined_pdf_cropped_pages_18_19_request_has_no_self_pair',async()=>{
  await panel.getByRole('tab',{name:'录题任务',exact:true}).click()
  const saved=await page.evaluate(()=>window.desktop.saveAgentKey('sk-isolated-test-only'));assert.equal(saved.configured,true)
  const material=fs.readdirSync(require('./private_paths.cjs').materials).find(n=>n.includes('四川百师联盟'))
  const chooser=page.waitForEvent('filechooser');await panel.getByRole('button',{name:'选择图片或 PDF',exact:true}).click();await(await chooser).setFiles(path.join(require('./private_paths.cjs').materials,material))
  await panel.getByText(material+' · 9 页',{exact:true}).waitFor()
  const ids=(await request('/api/agent/sessions')).data;let session;for(const s of ids){const candidate=(await request('/api/agent/sessions/'+s.id)).data;if(candidate.documents.length){session=candidate;break}};assert.ok(session)
  const pdfPages=session.attachments.filter(a=>a.document_id)
  const pageCheckboxes=panel.getByRole('checkbox',{name:'选择图片 '+material,exact:true})
  for(let n=0;n<9;n++)if(![0,5,6,7].includes(n))await pageCheckboxes.nth(n).uncheck()
  const cropButton=panel.getByRole('button',{name:/^裁剪识别范围/})
  const nonPdf=session.attachments.filter(a=>!a.document_id).length
  await cropButton.nth(nonPdf).click();const crop=page.getByRole('dialog',{name:'图片裁剪',exact:true})
  for(const [label,v] of [['左','.5'],['上','.62'],['右','.98'],['下','.98']])await crop.getByLabel('区域'+label,{exact:true}).fill(v)
  await crop.getByRole('button',{name:'保存题目区域',exact:true}).click();await crop.waitFor({state:'hidden'})
  await panel.getByLabel('提取题号',{exact:true}).fill('18,19')
  let body
  const fallback=(await request('/api/agent/imports/'+session.tasks[0].id)).data
  await page.route('**/api/agent/imports',route=>{body=route.request().postDataJSON();return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify(fallback)})})
  await panel.getByRole('button',{name:'开始识别所选页面（4/20）',exact:true}).click()
  await page.waitForTimeout(300);assert.ok(body);assert.deepEqual(body.document_pairs,[]);assert.equal(body.question_numbers,'18,19')
  assert.deepEqual(body.input_regions.find(r=>r.image_id===pdfPages[0].id).rect,[.5,.62,.98,.98]);assert.equal(body.attachment_ids.length,4)
  await page.unroute('**/api/agent/imports')
 })
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exit,0);app=null
}
main().catch(e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,executable?'packaged-results.json':'source-results.json'),JSON.stringify({remote_calls:0,provider:'controlled responses; PDF request intercepted, no real recognition',checks},null,2))})
