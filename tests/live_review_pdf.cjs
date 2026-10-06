// Review/preview/publish acceptance operates only on the isolated live-test home.
// Approval entries contain local test edits, never an API key or raw responses.
const { _electron: electron } = require('playwright')
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto')
const root=path.resolve(__dirname,'..'),area=require('./private_paths.cjs').liveArea
const runs=require('./private_paths.cjs').readRuns()
const approval=JSON.parse(fs.readFileSync(path.join(area,'qa-approval.json')))
let app,page;const previous=fs.existsSync(path.join(area,'publication-results.json'))?JSON.parse(fs.readFileSync(path.join(area,'publication-results.json'))):{checks:[]}
const checks=previous.checks.filter(c=>c.passed&&c.name!=='clean_release_shutdown')
async function request(url,method='GET',body) {
 return page.evaluate(async({url,method,body})=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(JSON.stringify(data));return data},{url,method,body})
}
async function main() {
 const executable=process.argv[2]
 const flags=['--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding','--disable-background-timer-throttling']
 app=await electron.launch({executablePath:executable||require('electron'),args:executable?flags:[root,...flags],env:{...process.env,QD_TEST_HOME:runs.home,QD_TEST_HIDE_WINDOW:'1',QD_AI_TEST_BUDGET_FILE:path.join(area,'budget.json'),QD_AI_TEST_BUDGET_CNY:'20'},timeout:60000})
 page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})
 await page.getByRole('button',{name:'AI 录题',exact:true}).click()
 for(const entry of approval) {
  let task=await request('/api/agent/imports/'+entry.task_id)
  let item=task.items.find(i=>i.details.original_number===entry.number)
  assert.ok(item,'approved sample missing')
  const session=await request('/api/agent/sessions/'+task.session_id)
  await page.getByRole('combobox',{name:'录题会话',exact:true}).selectOption(session.id)
  await page.getByRole('combobox',{name:'导入批次',exact:true}).selectOption(task.id)
  for(const adjustment of entry.figures||[]) {
   const figure=item.details.figures.find(f=>f.id===adjustment.id)
   item=await request('/api/agent/items/'+item.id+'/figure','POST',{revision:item.revision,region:{image_id:figure.image_id,rect:adjustment.rect},field:figure.field,figure_id:figure.id})
  }
  const form={}
  for(const [field,replacements] of Object.entries(entry.replace||{})) {
   let value=item.form[field]
   for(const [before,after] of replacements){if(value.includes(before))value=value.replaceAll(before,after);else assert.ok(value.includes(after), 'review edit does not match saved text')}
   form[field]=value
  }
  if(Object.keys(form).length)item=await request('/api/agent/items/'+item.id,'PATCH',{revision:item.revision,changes:{form}})
  if(entry.form)item=await request('/api/agent/items/'+item.id,'PATCH',{revision:item.revision,changes:{form:entry.form,classification_uncertain:false}})
  if(item.details.figures.length) {
   // The crops in the approval file were rendered and visually reviewed before this run.
   item=await request('/api/agent/items/'+item.id,'PATCH',{revision:item.revision,changes:{figures_confirmed:true}})
  }
  item=await request('/api/agent/items/'+item.id+'/validate','POST')
  assert.equal(item.state,'ready',JSON.stringify(item.details))
  const panel=page.getByRole('dialog',{name:'AI 录题',exact:true});const card=panel.locator('.ai-item').filter({hasText:`原题号 ${entry.number}`}).first()
  await card.getByRole('button',{name:'解析预览',exact:true}).click()
  const preview=page.getByRole('dialog',{name:'候选题 PDF 预览'});await preview.getByText(/共 \d+ 页/).waitFor({timeout:30000})
  await page.screenshot({path:path.join(area,`preview-${entry.label}.png`),timeout:5000}).catch(()=>{})
  await preview.getByRole('button',{name:'关闭候选预览',exact:true}).click()
  // Use the actual confirmation button; capture its idempotency request for replay.
  const outgoing=page.waitForRequest(r=>r.url().endsWith('/api/agent/imports/'+task.id+'/publish')&&r.method()==='POST')
  await card.getByRole('checkbox',{name:`选择候选题 ${item.item_order}`}).check()
  await panel.getByRole('button',{name:'确认入库所选题（1）',exact:true}).click()
  const sent=await outgoing;await new Promise(r=>setTimeout(r,500))
  const result=await request('/api/agent/imports/'+task.id+'/publish','POST',sent.postDataJSON())
  const question=await request('/api/questions/'+result.items[0].question_id)
  assert.equal(question.verified,false)
  assert.equal(question.sources.origins[0].original_number,entry.number)
  checks.push({name:entry.label,passed:true,question_id:question.id,source_title:question.sources.origins[0].title,number:entry.number})
  console.log(JSON.stringify(checks.at(-1)))
 }
 const before=(await request('/api/catalog')).total
 const child=app.process();const exited=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exited,0);app=null
 checks.push({name:'clean_release_shutdown',passed:true,total:before})
}
main().catch(error=>{console.error(error.stack);checks.push({name:'failure',passed:false,error:error.message});process.exitCode=1}).finally(async()=>{
 if(app)await app.close().catch(()=>{})
 fs.writeFileSync(path.join(area,'publication-results.json'),JSON.stringify({executable:process.argv[2]||'source',checks},null,2))
})
