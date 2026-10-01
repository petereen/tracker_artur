import { useTranslation } from 'react-i18next'
import { lazy, Suspense, useEffect, useState } from 'react'
import { Phone, Video } from 'lucide-react'
import type { ChatConversation } from '../api/enterprise'
import { useAuthStore } from '../store/auth'
import { useOptionalCall } from './CallProvider'

// Loaded on demand: the WebRTC call UI is only needed once someone dials OYUNS.
const OyunsVoiceCall = lazy(() => import('./OyunsVoiceCall').then((module) => ({ default: module.OyunsVoiceCall })))

export function ChatCallHeader({ conversation }: { conversation: ChatConversation }) {
  const { t } = useTranslation()
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
    return <div className="chat-call-header" aria-label={t('assistant.call.agentAria')}>
      <button className="chat-icon-button" disabled={busy} title={busy ? t('chat.call.busy') : t('assistant.call.agentTitle')} onClick={() => setAgentCallOpen(true)} aria-label={t('assistant.call.agentDial')}><Phone /></button>
      {agentCallOpen && <Suspense fallback={null}><OyunsVoiceCall onClose={() => setAgentCallOpen(false)} /></Suspense>}
    </div>
  }
  if (!call || conversation.kind !== 'direct') return null
  const disabled = !supported || !online || !call.signalingConnected || call.state !== 'idle'
  const reason = !supported ? t('chat.call.unsupported') : !online ? t('chat.call.peerOffline') : !call.signalingConnected ? t('chat.call.noSignaling') : call.state !== 'idle' ? t('chat.call.busy') : undefined
  const start = (callType: 'audio' | 'video') => peer && call.initiate({ userId: String(peer.account_id), name: peer.name, avatar: peer.avatar_url, conversationId: conversation.public_id }, callType)
  return <div className="chat-call-header" aria-label={t('chat.call.actions')}>
    <button className="chat-icon-button" disabled={disabled} title={reason || t('chat.call.audio')} onClick={() => start('audio')} aria-label={t('chat.call.audio')}><Phone /></button>
    <button className="chat-icon-button" disabled={disabled} title={reason || t('chat.call.video')} onClick={() => start('video')} aria-label={t('chat.call.video')}><Video /></button>
  </div>
}
