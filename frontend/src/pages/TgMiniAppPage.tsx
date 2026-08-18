import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { acceptSession, api } from '../api/client'
import { useAuthStore } from '../store/auth'

/**
 * Telegram's entry URL now signs into the normal ERP workspace.  Keeping this
 * small route preserves existing bot buttons and deep links without maintaining
 * a second, task-only application.
 */
export function TgMiniAppPage() {
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable' | 'error'>('loading')
  const setInitialized = useAuthStore((store) => store.setInitialized)

  useEffect(() => {
    const telegram = (window as any).Telegram?.WebApp
    const initData = telegram?.initData
    if (!telegram || !initData) {
      setState('unavailable')
      return
    }

    telegram.ready()
    telegram.expand()
    telegram.setHeaderColor?.('bg_color')
    telegram.setBackgroundColor?.('bg_color')
    document.documentElement.classList.add('telegram-mini-app')
    const startParam = telegram.initDataUnsafe?.start_param || new URLSearchParams(window.location.search).get('tgWebAppStartParam')

    api.post('/v1/auth/telegram', undefined, { headers: { 'X-Telegram-Init-Data': initData } })
      .then(async ({ data }) => {
        acceptSession(data)
        setInitialized(true)
        if (typeof startParam === 'string' && startParam.startsWith('oyuns-worktime:')) {
          await api.post('/v1/worktime-qr/clock', { token: startParam, client_timestamp: new Date().toISOString() })
        }
        setState('ready')
      })
      .catch(() => setState('error'))

    return () => document.documentElement.classList.remove('telegram-mini-app')
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
