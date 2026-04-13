/**
 * useWebSocket - Singleton reactive WebSocket with auto-reconnect.
 *
 * Returns reactive health/status refs and a way to register event handlers.
 * Auto-reconnects with exponential backoff (1s → 30s cap).
 */
import { ref, reactive, onBeforeUnmount } from 'vue'

// Singleton state — shared across all callers
const connected = ref(false)
const health = reactive({
  db: false,
  mqtt: false,
  mqttTopic: '',
  messageCount: 0,
  uptimeSec: 0,
  version: '',
  activeSleep: null,  // { period_id, source, started_at, duration_min } or null
})

let ws = null
let reconnectTimer = null
let backoff = 1000
const MAX_BACKOFF = 30000
const handlers = new Set()
let started = false

function getWsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

  ws = new WebSocket(getWsUrl())

  ws.onopen = () => {
    connected.value = true
    backoff = 1000
  }

  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data)

      // Handle health updates internally
      if (data.type === 'health_update') {
        health.db = data.db ?? false
        health.mqtt = data.mqtt ?? false
        health.mqttTopic = data.mqtt_topic ?? ''
        health.messageCount = data.message_count ?? 0
        health.uptimeSec = data.uptime_sec ?? 0
        health.version = data.version ?? ''
        health.activeSleep = data.active_sleep ?? null
      }

      // Dispatch to all registered handlers
      for (const fn of handlers) {
        try { fn(data) } catch (e) { console.warn('[WS] handler error:', e) }
      }
    } catch (e) {
      console.warn('[WS] bad message:', ev.data)
    }
  }

  ws.onclose = () => {
    connected.value = false
    health.db = false
    health.mqtt = false
    scheduleReconnect()
  }

  ws.onerror = () => {
    ws.close()
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    backoff = Math.min(backoff * 2, MAX_BACKOFF)
    connect()
  }, backoff)
}

/**
 * Start the singleton WS connection (idempotent).
 */
function start() {
  if (started) return
  started = true
  connect()
}

/**
 * Register an event handler. Returns an unregister function.
 */
function onEvent(fn) {
  handlers.add(fn)
  return () => handlers.delete(fn)
}

export function useWebSocket(handler) {
  start()

  let unregister = null
  if (handler) {
    unregister = onEvent(handler)
    onBeforeUnmount(() => unregister())
  }

  return { connected, health }
}
