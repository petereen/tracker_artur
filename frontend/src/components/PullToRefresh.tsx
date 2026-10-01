import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'

const TRIGGER = 64
const MAX_PULL = 96
const MIN_SPIN_MS = 550

function scrollableAncestorIsScrolled(node: Element | null) {
  for (let element = node; element && element !== document.body; element = element.parentElement) {
    if (element.scrollTop > 0) {
      const overflowY = getComputedStyle(element).overflowY
      if (overflowY === 'auto' || overflowY === 'scroll') return true
    }
  }
  return false
}

function overlayOpen() {
  return document.body.style.overflow === 'hidden' || Boolean(document.querySelector('[aria-modal="true"], .sheet-backdrop, .hr-drawer-backdrop, .workers-drawer.open'))
}

// Touch-only pull-to-refresh for the phone layout: refetches the active queries instead of
// reloading the page (the browser's own pull-to-refresh is disabled via overscroll-behavior).
export function PullToRefresh({ enabled }: { enabled: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [pull, setPull] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const state = useRef({ startX: 0, startY: 0, tracking: false, pulling: false, armed: false })
  const pullRef = useRef(0)

  useEffect(() => {
    if (!enabled || refreshing) return
    const setPullValue = (value: number) => { pullRef.current = value; setPull(value) }
    const onStart = (event: TouchEvent) => {
      const target = event.target as Element | null
      const eligible = event.touches.length === 1
        && window.scrollY <= 0
        && Boolean(window.matchMedia?.('(max-width: 800px)').matches)
        && !overlayOpen()
        && !target?.closest('input, textarea, select, [contenteditable="true"], .mobile-tabbar, .workspace-header, [data-no-pull-refresh]')
        && !scrollableAncestorIsScrolled(target)
      state.current = { startX: event.touches[0].clientX, startY: event.touches[0].clientY, tracking: eligible, pulling: false, armed: false }
    }
    const onMove = (event: TouchEvent) => {
      const current = state.current
      if (!current.tracking) return
      if (document.querySelector('.drag-overlay')) {
        current.tracking = false
        current.pulling = false
        setPullValue(0)
        return
      }
      const dx = event.touches[0].clientX - current.startX
      const dy = event.touches[0].clientY - current.startY
      if (!current.pulling) {
        if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) { current.tracking = false; return }
        if (dy < 8 || window.scrollY > 0) { if (dy < 0) current.tracking = false; return }
        current.pulling = true
      }
      const distance = Math.min(MAX_PULL, Math.max(0, dy - 8) * 0.5)
      if (distance >= TRIGGER && !current.armed) { current.armed = true; navigator.vibrate?.(8) }
      if (distance < TRIGGER) current.armed = false
      setPullValue(distance)
    }
    const onEnd = () => {
      const current = state.current
      if (!current.pulling) { current.tracking = false; return }
      state.current.tracking = false
      state.current.pulling = false
      if (pullRef.current >= TRIGGER) {
        setRefreshing(true)
        setPullValue(TRIGGER)
        const started = Date.now()
        void queryClient.refetchQueries({ type: 'active' }).catch(() => undefined).finally(() => {
          window.setTimeout(() => { setRefreshing(false); setPullValue(0) }, Math.max(0, MIN_SPIN_MS - (Date.now() - started)))
        })
      } else {
        setPullValue(0)
      }
    }
    window.addEventListener('touchstart', onStart, { passive: true })
    window.addEventListener('touchmove', onMove, { passive: true })
    window.addEventListener('touchend', onEnd, { passive: true })
    window.addEventListener('touchcancel', onEnd, { passive: true })
    return () => {
      window.removeEventListener('touchstart', onStart)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('touchend', onEnd)
      window.removeEventListener('touchcancel', onEnd)
    }
  }, [enabled, queryClient, refreshing])

  if (!enabled || (!pull && !refreshing)) return null
  const progress = Math.min(1, pull / TRIGGER)
  return (
    <div className={`pull-refresh-indicator ${refreshing ? 'is-refreshing' : ''} ${pull === 0 && !refreshing ? '' : 'is-visible'}`} style={{ transform: `translate3d(-50%, ${pull}px, 0)` }} role="status" aria-live="polite">
      <span style={{ opacity: 0.35 + progress * 0.65 }}>
        <RefreshCw size={18} strokeWidth={2.2} style={refreshing ? undefined : { transform: `rotate(${progress * 270}deg)` }} aria-hidden />
      </span>
      <span className="sr-only">{refreshing ? t('pull.refreshing') : progress >= 1 ? t('pull.release') : t('pull.pull')}</span>
    </div>
  )
}
