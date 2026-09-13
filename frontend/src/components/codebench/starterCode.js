/**
 * 起始代码归一化。
 *
 * 后端 `starter_code` 是 `{language: code}` 字典（教师按语言填写），
 * 而编辑器 / 提交链要的是纯字符串。直接把字典塞进 `sourceCode`
 * 会让 `.trim()` 抛错、CodeMirror 崩溃 —— 答题区整体消失。
 * （2026-09-13 线上复核：有题面、无答题区、无提交的根因。）
 */
export function pickStarterCode(starterCode, language) {
  if (!starterCode) return ''
  if (typeof starterCode === 'string') return starterCode
  if (typeof starterCode === 'object') {
    if (language && typeof starterCode[language] === 'string') {
      return starterCode[language]
    }
    const first = Object.values(starterCode).find((v) => typeof v === 'string')
    return first || ''
  }
  return ''
}
