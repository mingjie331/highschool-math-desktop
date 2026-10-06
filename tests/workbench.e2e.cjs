const { _electron:electron }=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/workbench');fs.mkdirSync(output,{recursive:true})
const executable=process.argv[2]
const home=fs.mkdtempSync(path.join(output,'run-'));let app,page,child;const results=[]
async function request(url,method='GET',body){return page.evaluate(async({url,method,body})=>{const response=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return{status:response.status,data:await response.json()}},{url,method,body})}
async function record(name,fn){await fn();results.push({name,passed:true});console.log(JSON.stringify(results.at(-1)))}
async function wait(fn){const end=Date.now()+40000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,150))}throw new Error('condition timed out')}
async function loseResponse(fragment){await page.evaluate(fragment=>{
 window.__testOriginalFetch=window.fetch;window.__testResponseDropped=false
 window.fetch=async(...args)=>{const response=await window.__testOriginalFetch(...args);const url=typeof args[0]==='string'?args[0]:args[0].url;if(url.includes(fragment)&&!window.__testResponseDropped){window.__testResponseDropped=true;throw new TypeError('模拟响应丢失')}return response}
},fragment)}
async function restoreFetch(){return page.evaluate(()=>{const dropped=window.__testResponseDropped;window.fetch=window.__testOriginalFetch;return dropped})}
async function open(){app=await electron.launch({...(executable?{executablePath:executable,args:['--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}:{args:[path.join(root,'tests/electron_review_fixture.cjs'),'--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});child=app.process();page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setBackgroundThrottling(false));await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})}
async function close(){const exited=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exited,0);app=null}
async function main(){
 if(executable){
  const {spawnSync}=require('node:child_process')
  const result=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys;sys.argv=['seed','--home',sys.argv[1],'--resources',sys.argv[2],'--frontend',sys.argv[3]];import tests.mock_review_runner",home,path.join(root,'resources'),path.join(root,'frontend/dist')],{encoding:'utf8',windowsHide:true})
  assert.equal(result.status,0,result.stderr)
 }
 await open();await page.getByRole('button',{name:'AI 录题',exact:true}).click()
 const panel=()=>page.getByRole('dialog',{name:'AI 录题',exact:true})
 const list=()=>panel().getByLabel('待核对题目列表').getByRole('button',{name:/^第 /})
 const checklist=(name)=>panel().getByLabel('核对清单').getByRole('button',{name:new RegExp('^'+name)})
 const showQueue=async()=>{if(!await panel().getByLabel('待核对题目列表').isVisible())await panel().getByRole('button',{name:'题目与筛选',exact:true}).click()}
 const choose=async text=>{await showQueue();await list().filter({hasText:text}).click()}

 await record('three_tabs_task_counts_and_global_review_queue',async()=>{
  await panel().getByRole('tab',{name:'录题任务',exact:true}).waitFor();assert.equal(await panel().getByRole('tab').count(),3)
  await panel().getByRole('button',{name:'核对 4 题',exact:true}).waitFor();const q=(await request('/api/agent/workbench')).data;assert.equal(q.counts.review,5);assert.equal(q.counts.publish,0)
  await panel().getByRole('tab',{name:/待核对/}).click();await list().first().waitFor()
  assert.equal(await list().count(),5)
 })
 let first
 await record('problem_free_candidate_requires_explicit_confirmation_and_stays_open',async()=>{
  await list().first().click();await panel().getByLabel('题干 LaTeX',{exact:true}).waitFor()
  const q=(await request('/api/agent/workbench')).data;first=q.items[0]
  assert.equal((await request('/api/agent/items/'+first.id)).data.review_stage,'review')
  await panel().getByRole('button',{name:'核对完成，移至待入库',exact:true}).click()
  await panel().getByText('核对完成，已移至待入库。',{exact:true}).waitFor({timeout:30000})
  assert.equal(await panel().getByLabel('题干 LaTeX',{exact:true}).isDisabled(),true)
  assert.equal((await request('/api/agent/items/'+first.id)).data.review_stage,'publish')
  assert.equal((await request('/api/catalog')).data.total,627)
 })
 await record('external_edit_invalidates_confirmation_and_explains_next_step',async()=>{
  const before=(await request('/api/agent/items/'+first.id)).data
  const update=await request('/api/agent/items/'+first.id,'PATCH',{revision:before.revision,changes:{form:{question_tex:before.form.question_tex+'（外部修改）'}}});assert.equal(update.status,200)
  await panel().getByText('内容或资源已变化，人工确认已失效，请重新核对。',{exact:true}).waitFor()
  assert.equal(await panel().getByLabel('题干 LaTeX',{exact:true}).isDisabled(),false)
  await panel().getByRole('button',{name:'核对完成，移至待入库',exact:true}).click();await panel().getByText('核对完成，已移至待入库。',{exact:true}).waitFor({timeout:30000})
 })
 await record('return_edit_autosave_tab_switch_and_source_filter',async()=>{
  await panel().getByRole('button',{name:'退回修改',exact:true}).click();await panel().getByLabel('题干 LaTeX',{exact:true}).fill('第2套计算 $1+1$。（人工修正）')
  await panel().getByRole('tab',{name:'录题任务',exact:true}).click();assert.equal((await request('/api/agent/items/'+first.id)).data.form.question_tex,'第2套计算 $1+1$。（人工修正）')
  await panel().getByRole('tab',{name:/待核对/}).click();await panel().getByLabel('题源筛选',{exact:true}).fill('核对测试卷1');await panel().getByRole('button',{name:'筛选',exact:true}).click()
  await panel().getByRole('button',{name:'题目与筛选',exact:true}).waitFor();await wait(async()=>!await panel().getByLabel('待核对题目列表').isVisible());await showQueue();await wait(async()=>await list().count()===1)
  await showQueue();await panel().getByLabel('题源筛选',{exact:true}).fill('');await panel().getByRole('button',{name:'筛选',exact:true}).click();await wait(async()=>await list().count()===5)
 })
 await record('issue_tags_focus_answer_conflict_and_classification_inline',async()=>{
  await choose('第 20 题');await checklist('答案解析').click()
  await panel().getByText(/未提供可比较答案，请对照原材料与解析核对/).waitFor()
  await panel().getByRole('button',{name:'保留原答案',exact:true}).click()
  await checklist('分类与题源').click();await panel().getByRole('button',{name:'确认当前分类',exact:true}).click()
  await panel().getByRole('button',{name:'核对完成，移至待入库',exact:true}).click();await panel().getByText('核对完成，已移至待入库。',{exact:true}).waitFor({timeout:30000})
 })
 await record('save_failure_blocks_navigation_and_lost_response_recovers_user_fields',async()=>{
  await panel().getByRole('button',{name:'下一题',exact:true}).click();await checklist('题干与选项').click();await panel().getByLabel('题干 LaTeX',{exact:true}).waitFor()
  const pattern='**/api/agent/items/*'
  await page.route(pattern,route=>route.request().method()==='PATCH'?route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'模拟保存失败，输入保留'})}):route.continue())
  await panel().getByLabel('题干 LaTeX',{exact:true}).fill('保存失败也保留此输入 $2+2$。')
  await panel().getByRole('tab',{name:'录题任务',exact:true}).click()
  await panel().getByText('模拟保存失败，输入保留',{exact:true}).first().waitFor()
  assert.equal(await panel().getByRole('tab',{name:/待核对/}).getAttribute('aria-selected'),'true')
  assert.equal(await panel().getByLabel('题干 LaTeX',{exact:true}).inputValue(),'保存失败也保留此输入 $2+2$。')
  await page.unroute(pattern)
  await loseResponse('/api/agent/items/')
  await checklist('答案解析').click();await panel().getByLabel('答案 LaTeX',{exact:true}).fill('测试人工修正的答案')
  await panel().getByRole('tab',{name:'录题任务',exact:true}).click();await panel().getByRole('button',{name:'新会话',exact:true}).waitFor();assert.equal(await restoreFetch(),true)
  await panel().getByRole('tab',{name:/待核对/}).click()
 })
 await record('fig2_guided_inline_crop_zoom_coordinates_cancel_and_real_compile',async()=>{
  await choose('第 21 题');await checklist('配图').click()
  assert.equal(await panel().getByLabel('核对清单').getByRole('button').count(),5)
  const checkbox=panel().getByLabel('已对照原材料，确认所有配图完整');assert.equal(await checkbox.isDisabled(),true)
  assert.equal(await panel().getByRole('button',{name:'调整裁剪范围',exact:true}).count(),1)
  await panel().getByRole('button',{name:'调整裁剪范围',exact:true}).click()
  await panel().getByLabel('配图裁剪设置').waitFor();assert.equal(await page.getByRole('dialog',{name:'图片裁剪',exact:true}).count(),0)
  await panel().getByRole('button',{name:'查看整页',exact:true}).click();await panel().getByRole('button',{name:'放大原图',exact:true}).click()
  const handle=await panel().getByRole('button',{name:'裁剪se边界',exact:true}).boundingBox()
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();await page.mouse.move(handle.x+handle.width/2+15,handle.y+handle.height/2+12);await page.mouse.up()
  assert.ok(Number(await panel().getByLabel('区域右',{exact:true}).inputValue())>.8)
  await panel().getByRole('button',{name:'取消裁剪',exact:true}).click()
  const q=(await request('/api/agent/workbench')).data.items.find(i=>i.original_number==='21')
  assert.equal((await request('/api/agent/items/'+q.id)).data.details.figures[0].rect[2],.8)
  await panel().getByRole('button',{name:'调整裁剪范围',exact:true}).click()
  await panel().getByRole('tab',{name:'录题任务',exact:true}).click();await panel().getByText('请先保存或取消当前裁剪，输入仍保留。',{exact:true}).first().waitFor()
  assert.equal(await panel().getByRole('tab',{name:/待核对/}).getAttribute('aria-selected'),'true')
  for(const [label,value] of [['左','.1'],['上','.27'],['右','.85'],['下','.65']])await panel().getByLabel('区域'+label,{exact:true}).fill(value)
  await panel().getByRole('button',{name:'保存裁剪',exact:true}).click();await panel().getByLabel('配图裁剪设置').waitFor({state:'hidden'})
  await wait(async()=>!await checkbox.isDisabled());await checkbox.check()
  await checklist('排版检查').click();await panel().getByRole('button',{name:'检查排版',exact:true}).click()
  await panel().getByText('当前内容真实编译通过，仍需整题人工确认。',{exact:true}).waitFor({timeout:30000})
  assert.equal((await request('/api/agent/items/'+q.id)).data.review_stage,'review')
  await panel().getByRole('button',{name:'核对完成，移至待入库',exact:true}).click();await panel().getByText('核对完成，已移至待入库。',{exact:true}).waitFor({timeout:30000})
  assert.deepEqual((await request('/api/agent/items/'+q.id)).data.details.figures[0].rect,[.1,.27,.85,.65])
 })
 await record('skip_is_not_human_confirmation_or_waiting_to_publish',async()=>{
  await choose('第 22 题');await panel().locator('.ai-more summary').click();await panel().getByRole('button',{name:'跳过此题',exact:true}).click()
  await panel().getByText('已跳过此题，草稿保留；没有完成人工确认。',{exact:true}).waitFor()
  assert.equal(await panel().locator('.ai-review-title small').textContent(),'已跳过')
  assert.equal(await panel().getByRole('button',{name:'查看待入库',exact:true}).count(),0)
  const task=(await request('/api/agent/workbench')).data.items.find(i=>i.original_number==='22');assert.equal(task.review_stage,'skipped')
  assert.equal((await request('/api/agent/items/'+task.id)).data.reviewed_at,null)
 })
 await record('cross_task_selection_explicit_batch_publish_and_open_formal_question',async()=>{
  // Confirm the first task's complete candidate using the UI as well.
  await choose('核对测试卷1')
  await loseResponse('/confirm-review')
  await panel().getByRole('button',{name:'核对完成，移至待入库',exact:true}).click();await panel().getByText('核对完成，已移至待入库。',{exact:true}).waitFor({timeout:30000})
  assert.equal(await restoreFetch(),true)
  await panel().getByRole('button',{name:'查看待入库',exact:true}).click();await panel().getByRole('button',{name:'选择当前筛选结果',exact:true}).click()
  await panel().getByRole('button',{name:'加入题库（3）',exact:true}).waitFor()
  const outgoing=page.waitForRequest(r=>r.url().endsWith('/api/agent/publish')&&r.method()==='POST')
  await loseResponse('/api/agent/publish')
  await panel().getByRole('button',{name:'加入题库（3）',exact:true}).click();const sent=await outgoing
  await panel().getByText('已加入题库 3 道题，核验状态仍为待核验。',{exact:true}).waitFor({timeout:30000})
  assert.equal(await restoreFetch(),true)
  const replay=await request('/api/agent/publish','POST',sent.postDataJSON());assert.equal(replay.status,200);assert.equal((await request('/api/catalog')).data.total,630)
  await panel().getByRole('button',{name:'查看已入库题目 1',exact:true}).click();await panel().waitFor({state:'hidden'})
 })
 await record('restart_keeps_review_state_and_clean_exit',async()=>{
  await close();await open();const q=(await request('/api/agent/workbench')).data;assert.equal(q.counts.published,3);assert.equal(q.counts.review,1)
  await page.getByRole('button',{name:'AI 录题',exact:true}).click();await panel().getByRole('tab',{name:/待核对/}).click();await panel().getByRole('button',{name:'题目与筛选',exact:true}).waitFor();await showQueue();await list().first().click()
  await panel().getByLabel('题干 LaTeX',{exact:true}).fill('退出前保存的内容 $2+2$。');await close()
  await open();const items=(await request('/api/agent/workbench')).data.items
  assert.ok(items.some(i=>i.summary.includes('退出前保存')))
 })
 if(!executable) await record('task_tab_image_upload_mock_recognition_and_no_automatic_human_approval',async()=>{
  await page.evaluate(()=>window.desktop.saveAgentKey('TEST-MOCK-NOT-A-REAL-KEY'))
  await page.getByRole('button',{name:'AI 录题',exact:true}).click()
  await panel().getByRole('button',{name:'新会话',exact:true}).click()
  const source=fs.readdirSync(path.join(home,'data/agent/attachments')).find(name=>name.endsWith('.png'))
  const chooser=page.waitForEvent('filechooser');await panel().getByRole('button',{name:'选择图片或 PDF',exact:true}).click();await(await chooser).setFiles(path.join(home,'data/agent/attachments',source))
  const start=panel().getByRole('button',{name:'开始识别所选页面（1/20）',exact:true});await start.waitFor();await wait(async()=>!(await start.isDisabled()));await start.click()
  await wait(async()=>{const all=(await request('/api/agent/workbench')).data;return all.items.length===7&&all.counts.processing===0})
  const sessions=(await request('/api/agent/sessions')).data;const session=(await request('/api/agent/sessions/'+sessions[0].id)).data
  const task=(await request('/api/agent/imports/'+session.tasks[0].id)).data
  assert.equal(task.items.length,2);assert.ok(task.calls>=5);assert.ok(task.items.every(item=>item.review_stage==='review'&&!item.reviewed_hash))
  assert.equal((await request('/api/catalog')).data.total,630)
  await close()
 })
 if(app)await close()
}
main().catch(async e=>{console.error(e.stack);results.push({name:'failure',passed:false,error:e.message});process.exitCode=1;if(page)await page.screenshot({path:path.join(output,'failure.png'),timeout:5000}).catch(()=>{})}).finally(async()=>{if(page)await page.getByRole('button',{name:'取消裁剪',exact:true}).click({timeout:1000}).catch(()=>{});if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,executable?'packaged-results.json':'results.json'),JSON.stringify({home,executable:executable||'source',remote_calls:0,provider:executable?'real release; seeded isolated candidates; no remote calls':'mock only; real SQLite/XeLaTeX/Electron',results},null,2))})
