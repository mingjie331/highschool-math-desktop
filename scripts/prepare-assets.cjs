const fs = require('node:fs')
const path = require('node:path')
const root = path.resolve(__dirname, '..')
for (const name of ['cmaps', 'standard_fonts', 'wasm']) {
  fs.cpSync(path.join(root, 'frontend/node_modules/pdfjs-dist', name), path.join(root, 'frontend/public/pdfjs', name), { recursive: true })
}
