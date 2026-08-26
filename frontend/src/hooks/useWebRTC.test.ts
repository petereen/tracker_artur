import { describe, expect, it } from 'vitest'
import { mediaErrorMessage } from './useWebRTC'

describe('WebRTC media errors', () => {
  it('maps browser permission and device errors to actionable messages', () => {
    expect(mediaErrorMessage(new DOMException('', 'NotAllowedError'))).toContain('зөвшөөрөл')
    expect(mediaErrorMessage(new DOMException('', 'NotFoundError'))).toContain('олдсонгүй')
    expect(mediaErrorMessage(new DOMException('', 'NotReadableError'))).toContain('өөр програм')
  })
})
