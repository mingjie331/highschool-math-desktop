const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/ui-133');fs.mkdirSync(output,{recursive:true})
const home=fs.mkdtempSync(path.join(output,'run-')),executable=process.argv[2];let app,page;const checks=[];let sourceSession;let originalOrigin;
const pause=ms=>new Promise(r=>setTimeout(r,ms))
async function record(name,fn){await fn();checks.push({name,passed:true});console.log(JSON.stringify(checks.at(-1)))}
async function request(url){return page.evaluate(async url=>(await(await fetch(url)).json()),url)}
const panel=()=>page.getByRole('dialog',{name:'AI 录题',exact:true})
const canvas=()=>panel().getByLabel('原材料画布',{exact:true})
async function shoot(name){await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].showInactive());await pause(500);const png=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG().toString('base64'));fs.writeFileSync(path.join(output,(executable?'packaged-':'source-')+name+'.png'),Buffer.from(png,'base64'));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide())}
async function position(){return canvas().evaluate(node=>{const image=node.querySelector('img').getBoundingClientRect(),box=node.getBoundingClientRect();return{top:node.scrollTop,left:node.scrollLeft,maxY:node.scrollHeight-node.clientHeight,maxX:node.scrollWidth-node.clientWidth,x:(box.left+node.clientWidth/2-image.left)/image.width,y:(box.top+node.clientHeight/2-image.top)/image.height}})}
async function main(){
 if(executable){const r=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys;sys.argv=['seed','--home',sys.argv[1],'--resources',sys.argv[2],'--frontend',sys.argv[3]];import tests.mock_ui133_runner",home,path.join(root,'resources'),path.join(root,'frontend/dist')],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr)}
 app=await electron.launch({...(executable?{executablePath:executable,args:['--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}:{args:[path.join(root,'tests/electron_ui133_fixture.cjs'),'--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.webContents.setBackgroundThrottling(false);w.setSize(1450,940);w.webContents.setZoomFactor(1)})
 await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000});await page.getByRole('button',{name:'AI 录题',exact:true}).click()
 const data=await request('/api/agent/workbench'),task=data.tasks.find(t=>t.message==='已建立导入任务'&&t.filenames.some(f=>f.includes('四川百师联盟')||f==='长图测试.png'))
 assert.ok(task)
 await record('list_full_width_filters_rows_and_zero_results',async()=>{
  await panel().getByRole('tab',{name:/待核对/}).click()
  const bounds=await panel().getByLabel('题目筛选').evaluate(node=>{const box=node.getBoundingClientRect(),root=document.querySelector('.ai-workbench').getBoundingClientRect();return{ratio:box.width/root.width,position:getComputedStyle(node).position}})
  assert.ok(bounds.ratio>.95);assert.equal(bounds.position,'static');await shoot('list')
  await panel().getByLabel('题源筛选',{exact:true}).fill('不存在的题源');await panel().getByRole('button',{name:'筛选',exact:true}).click()
  await panel().getByText('此范围暂无待核对题目，请调整筛选或返回录题任务。',{exact:true}).waitFor();await shoot('empty-list')
  await panel().getByRole('button',{name:'重置筛选',exact:true}).click()
  await panel().getByLabel('任务批次',{exact:true}).selectOption(task.id);await panel().getByLabel('题干 LaTeX',{exact:true}).waitFor()
 })
 await record('native_wheel_scroll_horizontal_drag_and_zoom_anchor',async()=>{
  await page.waitForFunction(()=>{const n=document.querySelector('.ai-page-canvas');return n&&n.scrollHeight>n.clientHeight+100})
  const area=await canvas().boundingBox();await page.mouse.move(area.x+area.width/2,area.y+area.height/2)
  const before=await position(),right=await panel().locator('.ai-review-result fieldset').evaluate(n=>n.scrollTop)
  await page.mouse.wheel(0,250);await pause(700);assert.ok((await position()).top>before.top+100)
  assert.equal(await panel().locator('.ai-review-result fieldset').evaluate(n=>n.scrollTop),right)
  await shoot('scrolled-material')
  const centre=await position();await panel().getByRole('button',{name:'放大原图',exact:true}).click();await pause(350)
  const enlarged=await position();assert.ok(Math.abs(centre.y-enlarged.y)<.025);assert.ok(enlarged.maxX>20)
  await panel().getByRole('button',{name:'缩小原图',exact:true}).click();await pause(300);assert.ok(Math.abs((await position()).y-centre.y)<.025)
  await panel().getByRole('button',{name:'放大原图',exact:true}).click();await pause(300)
  await page.mouse.move(area.x+area.width/2,area.y+area.height/2);await page.keyboard.down('Shift');await page.mouse.wheel(0,100);await page.keyboard.up('Shift');await pause(300)
  assert.ok((await position()).left>enlarged.left+30)
  const dragBefore=await position();await page.mouse.move(area.x+area.width/2,area.y+area.height/2);await page.mouse.down();await page.mouse.move(area.x+area.width/2,area.y+area.height/2-70);await page.mouse.up();assert.ok((await position()).top>dragBefore.top+30)
  await canvas().evaluate(n=>{n.scrollLeft=100;n.scrollTop=100});await page.mouse.wheel(60,40);await pause(250);const pad=await position();assert.ok(pad.left>130&&pad.top>120)
  // Click the native scrollbar track; content pointer handlers must not capture it.
  const track=await canvas().evaluate(n=>{const r=n.getBoundingClientRect();return{x:r.left+n.clientWidth+4,y:r.top+r.height*.8}})
  await page.mouse.click(track.x,track.y);await pause(250);assert.ok((await position()).top>=pad.top)
  const anchor=await position();await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1350,900));await pause(400);assert.ok(Math.abs((await position()).y-anchor.y)<.04)
 })
 await record('crop_after_scroll_maps_to_original_and_cancel_preserves_draft',async()=>{
  const current=(await request('/api/agent/workbench')).items.find(i=>i.task_id===task.id);const before=await request('/api/agent/items/'+current.id)
  await panel().getByLabel('核对清单').getByRole('button',{name:/^配图/}).click();await panel().getByRole('button',{name:'补充配图',exact:true}).click();await panel().getByLabel('配图裁剪设置').waitFor()
  await panel().getByRole('button',{name:'重新框选',exact:true}).click()
  const area=await canvas().boundingBox();const image=await panel().getByAltText('核对原材料').boundingBox()
  const start={x:area.x+area.width*.35,y:area.y+area.height*.45},end={x:start.x+80,y:start.y+60}
  const expected=[(start.x-image.x)/image.width,(start.y-image.y)/image.height,(end.x-image.x)/image.width,(end.y-image.y)/image.height]
  await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(end.x,end.y);await page.mouse.up()
  for(let i=0;i<4;i++)assert.ok(Math.abs(Number(await panel().getByLabel('区域'+['左','上','右','下'][i],{exact:true}).inputValue())-expected[i])<.003)
  await shoot('inline-crop');await panel().getByRole('button',{name:'取消裁剪',exact:true}).click();assert.equal((await request('/api/agent/items/'+before.id)).revision,before.revision)
 })
 await record('saved_list_keeps_filter_and_responsive_layout',async()=>{
  await panel().getByRole('button',{name:'保存，稍后继续',exact:true}).click();await panel().getByLabel('待核对题目列表').waitFor();assert.equal(await panel().getByLabel('任务批次',{exact:true}).inputValue(),task.id)
  await pause(2200);assert.equal(await panel().getByLabel('核对清单').count(),0)
  for(const setting of [{name:'minimum',w:1000,h:680,z:1},{name:'125percent',w:1250,h:850,z:1.25},{name:'150percent',w:1250,h:850,z:1.5}]){
   await app.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(s.w,s.h);w.webContents.setZoomFactor(s.z)},setting);await pause(700)
   assert.ok(await panel().evaluate(n=>n.scrollWidth<=n.clientWidth+1));await shoot('list-'+setting.name)
  }
  await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(1450,940);w.webContents.setZoomFactor(1)})
 })
 await record('upload_visible_sources_manual_override_failure_and_session_restore',async()=>{
  await panel().getByRole('tab',{name:'录题任务',exact:true}).click();await panel().getByRole('button',{name:'新会话',exact:true}).click()
  const source=panel().getByLabel('本批题源',{exact:true})
  const raw=fs.readdirSync(path.join(home,'data/agent/attachments')).find(n=>n.endsWith('.png'));assert.ok(raw)
  const first=path.join(home,'第一份截图.png'),second=path.join(home,'第二份截图.png'),third=path.join(home,'第三份截图.png'),bad=path.join(home,'损坏截图.png')
  for(const file of [first,second,third])fs.copyFileSync(path.join(home,'data/agent/attachments',raw),file);fs.writeFileSync(bad,'not an image')
  async function upload(file){const chooser=page.waitForEvent('filechooser');await panel().getByRole('button',{name:'选择图片或 PDF',exact:true}).click();await(await chooser).setFiles(file)}
  await upload(first);await page.waitForFunction(()=>document.querySelector('[aria-label="本批题源"]').value==='第一份截图')
  await upload(second);await page.waitForFunction(()=>document.querySelector('[aria-label="本批题源"]').value==='第一份截图；第二份截图')
  await source.fill('人工统一题源');await upload(third);await panel().getByText('第三份截图.png',{exact:true}).waitFor();assert.equal(await source.inputValue(),'人工统一题源')
  await upload(bad);await panel().getByRole('button',{name:'选择图片或 PDF',exact:true}).waitFor();await pause(700);assert.equal(await source.inputValue(),'人工统一题源')
  const sid=await panel().getByLabel('录题会话',{exact:true}).inputValue();sourceSession=sid;await panel().getByRole('button',{name:'新会话',exact:true}).click();await panel().getByLabel('录题会话',{exact:true}).selectOption(sid);assert.equal(await source.inputValue(),'人工统一题源')
  await panel().getByRole('button',{name:'按文件自动',exact:true}).click();assert.equal(await source.inputValue(),'')
  const select=panel().getByRole('checkbox',{name:'选择图片 第一份截图.png',exact:true});await select.check();assert.equal(await source.inputValue(),'第一份截图')
  await shoot('source-auto')
  const configured=await page.evaluate(()=>window.desktop.saveAgentKey('sk-ui133-test-only'));assert.equal(configured.configured,true)
  let sent;const fake=await request('/api/agent/imports/'+task.id)
  await page.route('**/api/agent/imports',route=>{sent=route.request().postDataJSON();return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify(fake)})})
  const start=panel().getByRole('button',{name:'开始识别所选页面（1/20）',exact:true});await start.click();await pause(250);assert.equal(sent.source_title,'')
  await source.fill('整批手动题源');sent=null;await start.click();await pause(250);assert.equal(sent.source_title,'整批手动题源')
  await page.unroute('**/api/agent/imports')

 })
 originalOrigin=await page.evaluate(()=>location.origin)
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exit,0);app=null
 await record('source_choice_restores_after_restart_with_new_backend_origin',async()=>{
  app=await electron.launch({...(executable?{executablePath:executable,args:['--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}:{args:[path.join(root,'tests/electron_ui133_fixture.cjs'),'--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding']}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow()
  await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000});await page.getByRole('button',{name:'AI 录题',exact:true}).click();await panel().getByLabel('录题会话',{exact:true}).selectOption(sourceSession)
  await page.waitForFunction(()=>document.querySelector('[aria-label="本批题源"]').value==='整批手动题源')
  assert.equal(await panel().getByRole('button',{name:'整批统一题源',exact:true}).getAttribute('aria-pressed'),'true')
  const currentOrigin=await page.evaluate(()=>location.origin);console.log(JSON.stringify({previous_origin:originalOrigin,current_origin:currentOrigin}))
  const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exit,0);app=null
 })
}
main().catch(async e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1;if(page)await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{})}).finally(async()=>{if(page)await page.getByRole('button',{name:'取消裁剪',exact:true}).click({timeout:1000}).catch(()=>{});if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,executable?'packaged-results.json':'source-results.json'),JSON.stringify({remote_calls:0,provider:'no recognition; local fixture plus original PDF when present',checks},null,2))})
