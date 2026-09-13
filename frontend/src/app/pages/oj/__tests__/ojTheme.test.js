import test from 'node:test'
import assert from 'node:assert/strict'

import {
  OJ_DIFFICULTY_ORDER,
  buildProblemNoIndex,
  difficultyMeta,
  formatMemoryLimit,
  formatPassRate,
  formatProblemNo,
  formatTimeLimit,
  passRateWidth,
  sortProblems,
  tagColor,
} from '../ojTheme.js'

test('difficultyMeta: 三档各映射到洛谷色板，未标注走灰色兜底', () => {
  assert.equal(difficultyMeta('easy').label, '普及')
  assert.equal(difficultyMeta('easy').color, '#F39C11')
  assert.equal(difficultyMeta('medium').label, '提高')
  assert.equal(difficultyMeta('medium').color, '#3498DB')
  assert.equal(difficultyMeta('hard').label, '省选/NOI-')
  assert.equal(difficultyMeta('hard').color, '#9D3DCF')

  // 大小写与空白容错
  assert.equal(difficultyMeta(' HARD ').label, '省选/NOI-')

  // 兜底：空 / 未知名 / null 都不得抛错，也不得冒充成某一档
  for (const value of [null, undefined, '', 'impossible']) {
    const meta = difficultyMeta(value)
    assert.equal(meta.label, '暂无评定')
    assert.equal(meta.order, 0)
  }
})

test('difficultyMeta: 三档 order 严格递增（排序与区间筛选依赖它）', () => {
  const orders = OJ_DIFFICULTY_ORDER.map((key) => difficultyMeta(key).order)
  assert.deepEqual(orders, [1, 2, 3])
  // 未标注必须小于所有真实档位，否则「暂无评定」会排到「简单」后面
  assert.ok(difficultyMeta(null).order < Math.min(...orders))
})

test('tagColor: 同一标签恒定同色，不同进程/不同会话不得漂移', () => {
  const first = tagColor('动态规划')
  for (let i = 0; i < 50; i += 1) assert.equal(tagColor('动态规划'), first)
  // 空标签不得抛错
  assert.ok(tagColor('').startsWith('#'))
  assert.ok(tagColor(null).startsWith('#'))
})

test('tagColor: 纯年份标签走橙色专色（复刻截图里年份 chip 与来源 chip 的区分）', () => {
  assert.equal(tagColor('2015'), '#E67E22')
  assert.equal(tagColor('2026'), '#E67E22')
  // 含年份但不是纯年份的标签不享受专色 —— 否则「Google Code Jam 2015」会误判
  assert.notEqual(tagColor('Google Code Jam 2015'), '#E67E22')
  assert.notEqual(tagColor('12015'), '#E67E22')
})

test('formatProblemNo: 补零到三位，非法序号给占位而不是 NaN', () => {
  assert.equal(formatProblemNo(1), '#001')
  assert.equal(formatProblemNo(15), '#015')
  assert.equal(formatProblemNo(999), '#999')
  assert.equal(formatProblemNo(1000), '#1000')
  assert.equal(formatProblemNo(0), '—')
  assert.equal(formatProblemNo(-3), '—')
  assert.equal(formatProblemNo(Number.NaN), '—')
  assert.equal(formatProblemNo('abc'), '—')
})

test('buildProblemNoIndex: 相同题目集合产出相同编号（顺序不随入参顺序变）', () => {
  const a = [{ experiment_id: 'exp_c' }, { experiment_id: 'exp_a' }, { experiment_id: 'exp_b' }]
  const b = [{ experiment_id: 'exp_b' }, { experiment_id: 'exp_c' }, { experiment_id: 'exp_a' }]
  const indexA = buildProblemNoIndex(a)
  const indexB = buildProblemNoIndex(b)
  assert.equal(indexA.get('exp_a'), '#001')
  assert.equal(indexA.get('exp_b'), '#002')
  assert.equal(indexA.get('exp_c'), '#003')
  for (const key of indexA.keys()) assert.equal(indexA.get(key), indexB.get(key))
})

test('buildProblemNoIndex: 编号源必须是未筛选的全量目录 —— 筛掉中间题号不得让其余题号平移', () => {
  const catalog = [
    { experiment_id: 'exp_a' },
    { experiment_id: 'exp_b' },
    { experiment_id: 'exp_c' },
  ]
  const fullIndex = buildProblemNoIndex(catalog)
  // 模拟「筛完之后只剩 exp_a / exp_c」——页面仍要用全量索引查号
  const filtered = catalog.filter((item) => item.experiment_id !== 'exp_b')
  assert.equal(filtered.length, 2)
  assert.equal(fullIndex.get('exp_c'), '#003')
  // 反向验证：如果错用筛选后的结果编号，exp_c 会变成 #002（这正是要拦的退化）
  assert.equal(buildProblemNoIndex(filtered).get('exp_c'), '#002')
})

