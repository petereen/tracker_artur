import { randomUUID } from 'node:crypto'
import type { Redis } from 'ioredis'
import type { Server, Socket } from 'socket.io'
import type {
  CallEndPayload, CallOutcome, ClientToServerEvents, ServerToClientEvents,
  SignalingAck, SignalingSocketData,
} from '../../types/call.js'

type CallServer = Server<ClientToServerEvents, ServerToClientEvents, Record<string, never>, SignalingSocketData>
type CallSocket = Socket<ClientToServerEvents, ServerToClientEvents, Record<string, never>, SignalingSocketData>

interface StoredCall {
  callId: string
  conversationId: string
  callerId: string
  calleeId: string
  callType: 'audio' | 'video'
  status: 'ringing' | 'accepted' | 'connected'
  startedAt: string
}

const backendUrl = (process.env.BACKEND_INTERNAL_URL || 'http://backend:8000').replace(/\/$/, '')
const serviceSecret = process.env.CALL_SIGNALING_SECRET || ''
const ringTimers = new Map<string, NodeJS.Timeout>()
const userRoom = (id: string) => `call:user:${id}`
const orgRoom = (id: string) => `call:org:${id}`
const onlineKey = (id: string) => `call:online:${id}`
const busyKey = (id: string) => `call:busy:${id}`
const callKey = (id: string) => `call:session:${id}`

async function backend(path: string, init: RequestInit = {}) {
  const response = await fetch(`${backendUrl}${path}`, init)
  if (!response.ok) throw Object.assign(new Error(`Backend returned ${response.status}`), { status: response.status })
  return response.json() as Promise<any>
}

function bearer(token: string) {
  return { authorization: `Bearer ${token}`, 'content-type': 'application/json' }
}

function internalHeaders() {
  return { 'x-call-service-secret': serviceSecret, 'content-type': 'application/json' }
}

function safeAck<T extends object>(ack: ((value: SignalingAck<T>) => void) | undefined, value: SignalingAck<T>) {
  if (typeof ack === 'function') ack(value)
}

export function validId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 64
}

export function validDescription(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const item = value as { type?: unknown; sdp?: unknown }
  return ['offer', 'answer', 'pranswer', 'rollback'].includes(String(item.type)) && (item.sdp === undefined || (typeof item.sdp === 'string' && item.sdp.length <= 200_000))
}

async function readCall(redis: Redis, callId: string): Promise<StoredCall | null> {
  const data = await redis.hgetall(callKey(callId))
  return data.callId ? data as unknown as StoredCall : null
}

async function touch(redis: Redis, socket: CallSocket) {
  await redis.sadd(onlineKey(socket.data.userId), socket.id)
  await redis.expire(onlineKey(socket.data.userId), 60)
  const callId = await redis.get(busyKey(socket.data.userId))
  if (callId) {
    await redis.expire(busyKey(socket.data.userId), 7200)
    await redis.expire(callKey(callId), 7200)
  }
}

async function releaseLock(redis: Redis, userId: string, callId: string) {
  await redis.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0", 1, busyKey(userId), callId)
}

async function lifecycle(callId: string, state: 'accepted' | 'connected' | 'ended', outcome?: CallOutcome, reason?: string) {
  return backend(`/v1/calls/internal/${callId}`, {
    method: 'PATCH', headers: internalHeaders(), body: JSON.stringify({ state, outcome, reason }),
  })
}

async function finalize(io: CallServer, redis: Redis, callId: string, outcome: CallOutcome, reason: string) {
  const call = await readCall(redis, callId)
  if (!call) return
  const first = await redis.set(`call:ended:${callId}`, '1', 'EX', 86_400, 'NX')
  if (!first) return
  const timer = ringTimers.get(callId)
  if (timer) clearTimeout(timer)
  ringTimers.delete(callId)
  await Promise.all([releaseLock(redis, call.callerId, callId), releaseLock(redis, call.calleeId, callId)])
  let durationSeconds = call.status === 'connected' ? Math.max(0, Math.floor((Date.now() - Date.parse(call.startedAt)) / 1000)) : 0
  try {
    const result = await lifecycle(callId, 'ended', outcome, reason)
    durationSeconds = Number(result.durationSeconds || 0)
  } catch {
    await redis.rpush('call:finalize:retry', JSON.stringify({ callId, outcome, reason }))
  }
  io.to(userRoom(call.callerId)).to(userRoom(call.calleeId)).emit('call:ended', { callId, outcome, reason, durationSeconds })
  await redis.del(callKey(callId))
}

async function peerCall(redis: Redis, socket: CallSocket, callId: string, requestedTarget: string) {
  const call = await readCall(redis, callId)
  if (!call) return null
  const expected = socket.data.userId === call.callerId ? call.calleeId : socket.data.userId === call.calleeId ? call.callerId : null
  return expected && expected === requestedTarget ? { call, peerId: expected } : null
}

