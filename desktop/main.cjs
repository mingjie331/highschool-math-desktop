const { app, BrowserWindow, ipcMain, dialog, shell, session, safeStorage } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')

const project = path.resolve(__dirname, '..')
const home = path.resolve(process.env.QD_TEST_HOME || (app.isPackaged ? path.dirname(process.execPath) : path.join(project, 'runtime')))
const payload = app.isPackaged ? path.join(process.resourcesPath, 'payload') : project
const sourcePreferences = require('./source-preferences.cjs').sourcePreferences(home)
const token = crypto.randomBytes(32).toString('hex')
const secrets = require('./agent-secrets.cjs').agentSecrets(home, safeStorage)
let backend, window, origin, quitting = false, stopped = false
const logDir = path.join(home, 'logs')
function log(message) {
  try {
    const file = path.join(logDir, 'desktop.log')
    if (fs.existsSync(file) && fs.statSync(file).size > 5 * 1024 * 1024) fs.renameSync(file, path.join(logDir, 'desktop.previous.log'))
    fs.appendFileSync(file, `${new Date().toISOString()} ${message}\n`)
  } catch {}
}
try {
  fs.mkdirSync(logDir, { recursive: true })
  fs.writeFileSync(path.join(home, '.write-test'), 'ok')
  fs.unlinkSync(path.join(home, '.write-test'))
  app.setPath('userData', path.join(home, '.cache', 'electron'))
} catch (error) {
  dialog.showErrorBox('目录不可写', '请将完整应用文件夹解压到有写入权限的位置，例如桌面或文档目录。\n' + error.message)
  app.exit(1)
}
// Electron's lock is scoped to userData, hence to this portable directory.
if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => { if (window) { if (window.isMinimized()) window.restore(); window.show(); window.focus() } })
  app.whenReady().then(start).catch(fatal)
}

async function backendFetch(route, init = {}) {
  const response = await fetch(origin + route, { ...init, headers: { 'x-desktop-token': token, ...init.headers } })
  if (!response.ok) throw new Error(`后台请求失败 (${response.status})`)
  return response
}

async function startBackend() {
  const executable = app.isPackaged ? path.join(payload, 'backend-runtime', 'question-backend.exe') : path.join(project, '.venv', 'Scripts', 'python.exe')
  const args = app.isPackaged ? [] : ['-m', 'backend.runner']
  args.push('--home', home, '--resources', path.join(payload, 'resources'), '--frontend', path.join(payload, 'frontend', 'dist'))
  const env = { ...process.env, QD_TOKEN: token, PYTHONUTF8: '1', QD_APP_VERSION: app.getVersion() }
  delete env.ELECTRON_RUN_AS_NODE
  backend = spawn(executable, args, { cwd: payload, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
  backend.stderr.on('data', data => log(data.toString()))
  backend.on('error', error => { if (!quitting) fatal(error) })
  backend.on('exit', code => {
    stopped = true
    log(`Backend exited: ${code}`)
    if (!quitting) fatal(new Error('题库后台意外停止，请重新打开应用。'))
  })
  await new Promise((resolve, reject) => {
    let text = ''
    const timer = setTimeout(() => reject(new Error('后台启动超时，请查看日志。')), 60000)
    backend.stdout.on('data', chunk => {
      if (origin) { log(chunk.toString()); return }
      text += chunk.toString()
      const match = text.match(/QD_PORT=(\d+)/)
      if (match && !origin) { origin = `http://127.0.0.1:${match[1]}`; text = ''; clearTimeout(timer); resolve() }
    })
    backend.once('error', error => { clearTimeout(timer); reject(error) })
    backend.once('exit', () => { clearTimeout(timer); reject(new Error('后台未能完成初始化，请查看日志。')) })
  })
  for (let i = 0; i < 120; i++) {
    try { await backendFetch('/api/health', { signal: AbortSignal.timeout(1000) }); return } catch {}
    if (stopped) throw new Error('后台已退出。')
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('后台未就绪，请查看日志。')
}

async function start() {
  window = new BrowserWindow({ width: 1450, height: 940, minWidth: 1000, minHeight: 680,
    title: '高中数学题库', backgroundColor: '#f4f1ea', show: false,
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true } })
  window.setMenuBarVisibility(false)
  window.webContents.on('will-prevent-unload', event => { if (quitting) event.preventDefault() })
  window.on('close', event => { if (!quitting) { event.preventDefault(); app.quit() } })
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<html lang="zh"><body style="background:#f4f1ea;color:#135d54;font:22px Microsoft YaHei;display:grid;place-items:center;height:90vh"><div>高中数学题库<p style="font-size:14px">正在打开题库…</p></div></body></html>'))
  if (!(process.env.QD_TEST_HOME && process.env.QD_TEST_HIDE_WINDOW === '1')) window.show()
  await startBackend()
  const credentials = await secrets.load()
  if (credentials) {
    try { await backendFetch('/api/agent/credentials', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(credentials) }) }
    catch { log('DeepSeek configuration restore failed; re-enter it in settings.') }
  }
  await session.defaultSession.setProxy({ mode: 'direct' })
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    if (details.url.startsWith(origin + '/')) details.requestHeaders['x-desktop-token'] = token
    callback({ requestHeaders: details.requestHeaders })
  })
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) event.preventDefault() })
  registerHandlers()
  for (let attempt = 0; attempt < 4; attempt++) {
    try { await window.loadURL(origin); break }
    catch (error) {
      if (attempt === 3 || !/ERR_NETWORK_CHANGED|ERR_CONNECTION_REFUSED/.test(error.message)) throw error
      log('Retry local window navigation: ' + error.message)
      await new Promise(resolve => setTimeout(resolve, 700))
    }
  }
}

