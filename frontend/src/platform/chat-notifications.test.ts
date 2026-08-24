import { beforeEach, describe, expect, it, vi } from 'vitest'
import { requestDesktopChatPermission, showDesktopChatAlert } from './chat-notifications'


describe('desktop chat notifications', () => {
  const play = vi.fn().mockResolvedValue(undefined)
  const close = vi.fn()

  beforeEach(() => {
    play.mockClear(); close.mockClear()
    class NotificationMock {
      static permission: NotificationPermission = 'granted'
      static requestPermission = vi.fn().mockResolvedValue('granted')
      onclick: (() => void) | null = null
      close = close
      constructor(public title: string, public options?: NotificationOptions) {}
    }
    vi.stubGlobal('Notification', NotificationMock)
    vi.stubGlobal('Audio', class { currentTime = 0; play = play })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  })

  it('requests permission only through the explicit helper', async () => {
    expect(await requestDesktopChatPermission()).toBe('granted')
    expect(Notification.requestPermission).toHaveBeenCalledOnce()
  })

  it('shows and sounds an alert only while hidden', async () => {
    const open = vi.fn()
    expect(await showDesktopChatAlert({ title: 'Ану', body: 'Сайн уу', targetUrl: '/chat/c1', soundEnabled: true }, open)).toBe(true)
    expect(play).toHaveBeenCalledOnce()
  })
})
