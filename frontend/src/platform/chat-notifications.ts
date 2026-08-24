export type DesktopChatAlert = {
  title: string
  body: string
  targetUrl: string
  soundEnabled: boolean
}

let sound: HTMLAudioElement | null = null

export function desktopChatPermission(): NotificationPermission | 'unsupported' {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
}

export async function requestDesktopChatPermission() {
  if (typeof Notification === 'undefined') return 'unsupported' as const
  return Notification.requestPermission()
}

export async function previewChatSound() {
  if (typeof Audio === 'undefined') return false
  sound ||= new Audio('/sounds/oyuns-chat-notification.mp3')
  sound.currentTime = 0
  try {
    await sound.play()
    return true
  } catch {
    return false
  }
}

export async function showDesktopChatAlert(alert: DesktopChatAlert, onOpen: (targetUrl: string) => void) {
  if (document.visibilityState === 'visible' || typeof Notification === 'undefined' || Notification.permission !== 'granted') return false
  const notification = new Notification(alert.title, { body: alert.body, icon: '/favicon.png', tag: alert.targetUrl })
  notification.onclick = () => {
    window.focus()
    onOpen(alert.targetUrl)
    notification.close()
  }
  if (alert.soundEnabled) await previewChatSound()
  return true
}