function currentExport(kind, collectionCode = 'gaoyi-first', exportKey) {
  if (exportKey) {
    if (!/^[0-9a-f]{32}$/.test(exportKey)) throw new Error('导出标识无效')
    const root=path.join(home,'output','banks',exportKey)
    const generation=JSON.parse(fs.readFileSync(path.join(root,'current.json'),'utf8')).generation
    if(!/^book-[0-9a-f]{32}$/.test(generation))throw new Error('导出版本无效')
    const folder=path.join(root,'versions',generation)
    const manifest=JSON.parse(fs.readFileSync(path.join(folder,'export_manifest.json'),'utf8'))
    const filename=manifest.files?.[kind]
    if(manifest.key!==exportKey || !['question','solution'].includes(kind) || typeof filename!=='string' || path.basename(filename)!==filename)throw new Error('导出文件无效')
    return path.join(folder,filename)
  }

  const namesByCollection = {
    'gaoyi-first': { question: '高一上学期数学难题整理_题目册.pdf', solution: '高一上学期数学难题整理_答案解析册.pdf' },
    'gaoyi-second': { question: '高一下学期数学难题整理_题目册.pdf', solution: '高一下学期数学难题整理_答案解析册.pdf' },
    'gaokao-first': { question: '高二上学期数学难题整理_题目册.pdf', solution: '高二上学期数学难题整理_答案解析册.pdf' },
    'gaokao-second': { question: '高二下学期数学难题整理_题目册.pdf', solution: '高二下学期数学难题整理_答案解析册.pdf' },
    'misc': { question: '其他专题数学题目册.pdf', solution: '其他专题数学解析册.pdf' },
  }
  const names = Object.hasOwn(namesByCollection, collectionCode) ? namesByCollection[collectionCode] : null
  if (!names) throw new Error('未知题库集合')
  if (!(kind in names)) throw new Error('未知导出类型')
  const pointer = JSON.parse(fs.readFileSync(path.join(home, 'output', `current-${collectionCode}.json`), 'utf8'))
  if (!/^book-[a-zA-Z0-9-]+$/.test(pointer.generation)) throw new Error('导出目录记录无效')
  const file = path.join(home, 'output', 'versions', collectionCode, pointer.generation, names[kind])
  const manifest = JSON.parse(fs.readFileSync(path.join(path.dirname(file), 'export_manifest.json'), 'utf8'))
  if (manifest.collection_code !== collectionCode) throw new Error('导出文件集合不匹配')
  if (!fs.existsSync(file)) throw new Error('尚无成功导出的文件')
  return file
}

