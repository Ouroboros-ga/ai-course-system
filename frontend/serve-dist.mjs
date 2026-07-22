import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { extname, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('./dist', import.meta.url))
const port = Number(process.env.PORT || 4173)
const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
}

createServer(async (req, res) => {
  try {
    let urlPath = decodeURIComponent((req.url || '/').split('?')[0])
    let filePath = normalize(join(root, urlPath))
    if (!filePath.startsWith(root)) { res.writeHead(403); return res.end('Forbidden') }
    let data
    try {
      data = await readFile(filePath)
      if (data.length === 0 && urlPath.endsWith('/')) throw new Error('dir')
    } catch {
      // SPA fallback to index.html for client-side routes
      data = await readFile(join(root, 'index.html'))
      res.writeHead(200, { 'Content-Type': mime['.html'] })
      return res.end(data)
    }
    res.writeHead(200, { 'Content-Type': mime[extname(filePath)] || 'application/octet-stream' })
    res.end(data)
  } catch (e) {
    res.writeHead(500); res.end('Server error')
  }
}).listen(port, () => console.log(`Preview (dist, no /api proxy): http://localhost:${port}/`))
