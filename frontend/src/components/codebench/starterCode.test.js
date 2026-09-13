import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { pickStarterCode } from './starterCode.js'

describe('pickStarterCode', () => {
  it('字典按语言精确命中', () => {
    assert.equal(
      pickStarterCode({ python3: 'print(1)', 'c++': 'int main(){}' }, 'c++'),
      'int main(){}',
    )
  })

  it('字典无该语言时回退第一段字符串（不抛、不返回对象）', () => {
    const got = pickStarterCode({ python3: 'print(1)' }, 'java')
    assert.equal(got, 'print(1)')
  })

  it('空字典/空值一律回空串', () => {
    assert.equal(pickStarterCode({}, 'python3'), '')
    assert.equal(pickStarterCode(null, 'python3'), '')
    assert.equal(pickStarterCode(undefined, 'python3'), '')
  })

  it('字符串原样透传（兼容旧形态）', () => {
    assert.equal(pickStarterCode('print(2)', 'python3'), 'print(2)')
  })

  it('非字符串值被跳过', () => {
    assert.equal(pickStarterCode({ python3: 42 }, 'python3'), '')
  })
})
