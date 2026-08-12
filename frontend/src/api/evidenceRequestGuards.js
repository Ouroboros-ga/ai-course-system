function hasValue(value) {
  return value != null && value !== ''
}

/**
 * Learning-page citations are course-scoped and may read only their
 * server-authorized render URL. The standalone evidence viewer alone may use
 * its document-scoped evidence-v2 page endpoint.
 */
export function resolveCitationPageImageSource({
  courseId,
  documentId,
  pageNumber,
  renderUrl,
} = {}) {
  if (renderUrl) return { kind: 'protected', url: renderUrl }
  if (hasValue(courseId) || !hasValue(documentId)) return null

  const page = Number(pageNumber)
  if (!Number.isSafeInteger(page) || page <= 0) return null

  return { kind: 'document', documentId, pageNumber: page }
}
