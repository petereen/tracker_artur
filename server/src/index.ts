import { createServer } from 'node:http'
import { createAdapter } from '@socket.io/redis-adapter'
import { Redis } from 'ioredis'
import { Server } from 'socket.io'
import type { ClientToServerEvents, ServerToClientEvents, SignalingSocketData } from '../../types/call.js'
import { registerCallHandler } from './callHandler.js'

const port = Number(process.env.PORT || 8020)
const redisUrl = process.env.CALL_REDIS_URL || 'redis://redis:6379/1'
const allowedOrigins = (process.env.CORS_ORIGINS || 'https://erp.oyuns.mn').split(',').map((value) => value.trim()).filter(Boolean)
if (!process.env.CALL_SIGNALING_SECRET) throw new Error('CALL_SIGNALING_SECRET is required')
const httpServer = createServer((request, response) => {
  if (request.url === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end('{"status":"ok"}')
    return
  }
  response.writeHead(404).end()
})
const pub = new Redis(redisUrl, { maxRetriesPerRequest: null })
const sub = pub.duplicate()
const io = new Server<ClientToServerEvents, ServerToClientEvents, Record<string, never>, SignalingSocketData>(httpServer, {
  path: '/socket.io',
  cors: { origin: allowedOrigins, credentials: true },
  maxHttpBufferSize: 256_000,
  transports: ['websocket', 'polling'],
})
io.adapter(createAdapter(pub, sub))
registerCallHandler(io, pub)
httpServer.listen(port)

const shutdown = async () => {
  io.close()
  await Promise.allSettled([pub.quit(), sub.quit()])
  httpServer.close(() => process.exit(0))
}
process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
