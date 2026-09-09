import assert from 'node:assert/strict'
import { formatCorpusCoverage, safeSourceUrl } from '../disciplineCorpusPresentation.js'
const text = formatCorpusCoverage({ eligible_chunks: 100, embedded_chunks: 40 })
assert.match(text, /40/)
assert.doesNotMatch(text, /全部完成/)

// 出处链接白名单：只放行 http/https，其余协议一律空串（不渲染链接）
assert.equal(safeSourceUrl('https://example.org/doc'), 'https://example.org/doc')
assert.equal(safeSourceUrl('http://example.org/doc'), 'http://example.org/doc')
assert.equal(safeSourceUrl('  https://example.org/doc  '), 'https://example.org/doc')
assert.equal(safeSourceUrl('javascript:alert(1)'), '')
assert.equal(safeSourceUrl('data:text/html,<script>alert(1)</script>'), '')
assert.equal(safeSourceUrl('ftp://example.org/doc'), '')
assert.equal(safeSourceUrl(''), '')
assert.equal(safeSourceUrl(null), '')
assert.equal(safeSourceUrl(undefined), '')
