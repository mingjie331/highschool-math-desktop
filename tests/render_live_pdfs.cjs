const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path')
const root=path.resolve(__dirname,'..'),area=require('./private_paths.cjs').liveArea,runs=require('./private_paths.cjs').readRuns()
let app,page
async function main(){
 app=await electron.launch({executablePath:process.argv[2],args:[],env:{...process.env,QD_TEST_HOME:runs.home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow();await page.getByRole('button',{name:'AI 录题',exact:true}).waitFor({timeout:60000})
 for(const sample of JSON.parse(fs.readFileSync(path.join(area,'publication-results.json'))).checks.filter(c=>c.question_id)){
  const encoded=await page.evaluate(async id=>{const form=await(await fetch('/api/questions/'+id)).json();const response=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...form,view:'solution'})});if(!response.ok)throw new Error(await response.text());const bytes=new Uint8Array(await response.arrayBuffer());let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(text)},sample.question_id)
  fs.mkdirSync(path.join(area,'pdfs'),{recursive:true});fs.writeFileSync(path.join(area,'pdfs',sample.name+'.pdf'),Buffer.from(encoded,'base64'));console.log(sample.name)
 }
 const child=app.process(),exit=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());await exit;app=null
}
main().catch(e=>{console.error(e.message);process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{})})
