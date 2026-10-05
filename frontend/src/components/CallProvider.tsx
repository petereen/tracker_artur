import { createContext, lazy, Suspense, useContext, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWebRTC } from '../hooks/useWebRTC'

// The call UI pulls in `motion`; keep it out of the first-load graph and warm
// it when the browser is idle so an incoming call doesn't wait on a download.
const loadCallModal = () => import('./CallModal')
const CallModal = lazy(() => loadCallModal().then((module) => ({ default: module.CallModal })))

type CallContextValue = ReturnType<typeof useWebRTC>
const CallContext = createContext<CallContextValue | null>(null)

export function CallProvider({ children }: { children: React.ReactNode }) {
  const call = useWebRTC()
  const navigate = useNavigate()
  useEffect(() => {
    const idle = (window as Window & { requestIdleCallback?: (cb: () => void, options?: { timeout: number }) => number }).requestIdleCallback
    if (idle) idle(() => void loadCallModal(), { timeout: 5_000 })
    else window.setTimeout(() => void loadCallModal(), 3_000)
  }, [])
  return <CallContext.Provider value={call}>
    {children}
    {call.activeCall && <Suspense fallback={null}>
      <CallModal call={call} onOpenConversation={() => call.activeCall && navigate(`/chat/${call.activeCall.conversationId}`)} />
    </Suspense>}
  </CallContext.Provider>
}

export function useOptionalCall() {
  return useContext(CallContext)
}