function currentPaper(kind, bankId='system') {
  if(bankId!=='system'&&!/^[0-9a-f-]{36}$/.test(bankId))throw new Error('题库标识无效')
  const paperRoot=bankId==='system'?path.join(home,'output','papers'):path.join(home,'output','papers','banks',bankId)
  if (!['question', 'solution'].includes(kind)) throw new Error('未知训练卷类型')
  const pointer = JSON.parse(fs.readFileSync(path.join(paperRoot, 'current.json'), 'utf8'))
  if (typeof pointer.generation !== 'string' || !/^paper-[a-f0-9]{32}$/.test(pointer.generation)) throw new Error('训练卷目录记录无效')
  const folder = path.join(paperRoot, 'versions', pointer.generation)
  const base = fs.realpathSync(path.join(paperRoot, 'versions'))
  if (!fs.realpathSync(folder).startsWith(base + path.sep)) throw new Error('训练卷目录越界')
  const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'paper_manifest.json'), 'utf8'))
  if (manifest.generation !== pointer.generation) throw new Error('训练卷版本不匹配')
  const filename = manifest.files?.[kind]
  if (typeof filename !== 'string' || !new RegExp(`^高中数学训练卷_\\d{8}-\\d{6}_${kind === 'question' ? '题目卷' : '解析卷'}\\.pdf$`).test(filename)) throw new Error('训练卷文件名无效')
  const file = path.join(folder, filename)
  if (!fs.existsSync(file)) throw new Error('尚无成功生成的训练卷')
  return file
}

function registerHandlers() {
  const handle = (name, fn) => ipcMain.handle(name, async (event, ...args) => {
    if (event.sender !== window.webContents || !event.senderFrame.url.startsWith(origin + '/')) throw new Error('无效窗口请求')
    return fn(...args)
  })
  handle('desktop:agent-status', async () => ({ ...(await (await backendFetch('/api/agent/config')).json()), credential_warning: secrets.warning() }))
  handle('desktop:agent-save', async (key, prices) => {
    if (typeof key !== 'string' || !key.trim() || key.length > 512 || /[\r\n]/.test(key) || /[^\x21-\x7e]/.test(key.trim())) throw new Error('API Key 格式无效')
    if (prices !== undefined && (!prices || typeof prices !== 'object' || Object.keys(prices).some(name => !['input','cached_input','output'].includes(name)) || Object.values(prices).some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 10000))) throw new Error('参考单价格式无效')
    await secrets.save(key, prices)
    return (await backendFetch('/api/agent/credentials', { method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:key,prices}) })).json()
  })
  handle('desktop:app-info',()=>({version:app.getVersion(),program_directory:app.isPackaged?path.dirname(process.execPath):project,data_directory:path.join(home,'data')}))
  handle('desktop:import-source-load',sid=>sourcePreferences.load(sid))
  handle('desktop:import-source-save',(sid,value)=>sourcePreferences.save(sid,value))
  handle('desktop:agent-clear', async () => {
    await secrets.clear()
    return (await backendFetch('/api/agent/credentials', { method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:''}) })).json()
  })
  handle('desktop:choose-latex', async () => {
    const selection = await dialog.showOpenDialog(window, { title: '选择 xelatex.exe', properties: ['openFile'], filters: [{ name: 'XeLaTeX', extensions: ['exe'] }] })
    return selection.canceled ? null : selection.filePaths[0]
  })
  handle('desktop:export-file', async (kind, action, collectionCode, exportKey) => {
    const file = currentExport(kind, collectionCode, exportKey)
    if (action === 'open') {
      const error = await shell.openPath(file)
      if (error) throw new Error(error)
      return true
    }
    if (action !== 'save') throw new Error('未知文件操作')
    const selected = await dialog.showSaveDialog(window, { title: '另存为 PDF', defaultPath: path.basename(file), filters: [{ name: 'PDF', extensions: ['pdf'] }] })
    if (selected.canceled || !selected.filePath) return false
    if (path.resolve(selected.filePath) !== path.resolve(file)) await fs.promises.copyFile(file, selected.filePath)
    return true
  })
  handle('desktop:paper-file', async (kind, action, bankId) => {
    const file = currentPaper(kind,bankId)
    if (action === 'open') {
      const error = await shell.openPath(file)
      if (error) throw new Error(error)
      return true
    }
    if (action !== 'save') throw new Error('未知文件操作')
    const selected = await dialog.showSaveDialog(window, { title: '另存为训练卷 PDF', defaultPath: path.basename(file), filters: [{ name: 'PDF', extensions: ['pdf'] }] })
    if (selected.canceled || !selected.filePath) return false
    if (path.resolve(selected.filePath) !== path.resolve(file)) await fs.promises.copyFile(file, selected.filePath)
    return true
  })
  handle('desktop:open-folder', async (kind, collectionCode = 'gaoyi-first', exportKey) => {
    if (!['output', 'papers', 'logs', 'data'].includes(kind)) throw new Error('未知目录')
    let directory = path.join(home, kind)
    if(kind==='output' && exportKey) directory=path.dirname(currentExport('question',collectionCode,exportKey))
    if (kind === 'papers') {
      directory = path.join(home, 'output', 'papers', 'versions')
      try { directory = path.dirname(currentPaper('question')) } catch {}
    }
    if (kind === 'output' && !exportKey) {
      if (!['gaoyi-first', 'gaoyi-second', 'gaokao-first', 'gaokao-second', 'misc'].includes(collectionCode)) throw new Error('未知题库集合')
      directory = path.join(home, 'output', 'versions', collectionCode)
      try { directory = path.dirname(currentExport('question', collectionCode)) } catch {}
    }
    fs.mkdirSync(directory, { recursive: true })
    const error = await shell.openPath(directory)
    if (error) throw new Error(error)
  })
  handle('desktop:confirm-discard', async message => {
    if (typeof message !== 'string' || message.length > 3000) throw new Error('确认内容无效')
    const result = await dialog.showMessageBox(window, { type: 'warning', title: '丢弃草稿', message, buttons: ['保留草稿', '丢弃草稿'], defaultId: 0, cancelId: 0 })
    return result.response === 1
  })
  handle('desktop:confirm-delete', async message => {
    if (typeof message !== 'string' || message.length > 3000) throw new Error('确认内容无效')
    const result = await dialog.showMessageBox(window, { type: 'warning', title: '永久删除题目', message, buttons: ['取消', '永久删除'], defaultId: 0, cancelId: 0 })
    return result.response === 1
  })
}

