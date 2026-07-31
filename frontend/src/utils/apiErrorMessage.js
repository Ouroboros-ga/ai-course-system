export function apiErrorMessage(error, fallback) {
  const payload = error?.response?.data
  const detail = payload?.detail
  return (
    (typeof detail === 'string' ? detail : detail?.message)
    || payload?.message
    || error?.message
    || fallback
  )
}
