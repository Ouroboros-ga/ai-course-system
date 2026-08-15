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
    writes_formal_evidence: true,
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
