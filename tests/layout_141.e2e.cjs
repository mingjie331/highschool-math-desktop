// Viewport and real-input assertions. A container reaching its own end is insufficient.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/layout-141');fs.mkdirSync(output,{recursive:true})
const home=fs.mkdtempSync(path.join(output,'isolated-')),exe=process.argv[2];let app,page;const checks=[]
async function record(name,fn){await fn();checks.push({name,passed:true});console.log(JSON.stringify(checks.at(-1)))}
async function wait(fn){const end=Date.now()+40000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100))}throw new Error('condition timed out')}
async function request(route,method='GET',body){return page.evaluate(async({route,method,body})=>{const r=await fetch(route,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});return {status:r.status,data:await r.json()}},{route,method,body})}
async function screenshot(file){const png=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG().toString('base64'));fs.writeFileSync(file,Buffer.from(png,'base64'))}
async function resize(width,height,zoom){const size=await app.evaluate(({BrowserWindow},v)=>{const w=BrowserWindow.getAllWindows()[0];w.setBounds({width:v[0],height:v[1]});w.webContents.setZoomFactor(v[2]);return w.getContentSize()},[width,height,zoom]);await page.waitForFunction(({size,zoom})=>Math.abs(innerWidth-size[0]/zoom)<3&&Math.abs(innerHeight-size[1]/zoom)<3,{size,zoom})}
async function closeAtEnd(dialog,label){
 const body=dialog.locator('.dialog-body').first(),close=dialog.getByRole('button',{name:label,exact:true});const before=await close.boundingBox()
 if(await body.count()){await body.hover();await page.mouse.wheel(0,20000);await body.focus();await body.press('Control+End');await body.evaluate(n=>{n.scrollTop=n.scrollHeight})}
 const after=await close.boundingBox();assert.ok(before&&after&&Math.abs(before.y-after.y)<2,JSON.stringify({before,after}))
 const hit=await close.evaluate(n=>{const r=n.getBoundingClientRect(),el=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return r.top>=0&&r.bottom<=innerHeight&&(el===n||n.contains(el))});assert.ok(hit,'close is outside viewport or covered')
 await close.click();await dialog.waitFor({state:'hidden'})
}
async function main(){
 const seeded=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys;sys.argv=['seed','--home',sys.argv[1],'--resources',sys.argv[2],'--frontend',sys.argv[3]];import tests.mock_review_runner",home,path.join(root,'resources'),path.join(root,'frontend/dist')],{encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stderr)
 app=await electron.launch({...(exe?{executablePath:exe,args:[]}:{args:[path.join(root,'tests/electron_review_fixture.cjs')]}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setBackgroundThrottling(false));await page.getByLabel('当前题库',{exact:true}).waitFor({timeout:60000})
 const catalog=(await request('/api/catalog')).data;const first=catalog.collections[0].topics[0].points[0].questions[0].id
 const q=(await request('/api/questions/'+first)).data
 await record('source_end_visible_inside_actual_viewport_matrix',async()=>{
  const update=await request('/api/questions/'+q.id,'PATCH',{...q,solution_tex:Array.from({length:65},(_,i)=>`第${i+1}行 $1+1=2$。`).join('\n')+'\n滚动末尾标记',position_mode:'keep'});assert.equal(update.status,200,JSON.stringify(update))
  await page.reload();await page.getByRole('button',{name:'LaTeX 源码',exact:true}).click()
  for(const [width,height] of [[1450,940],[1250,680],[1000,680]])for(const zoom of [1,1.25,1.5]){
   await resize(width,height,zoom)
   const panel=page.getByLabel('源码与题源滚动区');await panel.focus();await panel.press('Control+Home');await panel.hover();await page.mouse.wheel(0,20000);await wait(async()=>await panel.evaluate(n=>n.scrollTop>0))
   await panel.press('Control+End');await wait(async()=>await panel.evaluate(n=>Math.abs(n.scrollHeight-n.clientHeight-n.scrollTop)<3))
   const geometry=await panel.evaluate(n=>{const r=n.getBoundingClientRect(),pre=n.lastElementChild.querySelector('pre'),range=document.createRange();range.selectNodeContents(pre);const last=[...range.getClientRects()].at(-1);const sidebar=document.querySelector('.sidebar'),controls=document.querySelector('.bank-picker');return {height:innerHeight,containerBottom:r.bottom,textBottom:last.bottom,textTop:last.top,docOverflow:document.scrollingElement.scrollHeight-innerHeight,controls:controls.getBoundingClientRect().height,sidebar:sidebar.getBoundingClientRect().height}})
   assert.ok(geometry.containerBottom<=geometry.height+2&&geometry.textBottom<=geometry.containerBottom+2&&geometry.textBottom<=geometry.height+2&&geometry.textTop>=0,JSON.stringify({width,height,zoom,...geometry}))
   assert.ok(geometry.docOverflow<=2&&geometry.controls<=geometry.sidebar/3+2,JSON.stringify(geometry))
  }
  await resize(1450,940,1);await screenshot(path.join(output,exe?'packaged-source-end.png':'source-end.png'))
 })
 await record('source_scrollbar_drag_scrolls_without_document_scroll',async()=>{
  const panel=page.getByLabel('源码与题源滚动区');await panel.focus();await panel.press('Control+Home')
  await wait(async()=>await panel.evaluate(n=>n.scrollTop<2))
  const thumb=await panel.evaluate(n=>{const r=n.getBoundingClientRect(),gutter=n.offsetWidth-n.clientWidth;const track=n.clientHeight-34;return{x:r.right-gutter/2,start:r.top+17+Math.max(18,track*n.clientHeight/n.scrollHeight)/2,end:r.bottom-19,gutter}})
  assert.ok(thumb.gutter>0);await page.mouse.move(thumb.x,thumb.start);await page.mouse.down();await page.mouse.move(thumb.x,thumb.end,{steps:16});await page.mouse.up()
  await wait(async()=>await panel.evaluate(n=>n.scrollTop>0));await panel.focus();await panel.press('Control+End')
  await wait(async()=>await panel.evaluate(n=>Math.abs(n.scrollHeight-n.clientHeight-n.scrollTop)<3))
  const end=await panel.evaluate(n=>({atEnd:Math.abs(n.scrollHeight-n.clientHeight-n.scrollTop)<3,bottom:n.lastElementChild.getBoundingClientRect().bottom,viewport:innerHeight,documentTop:document.scrollingElement.scrollTop}))
  assert.ok(end.atEnd&&end.bottom<=end.viewport+2&&end.documentTop===0,JSON.stringify(end))
 })
 await record('compact_semester_dropdown_and_independent_tree_scroll',async()=>{
  await page.getByLabel('选择学期',{exact:true}).selectOption('gaoyi-second');await page.getByLabel('选择学期',{exact:true}).selectOption('gaoyi-first')
  const control=page.getByLabel('题库与学期选择');const before=await control.boundingBox();const tree=page.locator('.sidebar .tree');await tree.hover();await page.mouse.wheel(0,20000);await tree.evaluate(n=>{n.scrollTop=n.scrollHeight})
  const after=await control.boundingBox();assert.ok(Math.abs(before.y-after.y)<2);assert.equal(await page.getByLabel('选择学期').inputValue(),'gaoyi-first')
 })
 await resize(1250,680,1.25)
 await record('bank_settings_drafts_pool_and_export_close_stays_at_top',async()=>{
  await page.getByRole('button',{name:'新建 / 管理题库'}).click();await closeAtEnd(page.getByRole('dialog',{name:'题库管理'}),'关闭题库管理')
  await page.getByRole('button',{name:'设置',exact:true}).click();const settings=page.getByRole('dialog',{name:'桌面设置'});await settings.locator('details summary').click();await closeAtEnd(settings,'关闭设置')
  await page.getByRole('button',{name:'草稿箱',exact:true}).click();await closeAtEnd(page.getByRole('dialog',{name:'草稿箱'}),'关闭草稿箱')
  await page.getByRole('button',{name:/^组卷区 /}).click();await closeAtEnd(page.getByRole('dialog',{name:'组卷区'}),'关闭组卷区')
  await page.getByRole('button',{name:'导出文件',exact:true}).click();await closeAtEnd(page.getByRole('dialog',{name:'导出文件'}),'关闭导出文件')
 })
 await record('editor_and_nested_paste_close_visible_and_save_failure_blocks_close',async()=>{
  await page.getByRole('button',{name:'增加题目',exact:true}).click();const editor=page.getByRole('dialog').filter({has:page.getByRole('heading',{name:'增加题目',exact:true})})
  await editor.getByRole('button',{name:'粘贴识别',exact:true}).click();const paste=page.getByRole('dialog',{name:'粘贴识别'})
  await paste.getByLabel('粘贴题目文本').fill('【题目】计算 $1+1$。\n【答案】2\n【解析】'+Array.from({length:100},()=>'$1+1=2$。').join('\n'));await closeAtEnd(paste,'关闭粘贴识别')
  await editor.getByLabel('题干 LaTeX').fill('保存失败验证')
  await page.route('**/api/drafts/**',route=>route.request().method()==='PUT'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模拟保存失败'})}):route.continue())
  await editor.locator('.form-column').evaluate(n=>{n.scrollTop=n.scrollHeight});await editor.getByRole('button',{name:'关闭',exact:true}).click();assert.ok(await editor.isVisible());await editor.getByRole('alert').filter({hasText:'模拟保存失败'}).waitFor()
  await page.unroute('**/api/drafts/**');await editor.getByRole('button',{name:'关闭',exact:true}).click();await editor.waitFor({state:'hidden'})
 })
 await record('ai_workbench_nested_pdf_crop_merge_and_delete_close_visible',async()=>{
  await page.getByRole('button',{name:'AI 录题',exact:true}).click();const workbench=page.getByRole('dialog',{name:'AI 录题',exact:true})
  // Import a small self-authored PDF locally; no recognition request.
  const pdf=path.join(home,'local.pdf');const made=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"from pypdf import PdfWriter;import sys;w=PdfWriter();w.add_blank_page(width=72,height=72);w.write(sys.argv[1])",pdf],{encoding:'utf8',windowsHide:true});assert.equal(made.status,0)
  await wait(async()=>await workbench.locator('input[type=file]').isEnabled());await workbench.locator('input[type=file]').setInputFiles(pdf);await workbench.getByRole('button',{name:'查看原 PDF'}).waitFor()
  await workbench.getByRole('button',{name:'查看原 PDF'}).click();await closeAtEnd(page.getByRole('dialog',{name:'原 PDF 预览'}),'关闭原 PDF')
  await workbench.getByRole('button',{name:'裁剪识别范围',exact:true}).last().click();await closeAtEnd(page.getByRole('dialog',{name:'图片裁剪'}),'关闭裁剪')
  await workbench.getByRole('tab',{name:/待核对/}).click();const list=workbench.getByLabel('待核对题目列表');await list.getByRole('button',{name:/^第 /}).first().click()
  await workbench.locator('.ai-more summary').click();await workbench.getByRole('button',{name:'合并同任务题目',exact:true}).click();await closeAtEnd(page.getByRole('dialog',{name:'合并同任务题目'}),'关闭合并题目')
  await workbench.getByRole('button',{name:'题目与筛选',exact:true}).click();await list.getByRole('button',{name:'删除候选题'}).first().click();await closeAtEnd(page.getByRole('dialog',{name:'删除候选题'}),'关闭删除确认')
  const ready=(await request('/api/agent/workbench?review_stage=review')).data.items[0];const current=(await request('/api/agent/items/'+ready.id)).data
  const confirmed=await request('/api/agent/items/'+ready.id+'/confirm-review','POST',{revision:current.revision,request_id:require('node:crypto').randomUUID()});assert.equal(confirmed.status,200,JSON.stringify(confirmed))
  await workbench.getByRole('tab',{name:/待入库/}).click();await workbench.getByRole('button',{name:'预览',exact:true}).first().click();await closeAtEnd(page.getByRole('dialog',{name:'待入库预览'}),'关闭待入库预览')
  const close=workbench.getByRole('button',{name:'关闭 AI 录题'});assert.ok(await close.isVisible());await close.click();await workbench.waitFor({state:'hidden'})
 })
}
main().catch(async e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});if(page)await page.screenshot({path:path.join(output,exe?'packaged-failure.png':'failure.png')}).catch(()=>{});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,exe?'packaged-results.json':'source-results.json'),JSON.stringify({remote_calls:0,checks},null,2))})
