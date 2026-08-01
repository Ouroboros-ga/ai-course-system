const svgDataUrl = svg => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`

const svg = (content, viewBox = '0 0 480 480') => svgDataUrl(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}">${content}</svg>`,
)

const mouth = shape => svg(`<path d="${shape}" fill="#8B3A3A"/>`, '0 0 100 56')

/**
 * Platform-owned, generic instructor artwork.  It carries no teacher image,
 * voice sample, or external provider material, so P3 can be tested before the
 * teacher-facing P4 asset-selection flow exists.
 */
export const PLATFORM_SPRITE2D_MANIFEST = Object.freeze({
  schema: 'sprite2d-manifest/v1',
  provider: 'platform_sprite2d',
  version: 'platform-instructor-v1',
  label: '平台预制讲师',
  stage: { width: 480, height: 480 },
  expressions: ['neutral', 'warm', 'attentive'],
  gestures: ['rest', 'emphasis'],
  sprites: {
    body: svg(`
      <path d="M98 480c13-132 65-186 142-186s129 54 142 186H98Z" fill="#203A5F"/>
      <path d="M161 480c11-105 41-158 79-158s68 53 79 158H161Z" fill="#355C7D"/>
      <path d="M214 315h52v70h-52z" fill="#D9A983"/>
      <path d="M178 480h124l-62-73-62 73Z" fill="#F7F8FA"/>
    `),
    head: svg(`
      <path d="M150 163c0-71 39-117 90-117s90 46 90 117v80c0 61-38 105-90 105s-90-44-90-105v-80Z" fill="#E8BA96"/>
      <path d="M147 176c-3-66 30-132 93-132 53 0 96 37 94 118-24-28-49-43-95-44-18 31-48 49-92 58Z" fill="#14213D"/>
      <path d="M153 165c5 38 18 54 32 66v-49c-14-3-25-9-32-17Zm174 0c-7 8-18 14-32 17v49c14-12 27-28 32-66Z" fill="#14213D"/>
      <circle cx="158" cy="239" r="14" fill="#E8BA96"/><circle cx="322" cy="239" r="14" fill="#E8BA96"/>
    `),
    eyes: svg(`
      <path d="M184 217c14-13 38-13 52 0-14 16-38 16-52 0Zm60 0c14-13 38-13 52 0-14 16-38 16-52 0Z" fill="#FFFFFF"/>
      <circle cx="210" cy="217" r="7" fill="#172033"/><circle cx="270" cy="217" r="7" fill="#172033"/>
      <path d="M183 196c15-8 34-8 50 0M247 196c15-8 34-8 50 0" fill="none" stroke="#14213D" stroke-width="7" stroke-linecap="round"/>
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
