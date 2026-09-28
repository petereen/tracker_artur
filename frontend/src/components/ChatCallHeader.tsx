import { lazy, Suspense, useEffect, useState } from 'react'
import { Phone, Video } from 'lucide-react'
import type { ChatConversation } from '../api/enterprise'
import { useAuthStore } from '../store/auth'
import { useOptionalCall } from './CallProvider'

// Loaded on demand: the WebRTC call UI is only needed once someone dials OYUNS.
const OyunsVoiceCall = lazy(() => import('./OyunsVoiceCall').then((module) => ({ default: module.OyunsVoiceCall })))

export function ChatCallHeader({ conversation }: { conversation: ChatConversation }) {
  const ownId = useAuthStore((state) => state.actor?.id)
  const call = useOptionalCall()
  const [agentCallOpen, setAgentCallOpen] = useState(false)
  const peer = conversation.members.find((member) => member.account_id !== ownId)
  const supported = conversation.kind === 'direct' && Boolean(peer && !peer.is_agent)
  const online = peer ? (call?.onlineUsers[String(peer.account_id)] ?? conversation.presence === 'online') : false
  useEffect(() => {
    if (supported && peer && call) call.watchUser({ userId: String(peer.account_id), conversationId: conversation.public_id })
  }, [call?.watchUser, conversation.public_id, peer?.account_id, supported])
  if (conversation.kind === 'direct' && peer?.is_agent) {
    // The OYUNS agent answers live voice calls through the Realtime API.
    const busy = Boolean(call && call.state !== 'idle')
    return <div className="chat-call-header" aria-label="OYUNS Agent дуудлага">
      <button className="chat-icon-button" disabled={busy} title={busy ? 'Дуудлага идэвхтэй байна' : 'OYUNS Agent руу дуут дуудлага хийх'} onClick={() => setAgentCallOpen(true)} aria-label="OYUNS Agent руу залгах"><Phone /></button>
      {agentCallOpen && <Suspense fallback={null}><OyunsVoiceCall onClose={() => setAgentCallOpen(false)} /></Suspense>}
    </div>
  }
  if (!call || conversation.kind !== 'direct') return null
  const disabled = !supported || !online || !call.signalingConnected || call.state !== 'idle'
  const reason = !supported ? 'Энэ чатанд дуудлага боломжгүй' : !online ? 'Хэрэглэгч офлайн байна' : !call.signalingConnected ? 'Дуудлагын сервертэй холбогдоогүй' : call.state !== 'idle' ? 'Дуудлага идэвхтэй байна' : undefined
  const start = (callType: 'audio' | 'video') => peer && call.initiate({ userId: String(peer.account_id), name: peer.name, avatar: peer.avatar_url, conversationId: conversation.public_id }, callType)
  return <div className="chat-call-header" aria-label="Дуудлагын үйлдэл">
    <button className="chat-icon-button" disabled={disabled} title={reason || 'Аудио дуудлага'} onClick={() => start('audio')} aria-label="Аудио дуудлага"><Phone /></button>
    <button className="chat-icon-button" disabled={disabled} title={reason || 'Видео дуудлага'} onClick={() => start('video')} aria-label="Видео дуудлага"><Video /></button>
  </div>
}
