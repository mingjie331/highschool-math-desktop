# 高中数学题库 · 1.4.0

支持自建独立题库的 Windows 本地桌面应用，使用 FastAPI/SQLite、React、Electron 和 XeLaTeX。支持分类浏览与搜索、题目编辑、草稿保存、AI 录题与人工核对、组卷及 PDF 导出。

公开源码自带 **627 道题、87 张配图**。首次启动将种子库复制到本机 `runtime/data` 的“系统题库”，再迁移至 schema 9；不会修改仓库中的种子库。个人题库、试卷原材料、API 密钥和运行缓存不在仓库中。

## 同学快速上手

已验证环境：**Windows x64、Python 3.13 x64、Node.js 24 x64、Git**。先确认 `python --version` 与 `node --version`。首次安装需要访问 PyPI、npm 和 GitHub 下载依赖。

```powershell
git clone https://github.com/mingjie331/highschool-math-desktop.git
cd highschool-math-desktop
npm run setup
npm start
```

初始化脚本建立 `.venv`，按依赖清单和 npm 锁文件安装依赖，下载并校验 Electron，复制 PDF.js 字体资源，构建前端。无需激活虚拟环境。如果 `python` 指向另一个版本，可指定解释器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-dev.ps1 -PythonCommand "C:\你的Python313目录\python.exe"
```

浏览、搜索无需 API 密钥。**编辑保存、数学预览、组卷和 PDF 导出需要 XeLaTeX**：安装 TeX Live 或 MiKTeX，并具备 `ctex`、`xeCJK`、`amsmath` 等模板宏包以及 Windows 中文字体（宋体、黑体、楷体、仿宋）。在应用“设置”中选择 `xelatex.exe` 并运行编译测试。当前模板使用 Windows 字体，其他系统尚未验证。

AI 识别和补全由每位同学在自己的“AI 设置”中填写 DeepSeek API 密钥，会向远程服务发送所选内容并产生费用。密钥由 Electron 系统加密后保存于本机运行目录；不需要 `.env`，也不要把密钥写进源码、截图、Issue 或 PR。

## 开发入口

| 目录 | 负责的内容 |
|---|---|
| `frontend/src` | 题库界面、AI 任务与核对工作台、PDF 预览、类型与 API 调用 |
| `backend` | HTTP 接口、SQLite 与迁移、AI 流程、LaTeX 编译、组卷与导出 |
| `desktop` | Electron 启动、后台生命周期、IPC、本机密钥和文件操作 |
| `resources` | 只读种子库、配图、LaTeX 模板 |
| `scripts` | 初始化、提交检查、构建、打包、安装迁移和更新工具 |
| `tests`、`docs` | 隔离回归测试、使用说明和开发交接 |

`npm start` 启动 Electron，并自动启动 Python 后台。它使用构建后的前端，**不会自动热更新**；修改前端后先执行 `npm --prefix frontend run build`，再重启应用。`frontend` 的 Vite 开发代理指向本机 8765 端口，需要另行启动后台，不属于默认启动流程。

[开发交接](docs/开发交接.md) · [协作约定](CONTRIBUTING.md) · [使用说明](docs/使用说明.md) · [目录与更新](docs/目录与更新.md) · [第三方组件](docs/第三方组件说明.md) · [公开交接验证](docs/公开交接验证.md)

## 测试与提交

```powershell
npm test
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1 -Electron
git add backend frontend desktop resources scripts tests docs README.md CONTRIBUTING.md package.json package-lock.json requirements.txt requirements-build.txt build.ps1 .gitignore .gitattributes
npm run audit:public
```

普通测试使用临时题库与模拟 AI，不调用付费 API；桌面回归需要可用的 XeLaTeX。`audit:public` 检查 **Git 索引中即将提交的内容**，包含源码覆盖、敏感文件、密钥特征、种子库哈希及配图完整性，失败时应先修复再提交。源码 ZIP 收集范围由 `scripts/release-manifest.json` 统一维护。

私有 PDF 测试材料不公开；相关测试会明确记录跳过。需要自行补充材料时使用 `-Materials` 或 `QD_TEST_MATERIALS`，候选库用 `QD_TEST_DATA`，旧安装包用 `QD_TEST_OLD_APP`，均使用隔离副本。`tests/live_*.cjs`、真实 AI 验证脚本不是普通回归入口，运行前须自行检查密钥来源、材料和预算。

## 常见问题

- `python`/`node` 找不到：安装上述版本并重新打开终端；多个 Python 并存时使用 `-PythonCommand`。
- Git 克隆无法连接 GitHub：使用能访问 GitHub 的网络，或让 Git 命令使用你自己的 `HTTPS_PROXY`；不要提交本机代理配置或密码。
- Electron 下载失败：确认能访问 GitHub，重新运行 `npm run setup`；下载脚本自动使用环境变量或 Windows 系统中已启用的代理，校验哈希并恢复未完成下载。不要把代理密码写进源码。
- PDF 不显示：运行 `node scripts/prepare-assets.cjs` 和 `npm --prefix frontend run build` 后重启。
- 保存或导出提示 XeLaTeX 不可用：在设置中指定解释器并测试；缺少宏包或字体时先修复 TeX 环境。
- 从别人电脑复制的 API 配置不可解密：在自己电脑重新填写密钥，题库数据不受影响。

## 构建与数据保护

`powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1` 生成 Windows 包和源码 ZIP，写入 `build` 暂存。验收后可运行 `.venv/Scripts/python.exe scripts/release_tools.py --publish` 发布到新的 `release/<版本>`；已发行版本不能覆盖。

`runtime`、`.local`、`.cache`、`data`、`output`、`logs`、`test-results` 和构建产物均不提交。不要清空日常安装的 `data/.cache/output/logs`，也不要将个人数据写回 `resources/seed`。本次公开不附加新的开源许可证，第三方组件许可见组件说明。


## 1.4.0 题库与录题

本次验收范围与迁移结果见 [1.4.0 验证记录](docs/1.4.0验证.md)。

左侧先选择题库，再选学期、专题和考点。“新建 / 管理题库”可创建空题库、重命名、删除空题库，并批量移动或复制题目。移动保留 ID，复制可独立修改；带编辑草稿的题目需先处理草稿。旧版本题目和草稿全部保留在系统题库。

搜索默认当前题库，也可选全部题库搜索。每个题库拥有独立组卷区和导出结果；导出可选学期、专题、考点或勾选题目。LaTeX 源码面板可独立滚动至解析末尾。

AI 原材料支持单 PDF 1–35 页、32 MiB；一批识别仍最多 20 页（含答案页）、50 道题。导入自动选前面的剩余额度，全选最多 20 页，取消选择不删除原材料。超过 20 页的文件分批选择。新任务固定归属当前题库。

升级到 schema 9 前会备份数据库，旧程序无法打开新版数据。回退必须恢复匹配的旧程序和升级前数据库，不能仅替换旧 exe。