let fatalShown = false
async function fatal(error) {
  log(error.stack || String(error))
  if (fatalShown || quitting) return
  fatalShown = true
  const result = await dialog.showMessageBox({ type: 'error', title: '题库应用无法继续运行', message: error.message || String(error), detail: '题库修改保存在 data 目录。可打开日志查看原因，然后重新启动。', buttons: ['关闭应用', '打开日志目录'] })
  if (result.response === 1) await shell.openPath(logDir)
  app.quit()
}

let preparingQuit = false
async function flushEditor() {
  if (!origin || !window || window.isDestroyed() || !window.webContents.getURL().startsWith(origin + '/')) return true
  return new Promise(resolve => {
    const requestId = crypto.randomUUID()
    const finish = ok => { clearTimeout(timer); ipcMain.removeListener('desktop:close-ready', listener); resolve(ok) }
    const listener = (event, id, ok) => {
      if (event.sender === window.webContents && event.senderFrame.url.startsWith(origin + '/') && id === requestId) finish(ok === true)
    }
    const timer = setTimeout(() => finish(false), 10000)
    ipcMain.on('desktop:close-ready', listener)
    window.webContents.send('desktop:prepare-close', requestId)
  })
}
app.on('before-quit', event => {
  if (quitting) return
  event.preventDefault()
  if (preparingQuit) return
  preparingQuit = true
  ;(async () => {
    if (!(await flushEditor())) {
      const result = await dialog.showMessageBox(window, { type: 'warning', title: '草稿尚未确认保存', message: '保存失败或等待超时。返回编辑可重试；仍然退出可能丢失最近的修改。', buttons: ['返回编辑', '仍然退出'], defaultId: 0, cancelId: 0 })
      if (result.response !== 1) { preparingQuit = false; return }
    }
    quitting = true
    if (backend && !stopped) {
      try { await backendFetch('/api/desktop/shutdown', { method: 'POST', signal: AbortSignal.timeout(2000) }) } catch {}
      backend.stdin.end()
      for (let i = 0; i < 40 && !stopped; i++) await new Promise(resolve => setTimeout(resolve, 100))
      if (!stopped) await new Promise(resolve => {
        const killer = spawn(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'), ['/PID', String(backend.pid), '/T', '/F'], { windowsHide: true })
        killer.on('exit', resolve); killer.on('error', resolve)
      })
    }
    app.quit()
  })()
})
app.on('window-all-closed', () => app.quit())
