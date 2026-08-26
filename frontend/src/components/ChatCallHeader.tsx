import { useEffect } from 'react'
import { Mic, Video } from 'lucide-react'
import type { ChatConversation } from '../api/enterprise'
import { useAuthStore } from '../store/auth'
import { isNativePlatform } from '../platform/runtime'
import { useOptionalCall } from './CallProvider'

export function ChatCallHeader({ conversation }: { conversation: ChatConversation }) {
  const ownId = useAuthStore((state) => state.actor?.id)
  const call = useOptionalCall()
  const peer = conversation.members.find((member) => member.account_id !== ownId)
  const supported = conversation.kind === 'direct' && Boolean(peer && !peer.is_agent) && !isNativePlatform()
  const online = peer ? (call?.onlineUsers[String(peer.account_id)] ?? conversation.presence === 'online') : false
  useEffect(() => {
    if (supported && peer && call) call.watchUser({ userId: String(peer.account_id), conversationId: conversation.public_id })
  }, [call?.watchUser, conversation.public_id, peer?.account_id, supported])
  if (!call || conversation.kind !== 'direct' || peer?.is_agent) return null
  const disabled = !supported || !online || !call.signalingConnected || call.state !== 'idle'
  const reason = !supported ? 'Дуудлага native апп-д дараагийн шинэчлэлтээр орно' : !online ? 'Хэрэглэгч офлайн байна' : !call.signalingConnected ? 'Дуудлагын сервертэй холбогдоогүй' : call.state !== 'idle' ? 'Дуудлага идэвхтэй байна' : undefined
  const start = (callType: 'audio' | 'video') => peer && call.initiate({ userId: String(peer.account_id), name: peer.name, avatar: peer.avatar_url, conversationId: conversation.public_id }, callType)
  return <div className="chat-call-header" aria-label="Дуудлагын үйлдэл">
    <button className="chat-icon-button" disabled={disabled} title={reason || 'Аудио дуудлага'} onClick={() => start('audio')} aria-label="Аудио дуудлага"><Mic /></button>
    <button className="chat-icon-button" disabled={disabled} title={reason || 'Видео дуудлага'} onClick={() => start('video')} aria-label="Видео дуудлага"><Video /></button>
  </div>
}
