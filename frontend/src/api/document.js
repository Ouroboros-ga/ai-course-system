import request from '@/utils/request.js'

/** Import a local course source through the established document pipeline. */
export function importCourseDocument(file, options = {}) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/document/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: options.timeout ?? 300000,
    onUploadProgress: options.onUploadProgress,
  })
}

/**
 * Creation path for the product UI.  The server persists the draft course and
 * a TaskRecord before responding 202; parsing then continues independent of
 * this browser tab.
 */
export function createCourseImport(file, options = {}) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/document/course-imports', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: options.timeout ?? 300000,
    onUploadProgress: options.onUploadProgress,
  })
}
