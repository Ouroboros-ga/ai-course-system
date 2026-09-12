const scoped = (courseId) => encodeURIComponent(courseId)
const resource = (value) => encodeURIComponent(value)

const numeric = (value) => Number(value)

export function experimentPublishPaths(courseId, experimentId, versionId) {
  const course = scoped(courseId)
  const experiment = resource(experimentId)
  const version = resource(versionId)
  return {
    definitions: `/experiments/course/${course}/definitions`,
    definition: `/experiments/course/${course}/definitions/${experiment}`,
    versions: `/experiments/${experiment}/versions?course_id=${course}`,
    preview: `/experiments/versions/${version}/reference-preview?course_id=${course}`,
    lock: `/experiments/versions/${version}/lock?course_id=${course}`,
    publish: `/experiments/course/${course}/definitions/${experiment}/publish`,
  }
}

export function buildVersionRequest(form) {
  return {
    label: String(form.label ?? '').trim(),
    cpu_time_limit: numeric(form.cpuTimeLimit),
    memory_limit: numeric(form.memoryLimit),
    wall_time_limit: numeric(form.wallTimeLimit),
    max_processes: numeric(form.maxProcesses),
    max_file_size: numeric(form.maxFileSize),
    passing_score: 1.0,
    // F1c：是否计入学习证据。缺省 true（与后端模型默认一致）；教师显式关闭后
    // 成绩仅记分，不写 LearningEvidence（B3 静默门的可视化对应项见出题页 F1d）。
    writes_formal_evidence: form.writesFormalEvidence !== false,
    // F1b：起始代码 {language: source}。只做形状消毒，服务端再截断；
    // 学生工作台重置时按语言取用，无对应语言回退空编辑器。
    starter_code: sanitizeStarterCode(form.starterCode),
    activate: true,
    test_cases: (form.testCases ?? []).map((testCase) => ({
      case_name: String(testCase.case_name ?? '').trim(),
      stdin: String(testCase.stdin ?? ''),
      expected_stdout: String(testCase.expected_stdout ?? ''),
      is_hidden: Boolean(testCase.is_hidden),
      weight: numeric(testCase.weight),
    })),
  }
}

function sanitizeStarterCode(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const out = {}
  for (const [lang, code] of Object.entries(value)) {
    if (typeof lang !== 'string' || !lang.trim()) continue
    out[lang.trim()] = String(code ?? '').slice(0, 20000)
  }
  return out
}
