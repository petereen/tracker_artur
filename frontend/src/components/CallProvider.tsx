import { createContext, useContext } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWebRTC } from '../hooks/useWebRTC'
import { CallModal } from './CallModal'

type CallContextValue = ReturnType<typeof useWebRTC>
const CallContext = createContext<CallContextValue | null>(null)

export function CallProvider({ children }: { children: React.ReactNode }) {
  const call = useWebRTC()
  const navigate = useNavigate()
  return <CallContext.Provider value={call}>
    {children}
    <CallModal call={call} onOpenConversation={() => call.activeCall && navigate(`/chat/${call.activeCall.conversationId}`)} />
  </CallContext.Provider>
}

export function useCall() {
  const value = useContext(CallContext)
  if (!value) throw new Error('useCall must be used inside CallProvider')
  return value
}

export function useOptionalCall() {
  return useContext(CallContext)
}
