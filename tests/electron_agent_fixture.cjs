const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const file = path.resolve(__dirname, '../desktop/main.cjs')
const source = fs.readFileSync(file, 'utf8').replace("['-m', 'backend.runner']", "['-m', 'tests.mock_agent_runner']")
const fixture = new Module(file, module)
fixture.filename = file
fixture.paths = Module._nodeModulePaths(path.dirname(file))
fixture._compile(source, file)
