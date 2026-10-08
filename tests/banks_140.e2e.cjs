// Complete source/packaged v1.4 acceptance; isolated data and no remote AI calls.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/banks-140');fs.mkdirSync(output,{recursive:true})
const home=fs.mkdtempSync(path.join(output,'run-')),exe=process.argv[2];let app,page;const checks=[]
async function record(name,fn){await fn();checks.push({name,passed:true});console.log(JSON.stringify(checks.at(-1)))}
async function request(route,method='GET',body){return page.evaluate(async({route,method,body})=>{const response=await fetch(route,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:response.status,data:await response.json()}},{route,method,body})}
async function wait(fn){const end=Date.now()+90000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,200))}throw new Error('timed out')}
async function main(){
 const pdf=path.join(home,'35pages.pdf')
 const made=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"from pypdf import PdfWriter;import sys;w=PdfWriter();[w.add_blank_page(width=72,height=72) for _ in range(35)];w.write(sys.argv[1])",pdf],{encoding:'utf8',windowsHide:true});assert.equal(made.status,0,made.stderr)
 app=await electron.launch({...(exe?{executablePath:exe,args:[]}:{args:[root]}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000})
 page=await app.firstWindow();await page.getByLabel('当前题库',{exact:true}).waitFor({timeout:60000})
 const picker=()=>page.getByLabel('当前题库',{exact:true});let bank,q
 await record('system_seed_and_new_empty_bank_ui',async()=>{
  assert.equal((await request('/api/catalog')).data.total,627)
  await page.getByRole('button',{name:'新建 / 管理题库'}).click()
  const manager=page.getByRole('dialog',{name:'题库管理'});await manager.getByLabel('题库名称').fill('课外补充');await manager.getByRole('button',{name:'创建题库',exact:true}).click()
  await wait(async()=>{bank=await picker().inputValue();return bank!=='system'})
  await page.getByRole('button',{name:'关闭题库管理'}).click()
  assert.equal((await request('/api/catalog?bank_id='+bank)).data.total,0)
 })
 await record('long_latex_source_scroll_and_responsive_layout',async()=>{
  const value={bank_id:bank,collection_code:'gaoyi-first',point_code:'1.1',position:1,type:'fill',question_tex:'独立源码测试 $1+1=$？',answer_tex:'2',solution_tex:Array.from({length:45},(_,i)=>`解析第 ${i+1} 行：$1+1=2$。`).join('\n')+'源码末尾标记',options:[],sources:{origins:[{title:'自编测试'}]}}
  const created=await request('/api/questions','POST',value);assert.equal(created.status,201,JSON.stringify(created));q=created.data.question
  await page.reload();await page.getByRole('button',{name:'LaTeX 源码'}).click()
  const panel=page.getByLabel('源码与题源滚动区')
  for(const [width,height,zoom] of [[1450,940,1],[1000,680,1],[1450,940,1.25],[1450,940,1.5]]){
    const size=await app.evaluate(({BrowserWindow},v)=>{const w=BrowserWindow.getAllWindows()[0];w.setBounds({width:v[0],height:v[1]});w.webContents.setZoomFactor(v[2]);w.webContents.setBackgroundThrottling(false);return w.getContentSize()},[width,height,zoom])
    await page.waitForFunction(({size,zoom})=>Math.abs(innerWidth-size[0]/zoom)<3&&Math.abs(innerHeight-size[1]/zoom)<3,{size,zoom})
  await page.waitForFunction(()=>document.querySelector('.viewer-card').getBoundingClientRect().bottom<=innerHeight+2)
  await panel.focus();await panel.press('Control+End')
  await wait(async()=>await panel.evaluate(n=>Math.abs(n.scrollHeight-n.clientHeight-n.scrollTop)<3))
  const measured=await panel.evaluate(node=>{const last=node.querySelector('section:last-child');const box=node.getBoundingClientRect();const r=last.getBoundingClientRect();return{top:node.scrollTop,height:node.clientHeight,total:node.scrollHeight,visible:r.bottom<=box.bottom+2&&r.bottom<=innerHeight+2,unclipped:last.scrollHeight<=last.clientHeight+2}})
    assert.ok(measured.top>0&&measured.visible&&measured.unclipped,JSON.stringify(measured))
  }
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.setBounds({width:1450,height:940});w.webContents.setZoomFactor(1)})
  await page.screenshot({path:path.join(output,exe?'packaged-source.png':'source.png')})
 })
 await record('edit_existing_question_keeps_bank_and_publishes',async()=>{
  await page.getByRole('button',{name:'修改',exact:true}).click()
  const editor=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:'修改题目',exact:true})})
  await editor.getByLabel('题干 LaTeX').fill('独立题库编辑后 $1+1=$？')
  await editor.getByRole('button',{name:'校验并保存',exact:true}).click()
  await editor.waitFor({state:'hidden',timeout:60000})
  q=(await request('/api/questions/'+q.id)).data;assert.equal(q.bank_id,bank);assert.ok(q.question_tex.includes('编辑后'))
 })
 await record('bank_pool_and_move_copy_scoped_exports',async()=>{
  assert.equal((await request('/api/pool/'+q.id+'?bank_id='+bank,'PUT')).status,200)
  assert.equal((await request('/api/pool')).data.count,0)
  const scope={kind:'point',point_code:'1.1'}
  const started=await request('/api/exports','POST',{bank_id:bank,collection_code:'gaoyi-first',scope});assert.equal(started.status,200)
  await wait(async()=>{const s=(await request('/api/exports/status?bank_id='+bank+'&collection_code=gaoyi-first&scope='+encodeURIComponent(JSON.stringify(scope)))).data;if(s.state==='failed')throw new Error(s.error);return s.state==='ready'})
  const manifest=(await request('/api/bank-exports/'+started.data.key+'/files/manifest')).data;assert.equal(manifest.count,1);assert.equal(manifest.bank_id,bank)
  await page.getByLabel('导出范围').selectOption('point');await page.getByLabel('导出考点').selectOption('1.1');await wait(async()=>!(await page.getByRole('button',{name:'打开题目册',exact:true}).isDisabled()))
  const savedPath=path.join(home,'scoped-export.pdf')
  await app.evaluate(({dialog},target)=>{dialog.showSaveDialog=async()=>({canceled:false,filePath:target})},savedPath)
  assert.equal(await page.evaluate(key=>window.desktop.exportFile('question','save','gaoyi-first',key),started.data.key),true)
  assert.equal(fs.readFileSync(savedPath).subarray(0,5).toString(),'%PDF-')
  const copy=await request('/api/banks/transfer','POST',{source_bank_id:bank,target_bank_id:'system',mode:'copy',selection:[{id:q.id,revision:q.revision}],request_id:require('node:crypto').randomUUID()});assert.equal(copy.status,200)
  const move=await request('/api/banks/transfer','POST',{source_bank_id:bank,target_bank_id:'system',mode:'move',selection:[{id:q.id,revision:q.revision}],request_id:require('node:crypto').randomUUID()});assert.equal(move.status,200)
  assert.equal((await request('/api/catalog?bank_id='+bank)).data.total,0)
  assert.equal((await request('/api/questions/'+q.id)).data.bank_id,'system')
  assert.equal((await request('/api/pool?bank_id='+bank)).data.count,0)
 })
 await record('35_page_import_first20_clear_and_last15_without_remote_calls',async()=>{
  await page.getByRole('button',{name:'AI 录题',exact:true}).click()
  const panel=page.getByRole('dialog',{name:'AI 录题',exact:true})
  await wait(async()=>await panel.locator('input[type=file]').isEnabled())
  await panel.locator('input[type=file]').setInputFiles(pdf)
  const pages=panel.locator('.ai-attachments input[type=checkbox]');await wait(async()=>await pages.count()===35)
  await wait(async()=>await panel.locator('.ai-attachments input:checked').count()===20)
  assert.equal(await pages.nth(0).isChecked(),true);assert.equal(await pages.nth(19).isChecked(),true);assert.equal(await pages.nth(20).isChecked(),false)
  await pages.nth(20).click();assert.equal(await pages.nth(20).isChecked(),false)
  await panel.getByRole('button',{name:'取消选择',exact:true}).first().click();assert.equal(await panel.locator('.ai-attachments input:checked').count(),0)
  for(let i=20;i<35;i++)await pages.nth(i).check()
  assert.equal(await panel.locator('.ai-attachments input:checked').count(),15)
  await panel.getByRole('button',{name:'全选（最多20页）',exact:true}).last().click();assert.equal(await panel.locator('.ai-attachments input:checked').count(),20);assert.equal(await pages.nth(0).isChecked(),true)
  const sessions=(await request('/api/agent/sessions?bank_id='+bank)).data;assert.equal(sessions.length,1)
  assert.equal((await request('/api/agent/sessions')).data.length,0)
  assert.equal((await request('/api/agent/workbench?bank_id='+bank)).data.tasks.length,0)
  await page.screenshot({path:path.join(output,exe?'packaged-pdf.png':'pdf.png')})
 })
}
main().catch(async e=>{console.error(e.stack);if(page)console.error(await page.locator('[role=status]').allTextContents());checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,exe?'packaged-results.json':'source-results.json'),JSON.stringify({remote_calls:0,checks},null,2))})