test('buildProblemNoIndex: 重复 id 只占一个号；空输入返回空 Map', () => {
  const index = buildProblemNoIndex([
    { experiment_id: 'exp_a' },
    { experiment_id: 'exp_a' },
    { experiment_id: 'exp_b' },
  ])
  assert.equal(index.size, 2)
  assert.equal(index.get('exp_b'), '#002')
  assert.equal(buildProblemNoIndex(null).size, 0)
  assert.equal(buildProblemNoIndex([{ experiment_id: '' }]).size, 0)
})

test('formatMemoryLimit: Judge0 的 KB 换算成 MB（不换算会显示 128000）', () => {
  assert.equal(formatMemoryLimit(128000), '125.00MB')
  assert.equal(formatMemoryLimit(64000), '62.50MB')
  assert.equal(formatMemoryLimit(1024), '1.00MB')
  assert.equal(formatMemoryLimit(0), null)
  assert.equal(formatMemoryLimit(null), null)
  assert.equal(formatMemoryLimit('nope'), null)
})

test('formatTimeLimit: 两位小数 + s 后缀', () => {
  assert.equal(formatTimeLimit(1), '1.00s')
  assert.equal(formatTimeLimit(2.5), '2.50s')
  assert.equal(formatTimeLimit(0), null)
  assert.equal(formatTimeLimit(undefined), null)
})

test('formatPassRate / passRateWidth: 无通过率不许编成 0%', () => {
  assert.equal(formatPassRate(0.632), '63.2%')
  assert.equal(formatPassRate(0), '0.0%')
  assert.equal(formatPassRate(null), null)
  assert.equal(formatPassRate(undefined), null)

  assert.equal(passRateWidth(0.5), '50.0%')
  // 极小值保留 2% 可见宽度，否则条形图看起来像渲染失败
  assert.equal(passRateWidth(0.0001), '2.0%')
  assert.equal(passRateWidth(0), '0%')
  assert.equal(passRateWidth(null), '0%')
})

test('sortProblems: 无数据的行永远沉底，降序也不翻到最前', () => {
  const items = [
    { title: 'a', pass_rate: 0.1 },
    { title: 'b', pass_rate: null },
    { title: 'c', pass_rate: 0.9 },
    { title: 'd' },
  ]
  assert.deepEqual(
    sortProblems(items, { sortBy: 'pass_rate', sortOrder: 'asc' }).map((i) => i.title),
    ['a', 'c', 'b', 'd'],
  )
  assert.deepEqual(
    sortProblems(items, { sortBy: 'pass_rate', sortOrder: 'desc' }).map((i) => i.title),
    ['c', 'a', 'b', 'd'],
  )
})

test('sortProblems: 难度按档位而非字典序；题号按派生号排序', () => {
  const items = [
    { experiment_id: 'exp_c', difficulty: 'hard' },
    { experiment_id: 'exp_a', difficulty: 'easy' },
    { experiment_id: 'exp_b', difficulty: 'medium' },
  ]
  const noOf = (p) => buildProblemNoIndex(items).get(p.experiment_id)
  assert.deepEqual(
    sortProblems(items, { sortBy: 'difficulty' }).map((i) => i.difficulty),
    ['easy', 'medium', 'hard'],
  )
  assert.deepEqual(
    sortProblems(items, { sortBy: 'no', problemNoOf: noOf }).map((i) => i.experiment_id),
    ['exp_a', 'exp_b', 'exp_c'],
  )
  // 字典序会得到 hard < medium（h < m），难度排序若不走档位就会错
  assert.notDeepEqual(
    [...items].map((i) => i.difficulty).sort(),
    ['easy', 'medium', 'hard'],
  )
})

test('sortProblems: 未知排序列与空输入原样返回，不得抛错', () => {
  const items = [{ title: 'b' }, { title: 'a' }]
  assert.deepEqual(sortProblems(items, { sortBy: 'default' }).map((i) => i.title), ['b', 'a'])
  assert.deepEqual(sortProblems(items, { sortBy: 'nope' }).map((i) => i.title), ['b', 'a'])
  assert.deepEqual(sortProblems(null), [])
  // 不得就地改写入参
  const original = [{ title: 'b' }, { title: 'a' }]
  sortProblems(original, { sortBy: 'title' })
  assert.deepEqual(original.map((i) => i.title), ['b', 'a'])
})
