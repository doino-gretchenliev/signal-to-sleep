<template>
  <header class="app-header">
    <div class="header-content">
      <div class="logo-section">
        <img src="/logo-header.png" alt="Signal-to-Sleep" class="logo-img" />
      </div>

      <div class="health-section">
        <!-- Backend WS connection -->
        <div class="badge">
          <div class="dot" :class="{ up: connected }"></div>
          <span class="label">Backend</span>
        </div>

        <!-- Database -->
        <div class="badge">
          <div class="dot" :class="{ up: health.db }"></div>
          <span class="label">Database</span>
        </div>

        <!-- MQTT -->
        <div class="badge">
          <div class="dot" :class="{ up: health.mqtt }"></div>
          <span class="label">MQTT</span>
        </div>

        <!-- MQTT Topic + message count -->
        <div class="badge mqtt-status" v-if="health.mqttTopic">
          <span class="label">{{ health.mqttTopic }}</span>
          <span class="count">{{ health.messageCount.toLocaleString() }}</span>
        </div>

        <!-- Sleep control -->
        <button
          v-if="!health.activeSleep"
          class="badge sleep-btn start"
          :disabled="busy"
          @click="handleStart"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <span class="label">Start Sleep</span>
        </button>

        <div v-else class="badge sleep-active">
          <div class="pulse-dot"></div>
          <span class="label">{{ sleepLabel }}</span>
          <span class="sleep-timer">{{ sleepElapsed }}</span>
          <button
            class="stop-btn"
            :disabled="busy"
            @click="handleStop"
          >Stop</button>
        </div>
      </div>

      <div class="uptime-section">
        <span class="label">Uptime</span>
        <span class="value">{{ uptime }}</span>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed, inject, onMounted, onUnmounted } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'
import { startSleep, stopSleep } from '../composables/useApi'

const { connected, health } = useWebSocket()
const busy = ref(false)
const sleepData = inject('sleepData', {})
const reloadPeriods = sleepData.reloadPeriods

// ── Uptime counter ─────────────────────────────────
let uptimeTimer = null
const localOffset = ref(0)

