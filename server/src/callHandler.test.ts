import assert from 'node:assert/strict'
import test from 'node:test'
import { validDescription, validId } from './callHandler.js'

test('validates bounded identifiers', () => {
  assert.equal(validId('42'), true)
  assert.equal(validId(''), false)
  assert.equal(validId('x'.repeat(65)), false)
  assert.equal(validId(42), false)
})

test('accepts WebRTC descriptions and rejects oversized or malformed SDP', () => {
  assert.equal(validDescription({ type: 'offer', sdp: 'v=0' }), true)
  assert.equal(validDescription({ type: 'answer', sdp: 'v=0' }), true)
  assert.equal(validDescription({ type: 'invalid', sdp: 'v=0' }), false)
  assert.equal(validDescription({ type: 'offer', sdp: 'x'.repeat(200_001) }), false)
})
