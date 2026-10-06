const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto')
function sourcePreferences(home){
 const directory=path.join(home,'.cache','source-preferences')
 const file=sid=>{if(typeof sid!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sid))throw new Error('会话标识无效');return path.join(directory,sid+'.json')}
 const valid=value=>value&&['auto','manual'].includes(value.mode)&&typeof value.manual==='string'&&value.manual.length<=1000
 return {
  load(sid){const target=file(sid);try{const value=JSON.parse(fs.readFileSync(target,'utf8'));return valid(value)?{mode:value.mode,manual:value.manual}:null}catch(error){if(error.code==='ENOENT'||error instanceof SyntaxError)return null;throw error}},
  save(sid,value){const target=file(sid);if(!valid(value))throw new Error('题源填写偏好无效');fs.mkdirSync(directory,{recursive:true});const tmp=target+'.'+crypto.randomUUID()+'.tmp';try{fs.writeFileSync(tmp,JSON.stringify({mode:value.mode,manual:value.manual}),{encoding:'utf8'});fs.renameSync(tmp,target)}finally{if(fs.existsSync(tmp))fs.unlinkSync(tmp)}return true}
 }
}
module.exports={sourcePreferences}