const uptime = computed(() => {
  const total = Math.floor(health.uptimeSec + localOffset.value)
  if (total <= 0) return '--:--:--'
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

onMounted(() => {
  uptimeTimer = setInterval(() => {
    if (connected.value) localOffset.value++
  }, 1000)
})

onUnmounted(() => {
  clearInterval(uptimeTimer)
})

let lastUptimeSec = 0
const checkReset = setInterval(() => {
  if (health.uptimeSec !== lastUptimeSec) {
    lastUptimeSec = health.uptimeSec
    localOffset.value = 0
  }
}, 1000)
onUnmounted(() => clearInterval(checkReset))

// ── Sleep in-progress ──────────────────────────────
const sleepLabel = computed(() => {
  if (!health.activeSleep) return ''
  return health.activeSleep.source === 'manual' ? 'Sleeping (manual)' : 'Sleeping (auto)'
})

const sleepElapsed = computed(() => {
  if (!health.activeSleep) return ''
  const mins = health.activeSleep.duration_min + (localOffset.value / 60)
  if (mins < 1) return '<1m'
  const h = Math.floor(mins / 60)
  const m = Math.floor(mins % 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
})

// ── Actions ────────────────────────────────────────
async function handleStart() {
  busy.value = true
  try {
    const res = await startSleep()
    if (res.status === 'ok') {
      // Optimistic update — show indicator immediately
      health.activeSleep = {
        period_id: res.period_id,
        source: 'manual',
        started_at: new Date().toISOString(),
        duration_min: 0,
      }
      localOffset.value = 0
      // Refresh period list
      if (reloadPeriods) await reloadPeriods()
    }
  } catch (e) {
    console.error('Failed to start sleep:', e)
  } finally {
    busy.value = false
  }
}

async function handleStop() {
  busy.value = true
  try {
    const res = await stopSleep()
    if (res.status === 'ok') {
      // Optimistic update — clear indicator immediately
      health.activeSleep = null
      // Refresh period list
      if (reloadPeriods) await reloadPeriods()
    }
  } catch (e) {
    console.error('Failed to stop sleep:', e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.app-header {
  background: linear-gradient(135deg, #0a0e27 0%, #16213e 100%);
  border-bottom: 1px solid rgba(59, 130, 246, 0.2);
  padding: 1rem 2rem;
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 2rem;
  max-width: 1400px;
  margin: 0 auto;
}

.logo-img {
  height: 52px;
  width: auto;
  display: block;
  object-fit: contain;
}

.health-section {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex: 1;
}

.badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: rgba(31, 41, 55, 0.6);
  border: 1px solid rgba(75, 85, 99, 0.5);
  border-radius: 9999px;
  font-size: 0.875rem;
  color: #d1d5db;
  transition: all 0.2s ease;
}

.badge:hover { border-color: rgba(75, 85, 99, 0.8); }

.dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: #ef4444;
  transition: background-color 0.3s ease;
}

.dot.up {
  background: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.5);
}

.label { font-weight: 500; }

.mqtt-status { gap: 0.75rem; }

.count {
  background: rgba(59, 130, 246, 0.2);
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #60a5fa;
}

/* ── Start Sleep button ──────────────────────────── */
.sleep-btn {
  cursor: pointer;
  border: none;
  font-family: inherit;
}

.sleep-btn.start {
  background: rgba(139, 92, 246, 0.15);
  border: 1px solid rgba(139, 92, 246, 0.4);
  color: #c4b5fd;
}

.sleep-btn.start:hover:not(:disabled) {
  background: rgba(139, 92, 246, 0.25);
  border-color: rgba(139, 92, 246, 0.6);
}

.sleep-btn.start:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sleep-btn.start svg {
  color: #a78bfa;
}

/* ── Sleep in-progress badge ─────────────────────── */
.sleep-active {
  background: rgba(139, 92, 246, 0.15);
  border-color: rgba(139, 92, 246, 0.5);
  gap: 0.5rem;
}

.pulse-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: #a78bfa;
  box-shadow: 0 0 8px rgba(167, 139, 250, 0.6);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 8px rgba(167, 139, 250, 0.6); }
  50% { opacity: 0.5; box-shadow: 0 0 16px rgba(167, 139, 250, 0.3); }
}

.sleep-active .label {
  color: #c4b5fd;
  font-weight: 600;
}

.sleep-timer {
  background: rgba(139, 92, 246, 0.25);
  padding: 0.25rem 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #a78bfa;
  font-family: 'Monaco', 'Courier New', monospace;
}

.stop-btn {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #fca5a5;
  padding: 0.2rem 0.6rem;
  border-radius: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
}

.stop-btn:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.35);
  border-color: rgba(239, 68, 68, 0.6);
  color: #fecaca;
}

.stop-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── Uptime ──────────────────────────────────────── */
.uptime-section {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 1rem;
  background: rgba(31, 41, 55, 0.6);
  border: 1px solid rgba(75, 85, 99, 0.5);
  border-radius: 0.5rem;
  font-size: 0.875rem;
}

.uptime-section .label { color: #9ca3af; font-weight: 500; }

.uptime-section .value {
  color: #60a5fa;
  font-weight: 600;
  font-family: 'Monaco', 'Courier New', monospace;
  letter-spacing: 0.5px;
}

@media (max-width: 1024px) {
  .header-content { flex-direction: column; gap: 1rem; }
  .logo-img { height: 44px; }
  .health-section { width: 100%; justify-content: flex-start; }
  .uptime-section { align-self: flex-start; }
}

@media (max-width: 640px) {
  .app-header { padding: 0.75rem 1rem; }
  .header-content { gap: 0.5rem; }
  .logo-img { height: 36px; }
  .badge, .uptime-section { font-size: 0.75rem; padding: 0.375rem 0.75rem; }
  .health-section { gap: 0.5rem; flex-wrap: wrap; }
}
</style>
