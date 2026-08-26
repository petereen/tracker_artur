export type CallState = 'idle' | 'outgoing_ring' | 'incoming_ring' | 'connecting' | 'connected' | 'reconnecting' | 'ended'
export type CallType = 'audio' | 'video'
export type CallRejectReason = 'declined' | 'busy' | 'offline'
export type CallOutcome = 'completed' | 'missed' | 'declined' | 'canceled' | 'failed'

export interface CallInitiatePayload { recipientId: string; conversationId: string; callType: CallType }
export interface CallIncomingPayload { callId: string; conversationId: string; callerId: string; callerName: string; callerAvatar?: string; callType: CallType }
export interface CallAcceptPayload { callId: string; targetUserId: string }
export interface CallRejectPayload { callId?: string; targetUserId: string; reason: CallRejectReason }
export interface CallDescriptionPayload { callId: string; targetUserId: string; sdp: RTCSessionDescriptionInit }
export interface CallIceCandidatePayload { callId: string; targetUserId: string; candidate: RTCIceCandidateInit }
export interface CallEndPayload { callId: string; targetUserId: string; durationSeconds: number; reason?: string }
export interface CallConnectedPayload { callId: string }
export interface CallResumePayload { callId: string }
export interface UserStatusPayload { userId: string; isOnline: boolean }
export interface UserWatchPayload { userId: string; conversationId: string }

export type SignalingErrorCode = 'unauthorized' | 'invalid_payload' | 'forbidden' | 'busy' | 'offline' | 'not_found' | 'rate_limited' | 'internal_error'
export type SignalingAck<T extends object = object> = ({ ok: true } & T) | { ok: false; code: SignalingErrorCode; message: string }

export interface CallAcceptedEvent { callId: string; acceptedBy: string }
export interface CallEndedEvent { callId: string; reason: string; outcome: CallOutcome; durationSeconds: number }
export interface CallErrorEvent { callId?: string; code: SignalingErrorCode; message: string }

export interface ClientToServerEvents {
  'call:initiate': (payload: CallInitiatePayload, ack: (result: SignalingAck<{ callId: string }>) => void) => void
  'call:accept': (payload: CallAcceptPayload, ack: (result: SignalingAck) => void) => void
  'call:reject': (payload: CallRejectPayload, ack?: (result: SignalingAck) => void) => void
  'call:offer': (payload: CallDescriptionPayload) => void
  'call:answer': (payload: CallDescriptionPayload) => void
  'call:ice-candidate': (payload: CallIceCandidatePayload) => void
  'call:connected': (payload: CallConnectedPayload) => void
  'call:end': (payload: CallEndPayload) => void
  'call:resume': (payload: CallResumePayload, ack: (result: SignalingAck) => void) => void
  'user:watch': (payload: UserWatchPayload) => void
}

export interface ServerToClientEvents {
  'call:incoming': (payload: CallIncomingPayload) => void
  'call:accepted': (payload: CallAcceptedEvent) => void
  'call:reject': (payload: CallRejectPayload) => void
  'call:offer': (payload: CallDescriptionPayload) => void
  'call:answer': (payload: CallDescriptionPayload) => void
  'call:ice-candidate': (payload: CallIceCandidatePayload) => void
  'call:ended': (payload: CallEndedEvent) => void
  'call:error': (payload: CallErrorEvent) => void
  'user:status': (payload: UserStatusPayload) => void
}

export interface SignalingSocketData { userId: string; organizationId: string; name: string; avatar?: string; token: string }
