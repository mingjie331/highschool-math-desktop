param([switch]$RealLatex, [switch]$Electron, [string]$Materials, [string]$TestData)
if ($Materials) { $env:QD_TEST_MATERIALS = $Materials }
if ($TestData) { $env:QD_TEST_DATA = $TestData }
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
$TestPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $TestPython)) { throw '请先按交接说明建立 .venv 并安装 requirements-build.txt，详情见 docs/开发交接.md' }
& $TestPython -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE) { throw '后台回归测试失败' }
node --experimental-strip-types --test tests/frontend.test.ts
if ($LASTEXITCODE) { throw '前端逻辑回归测试失败' }
node --test tests/secrets.test.cjs tests/source_preferences.test.cjs
if ($LASTEXITCODE) { throw '密钥存储回归测试失败' }
node scripts/prepare-assets.cjs
if ($LASTEXITCODE) { throw 'PDF.js 资源准备失败' }
npm.cmd --prefix frontend run build
if ($LASTEXITCODE) { throw '前端构建失败' }
if ($RealLatex) {
    & $TestPython tests/real_validation.py
    if ($LASTEXITCODE) { throw '真实 LaTeX 验证失败' }
}
if ($Electron) {
    Write-Output '维护发行包测试：候选包生成后单独运行 tests/update_134.py 与 tests/update_exit_134.e2e.cjs。'
    node tests/desktop.e2e.cjs
    if ($LASTEXITCODE) { throw '桌面交互回归失败' }
    node tests/agent.e2e.cjs
    if ($LASTEXITCODE) { throw 'AI录题桌面交互回归失败' }
    node tests/workbench_visual.e2e.cjs
    if ($LASTEXITCODE) { throw '核对工作台布局回归失败' }
    node tests/import_132.e2e.cjs
    if ($LASTEXITCODE) { throw 'PDF 实料界面回归失败' }
    node tests/ui_133.e2e.cjs
    if ($LASTEXITCODE) { throw '原图滚动、列表与题源回归失败' }
    node tests/review_keyboard.e2e.cjs
    if ($LASTEXITCODE) { throw '核对工作台键盘回归失败' }
}
