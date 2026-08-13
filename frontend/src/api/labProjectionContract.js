export function labProjectionPaths(courseId) {
  const scope = `?course_id=${encodeURIComponent(courseId)}`
  return {
    catalog: `/lab/catalog${scope}`,
    courseTasks: `/lab/course-tasks${scope}`,
    myExperiments: `/lab/my-experiments${scope}`,
    records: `/lab/records${scope}`,
  }
}

export function courseExperimentPath(courseId) {
  return `/app/course/${encodeURIComponent(courseId)}/experiments`
}
