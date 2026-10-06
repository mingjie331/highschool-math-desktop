// Visual QA uses a copy of previously recognized real candidates. No remote calls.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/workbench-visual');fs.mkdirSync(output,{recursive:true})
const home=fs.mkdtempSync(path.join(output,'isolated-'));let source=path.resolve(process.argv[3]||require('./private_paths.cjs').candidateData)
let fixture=false
if(!fs.existsSync(path.join(source,'question_bank.sqlite3'))){
 const fixtureHome=fs.mkdtempSync(path.join(output,'fixture-'))
 const seeded=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys;sys.argv=['seed','--home',sys.argv[1],'--resources',sys.argv[2],'--frontend',sys.argv[3]];import tests.mock_review_runner",fixtureHome,path.join(root,'resources'),path.join(root,'frontend/dist')],{encoding:'utf8',windowsHide:true})
 assert.equal(seeded.status,0,seeded.stderr);source=path.join(fixtureHome,'data');fixture=true
}
fs.mkdirSync(path.join(home,'data'),{recursive:true})
const result=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sqlite3,pathlib,sys,contextlib;source=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2]);a=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);b=sqlite3.connect(target);a.backup(b);b.close();a.close()",path.join(source,'question_bank.sqlite3'),path.join(home,'data/question_bank.sqlite3')],{encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.stderr)
for(const name of ['assets','agent'])fs.cpSync(path.join(source,name),path.join(home,'data',name),{recursive:true})
let app,page;const checks=[];const single=process.argv.includes('--single');const dpi=Number(process.argv.find(v=>v.startsWith('--dpi='))?.slice(6)||0)
async function request(url){return page.evaluate(async url=>(await(await fetch(url)).json()),url)}
async function main(){
 const executable=process.argv[2]==='source'?undefined:process.argv[2]
 app=await electron.launch({...(executable?{executablePath:executable,args:['--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding',...(dpi?[`--force-device-scale-factor=${dpi}`]:[])]}:{args:[root,'--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding',...(dpi?[`--force-device-scale-factor=${dpi}`]:[])]}),env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000})
 page=await app.firstWindow();await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.setBackgroundThrottling(false));await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000});await page.getByRole('button',{name:'AI 录题',exact:true}).click()
 assert.equal((await request('/api/agent/config')).configured,false)
 const work=(await request('/api/agent/workbench'));assert.ok(work.counts.review>(single||fixture?0:40));assert.equal(work.counts.publish,0)
 await page.getByRole('tab',{name:/待核对/}).click();if(work.counts.review!==1){await page.getByLabel('待核对题目列表').getByRole('button',{name:/^第 /}).first().waitFor();await page.getByLabel('待核对题目列表').getByRole('button',{name:/^第 /}).first().click()}
 await page.getByAltText('核对原材料').waitFor()
 if(single){
   const actual=await request('/api/agent/items/'+work.items[0].id);const edge=actual.issues.find(i=>i.code.startsWith('figure_edge:'))
   assert.equal(edge?.target?.figure_id,'fig2');await page.locator('.ai-material-box.selected').waitFor()
   const geometry=await page.evaluate(()=>{const a=document.querySelector('.ai-page-canvas').getBoundingClientRect(),b=document.querySelector('.ai-material-box.selected').getBoundingClientRect();return{canvas:{left:a.left,top:a.top,right:a.right,bottom:a.bottom},box:{left:b.left,top:b.top,right:b.right,bottom:b.bottom}}})
   assert.ok(geometry.box.left>=geometry.canvas.left-2&&geometry.box.right<=geometry.canvas.right+2&&geometry.box.top>=geometry.canvas.top-2&&geometry.box.bottom<=geometry.canvas.bottom+2);checks.push({name:'actual_fig2_automatic_location',passed:true,geometry});console.log(JSON.stringify(checks.at(-1)))
 }

 for(const setting of [{name:'normal',width:1450,height:940,zoom:1},{name:'minimum',width:1000,height:680,zoom:1},{name:'125percent',width:1250,height:850,zoom:1.25},{name:'150percent',width:1250,height:850,zoom:1.5}].filter(s=>!dpi||s.zoom===1)){
  await app.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(s.width,s.height);w.webContents.setZoomFactor(s.zoom)},setting)
  await new Promise(r=>setTimeout(r,800))
  if(await page.locator('.ai-mobile-switch').isVisible())await page.getByRole('button',{name:'原材料',exact:true}).click()
  const actualZoom=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.getZoomFactor())
  assert.ok(Math.abs(actualZoom-setting.zoom)<.01,`zoom ${actualZoom} differs from ${setting.zoom}`)
  const content=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].getContentSize())
  await page.waitForFunction(width=>Math.abs(innerWidth-width)<3,content[0]/setting.zoom)
  await page.waitForFunction(()=>{const image=document.querySelector('.ai-canvas-page img');return image?.complete&&image.naturalWidth>0&&image.getBoundingClientRect().width>50})
  const bounds=await page.evaluate(()=>{
    const footer=document.querySelector('.ai-review-footer').getBoundingClientRect(),tabs=document.querySelector('.ai-tabs').getBoundingClientRect(),root=document.querySelector('.ai-workbench').getBoundingClientRect(),comparison=document.querySelector('.ai-review-comparison').getBoundingClientRect(),canvas=document.querySelector('.ai-page-canvas').getBoundingClientRect()
    return{footer:{top:footer.top,bottom:footer.bottom,right:footer.right},tabs:{top:tabs.top,bottom:tabs.bottom},devicePixelRatio:devicePixelRatio,width:innerWidth,height:innerHeight,rootRight:root.right,comparisonRatio:comparison.height/root.height,canvasHeight:canvas.height,canvasWidth:canvas.width,imageWidth:document.querySelector('.ai-canvas-page img').getBoundingClientRect().width}
  })
  assert.ok(bounds.footer.bottom<=bounds.height+1);assert.ok(bounds.footer.right<=bounds.width+1);assert.ok(bounds.footer.top>=bounds.tabs.bottom)
  assert.ok(bounds.comparisonRatio>=(setting.name==='normal'?.70:.60),JSON.stringify(bounds));assert.ok(bounds.canvasHeight>180);assert.ok(bounds.canvasWidth>250)
  assert.equal(await page.getByLabel('核对清单').getByRole('button').count(),5)
  if(dpi)assert.ok(Math.abs(bounds.devicePixelRatio-dpi)<.02)
  const capture=await app.evaluate(async({BrowserWindow})=>{
    const w=BrowserWindow.getAllWindows()[0];const image=await w.webContents.capturePage(undefined,{stayHidden:true,stayAwake:true});return image.toPNG().toString('base64')
  })
  fs.writeFileSync(path.join(output,(dpi?`device-${Math.round(dpi*100)}-`:single?'actual-19-':'')+setting.name+'.png'),Buffer.from(capture,'base64'))
  checks.push({name:setting.name,passed:true,actualZoom,bounds});console.log(JSON.stringify(checks.at(-1)))
 }
 await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];w.setSize(1450,940);w.webContents.setZoomFactor(1)})
 if(single&&!dpi){
  const before=await request('/api/agent/items/'+work.items[0].id)
  await page.getByRole('button',{name:'调整裁剪范围',exact:true}).click();await page.getByLabel('配图裁剪设置').waitFor()
  const controls=await page.evaluate(()=>{const p=document.querySelector('.ai-inline-crop').getBoundingClientRect(),s=[...document.querySelectorAll('button')].find(b=>b.textContent==='保存裁剪').getBoundingClientRect(),preview=document.querySelector('.ai-inline-crop-preview').getBoundingClientRect();return{paneBottom:p.bottom,saveTop:s.top,saveBottom:s.bottom,previewHeight:preview.height}})
  assert.ok(controls.saveBottom<=controls.paneBottom+1);assert.ok(controls.previewHeight<=222)
  const shot=await app.evaluate(async({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].webContents.capturePage(undefined,{stayHidden:true,stayAwake:true})).toPNG().toString('base64'))
  fs.writeFileSync(path.join(output,'actual-19-inline-crop.png'),Buffer.from(shot,'base64'))
  await page.getByRole('button',{name:'取消裁剪',exact:true}).click()
  const after=await request('/api/agent/items/'+before.id);assert.equal(before.revision,after.revision)
  checks.push({name:'actual_long_material_crop_save_controls_and_cancel',passed:true,controls})
 }
 // Verify four real question types are represented, and source material pages survive.
 const types=new Set(work.items.filter(i=>i.review_stage==='review').map(i=>i.type));if(!single)assert.ok(['single','multi','fill','long'].every(t=>types.has(t)))
 checks.push({name:fixture?'isolated_fixture_four_types_remain_unreviewed':single?'actual_user_candidate_remains_unreviewed':'real_candidates_four_types_old_compiled_items_remain_unreviewed',passed:true,count:work.counts.review})
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exit,0);app=null
}
main().catch(async e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,dpi?`device-${Math.round(dpi*100)}-results.json`:single?'actual-19-results.json':'results.json'),JSON.stringify({home,remote_calls:0,checks},null,2))})
