import assert from 'node:assert/strict'
import test from 'node:test'

import { spriteTextureAsset } from '../renderers/Sprite2DRenderer.js'

test('signed content routes explicitly select the Pixi texture parser', () => {
  const url = '/api/v1/media/assets/platform/avatar/body.png/content?sig=signed'
  assert.deepEqual(spriteTextureAsset(url), {
    src: url,
    parser: 'loadTextures',
  })
})