export function registerCallHandler(io: CallServer, redis: Redis) {
  io.use(async (socket, next) => {
    try {
      const token = socket.handshake.auth?.token
      if (typeof token !== 'string' || token.length > 4096) return next(new Error('unauthorized'))
      const session = await backend('/v1/calls/session', { headers: bearer(token) })
      socket.data = { userId: String(session.userId), organizationId: String(session.organizationId), name: session.name, avatar: session.avatar || undefined, token }
      next()
    } catch { next(new Error('unauthorized')) }
  })

  io.on('connection', async (socket) => {
    socket.join(userRoom(socket.data.userId))
    socket.join(orgRoom(socket.data.organizationId))
    await touch(redis, socket)
    socket.to(orgRoom(socket.data.organizationId)).emit('user:status', { userId: socket.data.userId, isOnline: true })
    const heartbeat = setInterval(() => void touch(redis, socket), 20_000)
    let eventCount = 0
    let rateWindow = Date.now()
    socket.use((event, next) => {
      const now = Date.now()
      if (now - rateWindow > 10_000) { rateWindow = now; eventCount = 0 }
      if (++eventCount > 250) return next(new Error('rate_limited'))
      void touch(redis, socket)
      next()
    })

    socket.on('user:watch', async (payload) => {
      if (!validId(payload?.userId) || !validId(payload?.conversationId)) return
      try {
        await backend('/v1/calls/authorize', { method: 'POST', headers: bearer(socket.data.token), body: JSON.stringify({ conversationId: payload.conversationId, recipientId: Number(payload.userId) }) })
        socket.join(`call:watch:${socket.data.organizationId}:${payload.userId}`)
        socket.emit('user:status', { userId: payload.userId, isOnline: Boolean(await redis.exists(onlineKey(payload.userId))) })
      } catch { /* Do not disclose membership failures. */ }
    })

    socket.on('call:initiate', async (payload, ack) => {
      if (!validId(payload?.recipientId) || !validId(payload?.conversationId) || !['audio', 'video'].includes(payload?.callType)) {
        return safeAck(ack, { ok: false, code: 'invalid_payload', message: 'Invalid call request' })
      }
      try {
        const authorization = await backend('/v1/calls/authorize', { method: 'POST', headers: bearer(socket.data.token), body: JSON.stringify(payload) })
        if (!await redis.exists(onlineKey(payload.recipientId))) {
          socket.emit('call:reject', { targetUserId: payload.recipientId, reason: 'offline' })
          return safeAck(ack, { ok: false, code: 'offline', message: 'Recipient is offline' })
        }
        const callId = randomUUID()
        const locked = await redis.eval(
          "if redis.call('exists', KEYS[1]) == 1 or redis.call('exists', KEYS[2]) == 1 then return 0 end redis.call('set', KEYS[1], ARGV[1], 'EX', 7200) redis.call('set', KEYS[2], ARGV[1], 'EX', 7200) return 1",
          2, busyKey(socket.data.userId), busyKey(payload.recipientId), callId,
        )
        if (!locked) {
          socket.emit('call:reject', { targetUserId: payload.recipientId, reason: 'busy' })
          return safeAck(ack, { ok: false, code: 'busy', message: 'A participant is already in a call' })
        }
        const stored: StoredCall = { callId, conversationId: payload.conversationId, callerId: socket.data.userId, calleeId: payload.recipientId, callType: payload.callType, status: 'ringing', startedAt: new Date().toISOString() }
        await redis.hset(callKey(callId), stored as unknown as Record<string, string>)
        await redis.expire(callKey(callId), 7200)
        try {
          await backend('/v1/calls/internal/initiate', { method: 'POST', headers: internalHeaders(), body: JSON.stringify(stored) })
        } catch (error) {
          await Promise.all([releaseLock(redis, stored.callerId, callId), releaseLock(redis, stored.calleeId, callId), redis.del(callKey(callId))])
          throw error
        }
        io.to(userRoom(payload.recipientId)).emit('call:incoming', {
          callId, conversationId: payload.conversationId, callerId: socket.data.userId,
          callerName: authorization.caller.name, callerAvatar: authorization.caller.avatar || undefined, callType: payload.callType,
        })
        ringTimers.set(callId, setTimeout(() => void finalize(io, redis, callId, 'missed', 'no_answer'), 30_000))
        safeAck(ack, { ok: true, callId })
      } catch (error: any) {
        safeAck(ack, { ok: false, code: error?.status === 403 || error?.status === 404 ? 'forbidden' : 'internal_error', message: 'Unable to start call' })
      }
    })

    socket.on('call:accept', async (payload, ack) => {
      if (!validId(payload?.callId) || !validId(payload?.targetUserId)) return safeAck(ack, { ok: false, code: 'invalid_payload', message: 'Invalid call' })
      const pair = await peerCall(redis, socket, payload.callId, payload.targetUserId)
      if (!pair || socket.data.userId !== pair.call.calleeId) return safeAck(ack, { ok: false, code: 'forbidden', message: 'Call is unavailable' })
      const accepted = await redis.eval("if redis.call('hget', KEYS[1], 'status') ~= 'ringing' then return 0 end redis.call('hset', KEYS[1], 'status', 'accepted') return 1", 1, callKey(payload.callId))
      if (!accepted) return safeAck(ack, { ok: false, code: 'busy', message: 'Call was already answered' })
      const timer = ringTimers.get(payload.callId); if (timer) clearTimeout(timer); ringTimers.delete(payload.callId)
      await lifecycle(payload.callId, 'accepted').catch(() => undefined)
      io.to(userRoom(pair.call.callerId)).to(userRoom(pair.call.calleeId)).emit('call:accepted', { callId: payload.callId, acceptedBy: socket.data.userId })
      safeAck(ack, { ok: true })
    })

    socket.on('call:reject', async (payload, ack) => {
      if (!payload?.callId || !validId(payload.callId) || !validId(payload.targetUserId)) return safeAck(ack, { ok: false, code: 'invalid_payload', message: 'Invalid call' })
      const pair = await peerCall(redis, socket, payload.callId, payload.targetUserId)
      if (!pair) return safeAck(ack, { ok: false, code: 'forbidden', message: 'Call is unavailable' })
      io.to(userRoom(pair.peerId)).emit('call:reject', { callId: payload.callId, targetUserId: pair.peerId, reason: 'declined' })
      await finalize(io, redis, payload.callId, 'declined', 'declined')
      safeAck(ack, { ok: true })
    })

    const relayDescription = async (event: 'call:offer' | 'call:answer', payload: any) => {
      if (!validId(payload?.callId) || !validId(payload?.targetUserId) || !validDescription(payload?.sdp)) return
      const pair = await peerCall(redis, socket, payload.callId, payload.targetUserId)
      if (pair) io.to(userRoom(pair.peerId)).emit(event, payload)
    }
    socket.on('call:offer', (payload) => void relayDescription('call:offer', payload))
    socket.on('call:answer', (payload) => void relayDescription('call:answer', payload))
    socket.on('call:ice-candidate', async (payload) => {
      if (!validId(payload?.callId) || !validId(payload?.targetUserId) || !payload?.candidate || JSON.stringify(payload.candidate).length > 16_000) return
      const pair = await peerCall(redis, socket, payload.callId, payload.targetUserId)
      if (pair) io.to(userRoom(pair.peerId)).emit('call:ice-candidate', payload)
    })
    socket.on('call:connected', async (payload) => {
      const call = validId(payload?.callId) ? await readCall(redis, payload.callId) : null
      if (!call || ![call.callerId, call.calleeId].includes(socket.data.userId)) return
      await redis.hset(callKey(call.callId), 'status', 'connected', 'startedAt', new Date().toISOString())
      await lifecycle(call.callId, 'connected').catch(() => undefined)
    })
    socket.on('call:end', async (payload: CallEndPayload) => {
      if (!validId(payload?.callId) || !validId(payload?.targetUserId)) return
      const pair = await peerCall(redis, socket, payload.callId, payload.targetUserId)
      if (!pair) return
      const outcome: CallOutcome = pair.call.status === 'ringing' ? 'canceled' : pair.call.status === 'connected' ? 'completed' : 'failed'
      await finalize(io, redis, payload.callId, outcome, String(payload.reason || 'ended').slice(0, 120))
    })
    socket.on('call:resume', async (payload, ack) => {
      const call = validId(payload?.callId) ? await readCall(redis, payload.callId) : null
      if (!call || ![call.callerId, call.calleeId].includes(socket.data.userId)) return safeAck(ack, { ok: false, code: 'not_found', message: 'Call is no longer active' })
      socket.join(userRoom(socket.data.userId)); await touch(redis, socket); safeAck(ack, { ok: true })
    })

    socket.on('disconnect', async () => {
      clearInterval(heartbeat)
      await redis.srem(onlineKey(socket.data.userId), socket.id)
      if (await redis.scard(onlineKey(socket.data.userId))) return
      socket.to(orgRoom(socket.data.organizationId)).emit('user:status', { userId: socket.data.userId, isOnline: false })
      const callId = await redis.get(busyKey(socket.data.userId))
      if (callId) setTimeout(async () => {
        if (!await redis.exists(onlineKey(socket.data.userId))) await finalize(io, redis, callId, 'failed', 'disconnected')
      }, 15_000)
    })
  })

  setInterval(async () => {
    const item = await redis.lpop('call:finalize:retry')
    if (item) {
      try { const data = JSON.parse(item); await lifecycle(data.callId, 'ended', data.outcome, data.reason) }
      catch { await redis.rpush('call:finalize:retry', item) }
    }
    let cursor = '0'
    do {
      const [next, keys] = await redis.scan(cursor, 'MATCH', 'call:session:*', 'COUNT', 100)
      cursor = next
      for (const key of keys) {
        const call = await readCall(redis, key.slice('call:session:'.length))
        if (call?.status === 'ringing' && Date.now() - Date.parse(call.startedAt) >= 30_000) await finalize(io, redis, call.callId, 'missed', 'no_answer')
      }
    } while (cursor !== '0')
  }, 5_000).unref()
}
