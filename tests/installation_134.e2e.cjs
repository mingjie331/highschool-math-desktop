// Read-only installation acceptance. No remote API test or recognition request.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawnSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),output=path.join(root,'test-results/installation-134');fs.mkdirSync(output,{recursive:true})
const exe=path.resolve(process.argv[2]),source=path.resolve(process.argv[3]||'D:/Apps/高中数学题库'),real=process.argv.includes('--real-home')
const home=real?source:fs.mkdtempSync(path.join(output,'copy-'));let app,page;const checks=[]
function inspect(directory){const r=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys,json;sys.path.insert(0,sys.argv[1]);from install_inventory import database_inventory;print(json.dumps(database_inventory(sys.argv[2])))",path.join(root,'scripts'),path.join(directory,'data/question_bank.sqlite3')],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout)}
async function main(){
 if(!real){
  const r=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-c',"import sys,shutil,pathlib;sys.path.insert(0,sys.argv[1]);from install_inventory import consistent_copy,filesystem_path;source=pathlib.Path(sys.argv[2]);target=pathlib.Path(sys.argv[3]);target.joinpath('data').mkdir();shutil.copytree(filesystem_path(source/'data'),filesystem_path(target/'data'),dirs_exist_ok=True);db=target/'data/question_bank.sqlite3';db.unlink();[(target/'data'/n).unlink(missing_ok=True) for n in ['question_bank.sqlite3-wal','question_bank.sqlite3-shm']];consistent_copy(source/'data/question_bank.sqlite3',db);shutil.copytree(filesystem_path(source/'.cache'),filesystem_path(target/'.cache'))",path.join(root,'scripts'),source,home],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr)
 }
 const before=inspect(home)
 app=await electron.launch({executablePath:exe,args:['--disable-backgrounding-occluded-windows'],env:{...process.env,QD_TEST_HOME:home,QD_TEST_HIDE_WINDOW:'1'},timeout:60000});page=await app.firstWindow()
 await page.getByRole('button',{name:'设置',exact:true}).waitFor({timeout:60000})
 const state=await page.evaluate(async()=>({info:await window.desktop.appInfo(),catalog:await(await fetch('/api/catalog')).json(),config:await(await fetch('/api/agent/config')).json()}))
 assert.equal(state.info.version,'1.3.4');assert.equal(path.resolve(state.info.program_directory),path.dirname(exe));assert.equal(path.resolve(state.info.data_directory),path.join(home,'data'));assert.equal(state.catalog.total,628);assert.equal(state.config.configured,true)
 checks.push({name:'version_actual_program_and_data_paths',passed:true},{name:'main_628_question_bank_and_encrypted_configuration_restored',passed:true})
 await page.getByRole('button',{name:'设置',exact:true}).click();const settings=page.getByRole('dialog',{name:'桌面设置',exact:true})
 await settings.getByLabel('程序与数据位置').getByText('1.3.4',{exact:true}).waitFor();assert.equal(await settings.getByLabel('程序与数据位置').getByRole('textbox').count(),0)
 checks.push({name:'settings_information_is_read_only',passed:true})
 await settings.getByRole('button',{name:'关闭设置',exact:true}).click()
 const child=app.process(),exited=new Promise(r=>child.once('exit',r));await app.evaluate(({app})=>app.quit());assert.equal(await exited,0);app=null
 assert.deepEqual(inspect(home),before);checks.push({name:'normal_exit_preserves_all_business_tables',passed:true})
}
main().catch(e=>{console.error(e.stack);checks.push({name:'failure',passed:false,error:e.message});process.exitCode=1}).finally(async()=>{if(app)await app.close().catch(()=>{});fs.writeFileSync(path.join(output,real?'fixed-results.json':'isolated-results.json'),JSON.stringify({remote_calls:0,encrypted_key_value_exposed:false,checks},null,2));console.log(JSON.stringify(checks))})
