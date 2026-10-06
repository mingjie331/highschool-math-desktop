// Opt-in, real-provider acceptance. Encrypted key remains inside Electron/backend.
// Private inputs, databases and generated pages live only under .cache.
const { _electron: electron } = require('playwright')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const root = path.resolve(__dirname, '..')
const area = require('./private_paths.cjs').liveArea
fs.mkdirSync(area, { recursive: true })
const manifestPath = path.join(area, 'runs.json')
const manifest = fs.existsSync(manifestPath) ? require('./private_paths.cjs').readRuns() : { home: path.join(area, 'home'), cases: [] }
const arg = name => process.argv[process.argv.indexOf(name)+1]
let app, page
async function request(url, method='GET', body) {
  return page.evaluate(async ({url,method,body}) => {
    const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
    const data=await r.json();if(!r.ok)throw new Error(JSON.stringify(data));return data
  },{url,method,body})
}
async function upload(sid,file) {
  const bytes=fs.readFileSync(file).toString('base64')
  return page.evaluate(async ({sid,filename,bytes}) => {
    const data=Uint8Array.from(atob(bytes),ch=>ch.charCodeAt(0));const body=new FormData();body.append('file',new File([data],filename))
    const r=await fetch(`/api/agent/sessions/${sid}/attachments`,{method:'POST',body});const value=await r.json();if(!r.ok)throw new Error(JSON.stringify(value));return value
  },{sid,filename:path.basename(file),bytes})
}
async function main() {
  if (!process.argv.includes('--live')) throw new Error('Real calls require explicit --live and an authorized budget')
  fs.mkdirSync(path.join(manifest.home,'data'),{recursive:true})
  const secret=path.join(manifest.home,'data/deepseek.credentials.enc')
  if(!fs.existsSync(secret)) {
    const source=process.env.QD_LIVE_CREDENTIAL_SOURCE
    if(!source)throw new Error('Provide encrypted credential file path; never a plaintext key')
    fs.copyFileSync(source,secret)
  }
  // Chromium's safeStorage envelope uses the encrypted key in Local State.
  // Copy only that encrypted profile metadata, never decrypt it in this script.
  const credentialSource=process.env.QD_LIVE_CREDENTIAL_SOURCE
  if(credentialSource&&!manifest.cases.length) {
    const state=path.join(path.dirname(path.dirname(credentialSource)),'.cache/electron/Local State')
    if(fs.existsSync(state)) { fs.mkdirSync(path.join(manifest.home,'.cache/electron'),{recursive:true});fs.copyFileSync(state,path.join(manifest.home,'.cache/electron/Local State')) }
  }
  app=await electron.launch({executablePath:require('electron'),args:[root],env:{...process.env,QD_TEST_HOME:manifest.home,QD_TEST_HIDE_WINDOW:'1',QD_AI_TEST_BUDGET_FILE:path.join(area,'budget.json'),QD_AI_TEST_BUDGET_CNY:'20',QD_AI_DIAGNOSTIC_DIR:path.join(area,'diagnostics')},timeout:60000})
  page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})
  if(!(await request('/api/agent/config')).configured)throw new Error('Encrypted key did not restore')
  const materials=require('./private_paths.cjs').materials
  if(!manifest.groups) {
    const files=fs.readdirSync(materials).filter(f=>f.endsWith('.pdf'))
    const groups=[files.filter(f=>f.includes('四川')),files.filter(f=>f.includes('山西')),files.filter(f=>f.includes('九师'))]
    manifest.groups=[]
    for(const files of groups) {
      if(!files.length)throw new Error('Expected three authorized material groups')
      const s=await request('/api/agent/sessions','POST',{title:'真实验收 · '+files[0].slice(0,30)})
      const documents=[]
      for(const name of files)documents.push(await upload(s.id,path.join(materials,name)))
      manifest.groups.push({session_id:s.id,documents});console.log(JSON.stringify({uploaded:files,pages:documents.reduce((n,d)=>n+d.page_count,0)}))
    }
  }
  if(process.argv.includes('--setup'))return
  let batch=Number(arg('--batch')||0)
  if(process.argv.includes('--images')) {
    const directory=arg('--images');const files=fs.readdirSync(directory).filter(f=>/\.(png|jpe?g)$/i.test(f))
    const session=await request('/api/agent/sessions','POST',{title:'真实图片录题验收'})
    const documents=[]
    for(const name of files) {const attachment=await upload(session.id,path.join(directory,name));documents.push({filename:name,page_count:1,pages:[attachment]})}
    batch=manifest.groups.length;manifest.groups.push({session_id:session.id,documents})
  }
  const group=manifest.groups[batch]
  const numbers=process.argv.includes('--numbers')?arg('--numbers'):''
  const ids=group.documents.flatMap(d=>d.pages.map(p=>p.id))
  const body={session_id:group.session_id,attachment_ids:ids,instruction:'提取这些页面的题目与原答案解析，保留所有配图，不重新解题。',question_numbers:numbers,request_id:crypto.randomUUID()}
  if(process.argv.includes('--source'))body.source_title=arg('--source')
  let task
  if(process.argv.includes('--reprocess')) {
    const id=arg('--reprocess');const current=await request('/api/agent/imports/'+id)
    const selected=numbers.split(',')
    task=await request('/api/agent/imports/'+id+'/reprocess','POST',{item_ids:current.items.filter(item=>selected.includes(item.details.original_number)).map(item=>item.id)})
  } else task=process.argv.includes('--retry')?await request('/api/agent/imports/'+arg('--retry')+'/retry','POST',{}):await request('/api/agent/imports','POST',body)
  manifest.cases.push({batch,numbers,task_id:task.id,started_at:new Date().toISOString()});fs.writeFileSync(manifestPath,JSON.stringify(manifest,null,2))
  let last='';let current
  for(let i=0;i<1500;i++) {
    current=await request('/api/agent/imports/'+task.id)
    const signature=JSON.stringify([current.state,current.message,current.calls,current.error])
    if(signature!==last){console.log(signature);last=signature}
    if(!current.worker_active&&!['pending','recognizing','processing','chatting'].includes(current.state))break
    await new Promise(resolve=>setTimeout(resolve,1000))
  }
  const summary={...manifest.cases.at(-1),state:current.state,error:current.error,calls:current.calls,usage:current.usage,cost:current.estimated_cost_cny,
    items:current.items.map(item=>({id:item.id,number:item.details.original_number,state:item.state,classification:[item.form.collection_code,item.form.point_code],
      regions:item.details.regions.length,figures:item.details.figures.length,origins:[item.details.answer_origin,item.details.solution_origin],
      uncertainties:item.details.uncertainties,validation_error:item.details.validation_error,stage_error:item.details.stage_error}))}
  manifest.cases[manifest.cases.length-1]=summary;console.log(JSON.stringify(summary))
}
main().catch(error=>{console.error(error.message);process.exitCode=1}).finally(async()=>{
  fs.writeFileSync(manifestPath,JSON.stringify(manifest,null,2))
  if(app)await app.evaluate(({app})=>app.quit()).catch(()=>{} )
})
