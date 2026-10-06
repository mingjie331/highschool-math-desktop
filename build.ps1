param([switch]$Publish)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$BuildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $BuildPython)) {
    python -m venv .venv
    if ($LASTEXITCODE) { throw '创建 Python 环境失败' }
}
& $BuildPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE) { throw '安装 Python 依赖失败' }
npm.cmd ci --ignore-scripts
if ($LASTEXITCODE) { throw '安装桌面依赖失败' }
& $BuildPython scripts/download_electron.py
if ($LASTEXITCODE) { throw '下载桌面运行环境失败' }
Push-Location frontend
try { npm.cmd ci; if ($LASTEXITCODE) { throw '安装前端依赖失败' } } finally { Pop-Location }
node scripts/prepare-assets.cjs
if ($LASTEXITCODE) { throw '复制 PDF 资源失败' }
npm.cmd --prefix frontend run build
if ($LASTEXITCODE) { throw '前端构建失败' }
& $BuildPython -m unittest discover -s tests -p 'test_*.py'
if ($LASTEXITCODE) { throw '后台回归测试失败' }
node --experimental-strip-types --test tests/frontend.test.ts
if ($LASTEXITCODE) { throw '前端逻辑回归测试失败' }
node --test tests/secrets.test.cjs tests/source_preferences.test.cjs
if ($LASTEXITCODE) { throw '密钥存储回归测试失败' }
& $BuildPython scripts/make_icon.py
if ($LASTEXITCODE) { throw '图标生成失败' }
& $BuildPython scripts/collect_licenses.py
if ($LASTEXITCODE) { throw '许可收集失败' }
& $BuildPython scripts/build_backend.py
if ($LASTEXITCODE) { throw '后台打包失败' }
node scripts/package.cjs
if ($LASTEXITCODE) { throw '桌面打包失败' }
& $BuildPython scripts/zip_release.py
if ($LASTEXITCODE) { throw 'ZIP 生成失败' }
& $BuildPython scripts/zip_sources.py
if ($LASTEXITCODE) { throw '源码 ZIP 生成失败' }

& $BuildPython scripts/release_tools.py --manifests
if ($LASTEXITCODE) { throw '发行清单生成失败' }
if ($Publish) { & $BuildPython scripts/release_tools.py --publish; if ($LASTEXITCODE) { throw '发行发布失败' } }
