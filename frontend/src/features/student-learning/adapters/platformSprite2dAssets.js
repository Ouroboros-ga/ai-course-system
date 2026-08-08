const svgDataUrl = svg => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`

const svg = (content, viewBox = '0 0 480 480') => svgDataUrl(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}">${content}</svg>`,
)

const mouth = shape => svg(`<path d="${shape}" fill="#8B3A3A"/>`, '0 0 100 56')

/**
 * Platform-owned, semi-realistic fictional instructor artwork.  It carries no teacher image,
 * voice sample, or external provider material, so P3 can be tested before the
 * teacher-facing P4 asset-selection flow exists.
 */
export const PLATFORM_SPRITE2D_MANIFEST = Object.freeze({
  schema: 'sprite2d-manifest/v1',
  provider: 'platform_sprite2d',
  version: 'platform-instructor-real-v1@1.0.0',
  label: '半写实汽车教师',
  stage: { width: 480, height: 480 },
  expressions: ['neutral', 'warm', 'attentive'],
  gestures: ['rest', 'emphasis'],
  sprites: {
    body: svg(`
      <defs><linearGradient id="j" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#486B92"/><stop offset="1" stop-color="#203A5F"/></linearGradient><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#F7F8FA"/><stop offset="1" stop-color="#D9E0E8"/></linearGradient></defs>
      <path d="M70 480c11-127 70-196 170-196s159 69 170 196H70Z" fill="url(#j)"/>
      <path d="M161 480c11-91 38-151 79-171 41 20 68 80 79 171H161Z" fill="url(#s)"/>
      <path d="M240 308 205 480h70Z" fill="#B34B4B" opacity=".92"/>
      <path d="M164 316 214 480h-46l-43-112c10-25 22-40 39-52Zm152 0-50 164h46l43-112c-10-25-22-40-39-52Z" fill="#172941" opacity=".55"/>
    `),
    head: svg(`
      <defs><linearGradient id="skin" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#F0C5A5"/><stop offset="1" stop-color="#D59B78"/></linearGradient><linearGradient id="hair" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#46556A"/><stop offset="1" stop-color="#1A2230"/></linearGradient></defs>
      <path d="M151 170c0-73 39-119 89-119s89 46 89 119v76c0 62-37 108-89 108s-89-46-89-108v-76Z" fill="url(#skin)"/>
      <path d="M151 174c-6-65 29-137 92-137 64 0 101 47 87 139-29-31-59-47-105-48-18 29-40 43-74 46Z" fill="url(#hair)"/>
      <path d="M164 255c8 20 22 34 40 42M316 255c-8 20-22 34-40 42" fill="none" stroke="#A76F58" stroke-width="5" stroke-linecap="round" opacity=".35"/>
      <circle cx="153" cy="237" r="15" fill="url(#skin)"/><circle cx="327" cy="237" r="15" fill="url(#skin)"/>
    `),
    eyes: svg(`
      <path d="M177 217c15-15 40-15 55 0-15 17-40 17-55 0Zm71 0c15-15 40-15 55 0-15 17-40 17-55 0Z" fill="#FFFFFF"/>
      <circle cx="212" cy="218" r="8" fill="#182235"/><circle cx="268" cy="218" r="8" fill="#182235"/>
      <path d="M174 197c17-10 39-10 57 0M249 197c18-10 40-10 57 0" fill="none" stroke="#1A2230" stroke-width="7" stroke-linecap="round"/>
      <path d="M174 214h57M249 214h57M231 216h18" fill="none" stroke="#4A5666" stroke-width="3" opacity=".85"/>
      <path d="M176 213c0-14 14-22 29-22h8c12 0 19 8 19 22s-8 23-22 23h-13c-13 0-21-9-21-23Zm73 0c0-14 8-22 20-22h8c15 0 29 8 29 22s-8 23-21 23h-13c-14 0-23-9-23-23Z" fill="none" stroke="#25384F" stroke-width="4"/>
    `),
    mouths: {
      sil: mouth('M30 28c12 5 28 5 40 0 12 5 28 5 40 0-20 12-60 12-80 0Z'),
      a: mouth('M27 26c5-18 41-23 46-2 5-21 41-16 46 2-13 25-80 25-92 0Z'),
      e: mouth('M21 24c14-14 64-14 78 0-18 15-61 15-78 0Z'),
      i: mouth('M37 19c10-8 16-8 26 0 10-8 16-8 26 0-12 19-40 19-52 0Z'),
      o: mouth('M31 13c13-14 35-14 48 0v23c-13 14-35 14-48 0V13Z'),
      u: mouth('M40 14c7-9 14-9 20 0v25c-7 9-14 9-20 0V14Z'),
      fv: mouth('M20 18h80v11H20zM29 30c12 9 30 9 42 0-9 17-33 17-42 0Z'),
      mbp: mouth('M24 26c17-5 35-5 52 0-17 10-35 10-52 0Z'),
    },
  },
})

export function normalizeSprite2dManifest(rawValue) {
  const raw = rawValue?.data ?? rawValue ?? {}
  const sprites = raw.sprites
  const supportedMouths = sprites?.mouths
  if (
    raw.schema !== 'sprite2d-manifest/v1'
    || typeof sprites?.body !== 'string'
    || typeof sprites?.head !== 'string'
    || typeof sprites?.eyes !== 'string'
    || !supportedMouths
    || ![...new Set(['sil', 'a', 'e', 'i', 'o', 'u', 'fv', 'mbp'])].every(key => typeof supportedMouths[key] === 'string')
  ) return null

  return {
    schema: 'sprite2d-manifest/v1',
    provider: String(raw.provider ?? 'sprite2d'),
    version: String(raw.version ?? ''),
    label: String(raw.label ?? '数字人'),
    stage: {
      width: Math.max(1, Number(raw.stage?.width) || 480),
      height: Math.max(1, Number(raw.stage?.height) || 480),
    },
    expressions: Array.isArray(raw.expressions) ? raw.expressions.map(String) : ['neutral'],
    gestures: Array.isArray(raw.gestures) ? raw.gestures.map(String) : ['rest'],
    sprites: {
      body: sprites.body,
      head: sprites.head,
      eyes: sprites.eyes,
      mouths: Object.fromEntries(Object.entries(supportedMouths).map(([key, value]) => [key, String(value)])),
    },
  }
}
