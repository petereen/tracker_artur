import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { acceptSession, api } from '../api/client'
import { useAuthStore } from '../store/auth'
import { isNativePlatform } from '../platform/runtime'

async function loadTelegramSdk() {
  if ((window as any).Telegram?.WebApp) return
  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-telegram-web-app]')
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Telegram SDK failed to load')), { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-web-app.js'
    script.async = true
    script.dataset.telegramWebApp = 'true'
    script.addEventListener('load', () => resolve(), { once: true })
    script.addEventListener('error', () => reject(new Error('Telegram SDK failed to load')), { once: true })
    document.head.appendChild(script)
  })
}

/**
 * Telegram's entry URL now signs into the normal ERP workspace.  Keeping this
 * small route preserves existing bot buttons and deep links without maintaining
 * a second, task-only application.
 */
export function TgMiniAppPage() {
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable' | 'error'>('loading')
  const setInitialized = useAuthStore((store) => store.setInitialized)

  useEffect(() => {
    let cancelled = false
    if (isNativePlatform()) { setState('unavailable'); return }

    void loadTelegramSdk().then(() => {
      if (cancelled) return
      const telegram = (window as any).Telegram?.WebApp
      const initData = telegram?.initData
      if (!telegram || !initData) { setState('unavailable'); return }

      telegram.ready()
      telegram.expand()
      telegram.setHeaderColor?.('bg_color')
      telegram.setBackgroundColor?.('bg_color')
      document.documentElement.classList.add('telegram-mini-app')
      api.post('/v1/auth/telegram', undefined, { headers: { 'X-Telegram-Init-Data': initData } })
        .then(async ({ data }) => {
          await acceptSession(data)
          setInitialized(true)
          setState('ready')
        })
        .catch(() => setState('error'))
    }).catch(() => setState('unavailable'))

    return () => { cancelled = true; document.documentElement.classList.remove('telegram-mini-app') }
  }, [setInitialized])

  if (state === 'ready') return <Navigate to="/" replace />
  if (state === 'unavailable') return <Navigate to="/" replace />

  return (
    <main className="telegram-entry-state" aria-live="polite">
      <img src="/oyuns-aio-logo.png" alt="OYUNS" />
      {state === 'error'
        ? <><h1>Нэвтрэх боломжгүй байна</h1><p>Таны Telegram бүртгэл ERP эрхтэй эсэхийг админаасаа шалгуулна уу.</p></>
        : <><h1>Ажлын орон зайг нээж байна…</h1><p>Таны OYUNS ERP-д аюулгүй нэвтэрч байна.</p></>}
    </main>
  )
}
