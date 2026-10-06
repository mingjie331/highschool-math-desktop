# 同学协作约定

先按 [README](README.md) 启动项目，了解 [开发交接](docs/开发交接.md) 中的运行链路。公开仓库为 `mingjie331/highschool-math-desktop`，主分支为 `main`。

## 提交一个功能

```powershell
git switch main
git pull --ff-only
git switch -c feature/你的功能名
# 修改、验证后，仅暂存需要的文件
git add <本次修改的文件>
npm test
npm run audit:public
git diff --cached --stat
git commit -m "说明用户能观察到的改进"
git push -u origin feature/你的功能名
```

随后发起 Pull Request，说明解决什么问题、如何验证，以及数据库或依赖是否变化。没有仓库写权限时先 Fork，在自己的仓库提交，再向本仓库提出 PR。公开 Issue/PR 不附带个人试卷、题库副本、真实密钥或完整运行日志。新增顶层文件时同步更新源码发行清单，提交检查会提示遗漏或未授权的范围。

## 验证与数据

普通回归不需要真实 API 密钥。修改桌面、编辑器、核对工作台或 PDF 行为时补跑 `scripts/test.ps1 -Electron`，需要 XeLaTeX。私有材料测试未执行时在 PR 中明确写“因缺少材料跳过”，不要写成已通过。

每位同学使用自己的运行数据与 API 设置；不要共享 `runtime`、`.local`、`test-results`、加密凭据或 Electron 解密上下文。测试使用隔离副本，不能修改日常安装数据。新增或更改测试应使用自编题目和模拟 AI，避免自动产生远程费用。

数据库 schema 变更要提供迁移与旧数据保留测试。种子库和配图是只读基线，正常功能开发不修改它们。依赖更新需同时维护对应锁文件并单独说明，不提交 `node_modules` 或虚拟环境。

上传前先暂存，再运行 `audit:public`；它检查索引中的真实提交字节，失败时先解除敏感文件暂存或修复源码，再提交。该检查针对常见密钥特征和文件范围，仍须人工检查新增配置、截图和材料。如果真实密钥曾进入公开历史，应立即撤销或轮换密钥，仅删除当前文件不能消除历史泄露。

本仓库暂未新增开源许可证；公开可见不等同于授予任意再分发许可，第三方组件遵守各自许可。新增协作者权限由仓库所有者管理。
