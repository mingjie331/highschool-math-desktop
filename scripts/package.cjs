const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const { packager } = await import('@electron/packager')
  const root = path.resolve(__dirname, '..')
  const stage = path.join(root, 'build', 'electron-app')
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'scripts/release-manifest.json'),'utf8'))
  fs.mkdirSync(stage, { recursive: true })
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))
  fs.writeFileSync(path.join(stage, 'package.json'), JSON.stringify({ name: pkg.name, productName: pkg.productName, version: pkg.version, main: pkg.main }))
  fs.cpSync(path.join(root, 'desktop'), path.join(stage, 'desktop'), { recursive: true, filter: src => !src.includes('tests') && !src.includes('playwright.config') })
  const outputs = await packager({
    dir: stage, name: pkg.productName, executableName: pkg.productName, platform: 'win32', arch: 'x64',
    electronVersion: require('electron/package.json').version, out: path.join(root, 'build', 'apps', pkg.version), overwrite: true,
    electronZipDir: path.join(root, 'build/downloads'),
    asar: true, icon: path.join(root, 'desktop/icon.ico'), win32metadata: { CompanyName: '本地题库', FileDescription: pkg.productName, ProductName: pkg.productName },
  })
  for (const folder of outputs) {
    const payload = path.join(folder, 'resources', 'payload')
    fs.cpSync(path.join(root, 'resources'), path.join(payload, 'resources'), { recursive: true, filter: src => !src.endsWith('-wal') && !src.endsWith('-shm') })
    fs.cpSync(path.join(root, 'frontend/dist'), path.join(payload, 'frontend/dist'), { recursive: true })
    fs.cpSync(path.join(root, 'build/backend-runtime/question-backend'), path.join(payload, 'backend-runtime'), { recursive: true })
    for(const doc of manifest.documents){const target=path.join(folder,doc.target);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,doc.source),target)}
    fs.copyFileSync(path.join(root,'README.md'),path.join(folder,'README.md'))
    const validation=manifest.validation_directory.replace('{version}',pkg.version)
    if(fs.existsSync(path.join(root,validation)))fs.cpSync(path.join(root,validation),path.join(folder,validation),{recursive:true})
    for(const name of manifest.runtime_tools){const target=path.join(folder,'tools',name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(root,'scripts',name),target)}
    fs.writeFileSync(path.join(folder,'本地更新.cmd'),'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\\update_app.ps1" -Target "%~dp0." %*\r\nif errorlevel 1 pause\r\n','utf8')
    console.log('Packaged:', folder)
  }
}
main().catch(error => { console.error(error); process.exit(1) })
