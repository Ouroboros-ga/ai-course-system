#!/usr/bin/env node
/**
 * Shadow Frontend — 端到端冒烟（Vertical Slice 0.1）。
 *
 * 无浏览器自动化环境，采用构建产物级冒烟：起一个静态服务托管 dist，
 * 对关键 SPA 路由与静态资源做断言，验证影子前端确实编译产出且路由可达。
 *
 * 用法：
 *   VITE_ENABLE_SHADOW_FRONTEND=true npm run build
 *   npm run smoke:app
 *
 * 断言：
 *  1) / 与 /app 及其子路由均返回 index.html（SPA 回退）；
 *  2) 构建产物中存在含 `.sfx` 令牌作用域的 CSS（token 隔离已落地）；
 *  3) 至少一个 JS chunk 含影子前端路由路径串（/app/courses/learning）；
 *  4) 旗关闭构建（VITE_ENABLE_SHADOW_FRONTEND 未设）→ /app 仍可访问并回落。
 *
 * 任一断言失败 → 非零退出。
 */
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { join, extname, normalize } from 'node:path'

const DIST = process.env.SMOKE_DIST || join(process.cwd(), 'dist')
const PORT = Number(process.env.SMOKE_PORT) || 4319
const HOST = '127.0.0.1'

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
}

const SHADOW_BUILT = process.env.VITE_ENABLE_SHADOW_FRONTEND === 'true'
  || process.env.SMOKE_EXPECT_SHADOW === '1'

async function serve() {
  const server = createServer(async (req, res) => {
    try {
      let urlPath = decodeURIComponent((req.url || '/').split('?')[0])
      let filePath = normalize(join(DIST, urlPath))

      if (urlPath.endsWith('/')) {
        filePath = join(filePath, 'index.html')
      } else {
        const s = await stat(filePath).catch(() => null)
        if (!s || s.isDirectory()) {
          // SPA 回退：所有未命中静态文件的路径返回 index.html
          filePath = join(DIST, 'index.html')
        }
      }

      const body = await readFile(filePath)
      res.writeHead(200, { 'Content-Type': MIME[extname(filePath)] || 'application/octet-stream' })
      res.end(body)
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain' })
      res.end('not found')
    }
  })

  await new Promise((r) => server.listen(PORT, HOST, r))
  return server
}

async function fetchText(path) {
  const res = await fetch(`http://${HOST}:${PORT}${path}`)
  const text = await res.text()
  return { status: res.status, text }
}

async function readAssets() {
  const { readdir } = await import('node:fs/promises')
  const cssDir = join(DIST, 'assets')
  const files = await readdir(cssDir).catch(() => [])
  const cssFiles = files.filter((f) => f.endsWith('.css'))
  const jsFiles = files.filter((f) => f.endsWith('.js'))
  const readAll = async (names) =>
    Promise.all(names.map((n) => readFile(join(cssDir, n), 'utf8').catch(() => '')))
  return {
    cssText: (await readAll(cssFiles)).join('\n'),
    jsText: (await readAll(jsFiles)).join('\n'),
  }
}

const results = []
function check(name, ok, detail = '') {
  results.push({ name, ok, detail })
  const mark = ok ? 'PASS' : 'FAIL'
  console.log(`  ${ok ? '\u2713' : '\u2717'} [${mark}] ${name}${detail ? ' — ' + detail : ''}`)
}

async function main() {
  console.log(`\nShadow Frontend 端到端冒烟\n  dist: ${DIST}\n  shadow built: ${SHADOW_BUILT}\n`)

  const exists = await stat(DIST).catch(() => null)
  if (!exists || !exists.isDirectory()) {
    console.error(`\n\u2717 dist 目录不存在：${DIST}\n  请先运行：VITE_ENABLE_SHADOW_FRONTEND=true npm run build\n`)
    process.exit(1)
  }

  const server = await serve()

  try {
    // 1) SPA 路由回退
    const home = await fetchText('/')
    check('GET / 返回 200', home.status === 200, `status=${home.status}`)
    check('GET / 含 #app 挂载点', home.text.includes('id="app"'), '')

    const appHome = await fetchText('/app')
    check('GET /app 返回 200（SPA 回退）', appHome.status === 200, `status=${appHome.status}`)

    const learn = await fetchText('/app/course/1/learn')
    check('GET /app/course/1/learn 返回 200', learn.status === 200, `status=${learn.status}`)

    // 2 & 3) 构建产物内容断言
    const { cssText, jsText } = await readAssets()

    if (SHADOW_BUILT) {
      check('CSS 产物含 .sfx 令牌作用域', cssText.includes('.sfx'), 'token 隔离层已随 AppShell 分包')
      check('CSS 产物含 Academic Ink 主色 #14213D', cssText.includes('#14213D'), '')
      check('JS 产物含 /app/courses/learning 路由串', jsText.includes('/app/courses/learning'), '')
      check('JS 产物含 learnMachine 状态（LEARN）', jsText.includes('LEARN'), '')
    } else {
      check('旗关闭构建：CSS 不含 .sfx（影子前端未启用）', !cssText.includes('.sfx'), '符合预期')
    }

    const passed = results.filter((r) => r.ok).length
    const failed = results.length - passed
    console.log(`\n  结果：${passed} 通过 / ${failed} 失败\n`)

    if (failed > 0) process.exit(1)
  } finally {
    server.close()
  }
}

main().catch((e) => {
  console.error('\n冒烟执行异常：', e)
  process.exit(1)
})
