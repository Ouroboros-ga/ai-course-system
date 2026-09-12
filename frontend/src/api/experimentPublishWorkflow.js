/**
 * 实验任务设定工作台的分段模型（四段式，可任意跳转，不强制线性）。
 *
 * 与旧六步向导的区别：参考解预览 / 锁定版本 / 发布不再各占一屏，而是合并进
 * 「发布检查」段的一张清单 —— 对教师而言它们是同一件事的三道门槛，不是三次
 * 独立的创作动作。前四步（名称 → 用例 → 限制）才是真正要填的内容。
 */

export const EXPERIMENT_SECTIONS = ['basics', 'tests', 'limits', 'publish']

export const EXPERIMENT_SECTION_LABELS = {
  basics: '基本信息',
  tests: '测试用例',
  limits: '运行限制',
  publish: '发布检查',
}

/**
 * 打开某个任务时默认落到哪一段。
 *
 * - 尚无版本：测试用例（基本信息已在创建时落库，接下来是出题）。
 * - 已有版本：发布检查（剩下的动作是预览 → 锁定 → 发布）。
 * - 已发布：发布检查（回看 + 需要改动时以新版本重做）。
 */
export function resolveExperimentSection(definition) {
  if (!definition) return 'basics'
  if (definition.publish_status === 'published') return 'publish'
  return definition.default_version_id ? 'publish' : 'tests'
}

/**
 * 发布检查段的目标版本：优先最新未锁定版本（可继续预览与锁定），
 * 其次当前生效版本（已锁定），最后回退到最新版本。
 *
 * 版本不可变（服务端 PUT /versions/{id} 只改标签与证据开关），所以改动测试集
 * 的唯一途径是再创建一个版本；这里始终把目标指向"还能动的那个版本"。
 */
export function pickTargetVersion(versions) {
  if (!Array.isArray(versions) || versions.length === 0) return null
  const byNewest = [...versions].sort(
    (a, b) => Number(b.version_number ?? 0) - Number(a.version_number ?? 0),
  )
  const unlocked = byNewest.find((version) => version.is_locked === false)
  if (unlocked) return unlocked
  const active = byNewest.find((version) => version.is_active === true)
  return active ?? byNewest[0]
}

/**
 * 把 1.0 总权重平均分配给 count 条用例，结果以「分」为单位整除后再落回小数，
 * 保证求和精确等于 1.00 —— 服务端 create_version 用 1e-9 容差校验权重和，
 * 手动凑数最容易在这里翻车，所以默认走自动分配。
 *
 * count=3 → [0.34, 0.33, 0.33]；count=15 → 10 条 0.07 + 5 条 0.06。
 */
export function distributeWeights(count) {
  if (!Number.isInteger(count) || count <= 0) return []
  if (count === 1) return [1]
  const baseCents = Math.floor(100 / count)
  const remainder = 100 - baseCents * count
  return Array.from({ length: count }, (_, index) => (
    (baseCents + (index < remainder ? 1 : 0)) / 100
  ))
}

/** 权重和是否满足服务端校验（容差与 experiment_service 保持一致）。 */
export function isWeightTotalValid(testCases) {
  const total = (Array.isArray(testCases) ? testCases : [])
    .reduce((sum, testCase) => sum + Number(testCase?.weight ?? 0), 0)
  return Math.abs(total - 1) <= 1e-9
}
