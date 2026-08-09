/** Build a collision-resistant-enough key for the browser's pending-upload UI. */
export function createPendingFileId(file, runtime = {}) {
  const cryptoApi = runtime.crypto ?? globalThis.crypto
  const now = runtime.now ?? Date.now
  const random = runtime.random ?? Math.random
  // `crypto.randomUUID()` is unavailable in HTTP and some older browsers.
  // This ID never leaves the pending UI list, so the fallback need not be
  // cryptographically secure.
  const uuid = cryptoApi?.randomUUID?.()
    || `${now().toString(36)}-${random().toString(36).slice(2)}`
  return `${file.name}:${file.size}:${file.lastModified}:${uuid}`
}
