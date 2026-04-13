<template>
  <div class="metrics-cards">
    <div class="mcard" v-for="m in metrics" :key="m.label">
      <div class="mcard-header">
        <span class="mcard-icon" :style="{ color: m.color, background: m.bg }">
          <svg v-if="m.icon === 'clock'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <svg v-else-if="m.icon === 'eye'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
          </svg>
          <svg v-else-if="m.icon === 'zap'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
          <svg v-else-if="m.icon === 'shuffle'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/>
            <polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/>
            <line x1="4" y1="4" x2="9" y2="9"/>
          </svg>
          <svg v-else-if="m.icon === 'moon'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 20V10M12 20V4M6 20v-6"/>
          </svg>
        </span>
        <span class="mcard-label">{{ m.label }}</span>
      </div>
      <div class="mcard-body">
        <span class="mcard-value">{{ m.value }}</span>
        <span class="mcard-unit">{{ m.unit }}</span>
      </div>
      <div class="mcard-sub" :class="m.qualityCls">{{ m.qualityText }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ analyses: Array })

function avg(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null }
function sum(arr) { return arr.reduce((a, b) => a + b, 0) }

function fmt(v, decimals = 1) {
  if (v == null) return '--'
  return Number(v).toFixed(decimals)
}

const multi = computed(() => (props.analyses || []).length > 1)

// For multi-session: weighted average by sleep duration (more meaningful than simple avg)
function weightedAvg(aa, key) {
  const pairs = aa
    .filter(a => a[key] != null)
    .map(a => ({
      val: a[key],
      weight: (a.light_sleep_min || 0) + (a.deep_sleep_min || 0) + (a.rem_sleep_min || 0)
    }))
    .filter(p => p.weight > 0)
  if (!pairs.length) return null
  const totalW = sum(pairs.map(p => p.weight))
  return sum(pairs.map(p => p.val * p.weight)) / totalW
}

const metrics = computed(() => {
  const aa = props.analyses || []
  if (!aa.length) return []
  const isMulti = multi.value

  // For multi-session: use weighted averages for per-session metrics,
  // sum for cumulative metrics (WASO, awakenings)
  const onsetAvg = isMulti ? weightedAvg(aa, 'onset_latency_min') : avg(aa.map(a => a.onset_latency_min).filter(v => v != null))
  let onsetQ = { text: '', cls: '' }
  if (onsetAvg != null) {
    if (onsetAvg <= 15) onsetQ = { text: 'Normal', cls: 'q-good' }
    else if (onsetAvg <= 30) onsetQ = { text: 'Slightly Long', cls: 'q-ok' }
    else onsetQ = { text: 'Prolonged', cls: 'q-low' }
  }

  // WASO: sum across sessions when multi (total wake time across all sessions)
  const wasoVals = aa.map(a => a.waso_min).filter(v => v != null)
  const wasoVal = isMulti ? sum(wasoVals) : avg(wasoVals)
  let wasoQ = { text: '', cls: '' }
  if (wasoVal != null && wasoVals.length) {
    const wasoRef = isMulti ? wasoVal / aa.length : wasoVal // per-session reference for quality
    if (wasoRef <= 20) wasoQ = { text: 'Excellent', cls: 'q-good' }
    else if (wasoRef <= 40) wasoQ = { text: 'Normal', cls: 'q-ok' }
    else wasoQ = { text: 'High', cls: 'q-low' }
  }

  // Awakenings: sum across sessions when multi
  const awakVals = aa.map(a => a.num_awakenings).filter(v => v != null)
  const awakVal = isMulti ? sum(awakVals) : avg(awakVals)
  let awakQ = { text: '', cls: '' }
  if (awakVal != null && awakVals.length) {
    const awakRef = isMulti ? awakVal / aa.length : awakVal
    if (awakRef <= 3) awakQ = { text: 'Minimal', cls: 'q-good' }
    else if (awakRef <= 8) awakQ = { text: 'Normal', cls: 'q-ok' }
    else awakQ = { text: 'Fragmented', cls: 'q-low' }
  }

  // Fragmentation: weighted average (it's a rate, so averaging makes sense)
  const fragAvg = isMulti ? weightedAvg(aa, 'fragmentation_index') : avg(aa.map(a => a.fragmentation_index).filter(v => v != null))
  let fragQ = { text: '', cls: '' }
  if (fragAvg != null) {
    if (fragAvg <= 2) fragQ = { text: 'Excellent', cls: 'q-good' }
    else if (fragAvg <= 5) fragQ = { text: 'Normal', cls: 'q-ok' }
    else fragQ = { text: 'High', cls: 'q-low' }
  }

  // Time to Deep: weighted average
  const deepAvg = isMulti ? weightedAvg(aa, 'time_to_deep_min') : avg(aa.map(a => a.time_to_deep_min).filter(v => v != null))
  let deepQ = { text: '', cls: '' }
  if (deepAvg != null) {
    if (deepAvg <= 30) deepQ = { text: 'Normal', cls: 'q-good' }
    else if (deepAvg <= 60) deepQ = { text: 'Delayed', cls: 'q-ok' }
    else deepQ = { text: 'Very Late', cls: 'q-low' }
  }

  // Time to REM: weighted average
  const remAvg = isMulti ? weightedAvg(aa, 'time_to_rem_min') : avg(aa.map(a => a.time_to_rem_min).filter(v => v != null))
  let remQ = { text: '', cls: '' }
  if (remAvg != null) {
    if (remAvg <= 90) remQ = { text: 'Normal', cls: 'q-good' }
    else if (remAvg <= 120) remQ = { text: 'Delayed', cls: 'q-ok' }
    else remQ = { text: 'Very Late', cls: 'q-low' }
  }

  return [
    {
      label: isMulti ? 'Avg Onset' : 'Sleep Onset',
      icon: 'clock',
      color: '#60a5fa',
      bg: 'rgba(96,165,250,0.15)',
      value: fmt(onsetAvg),
      unit: 'min',
      qualityText: onsetQ.text,
      qualityCls: onsetQ.cls,
    },
    {
      label: isMulti ? 'Total WASO' : 'WASO',
      icon: 'eye',
      color: '#fbbf24',
      bg: 'rgba(251,191,36,0.15)',
      value: fmt(wasoVal),
      unit: 'min',
      qualityText: wasoQ.text,
      qualityCls: wasoQ.cls,
    },
    {
      label: isMulti ? 'Total Awakenings' : 'Awakenings',
      icon: 'zap',
      color: '#f87171',
      bg: 'rgba(248,113,113,0.15)',
      value: awakVal != null && awakVals.length ? Math.round(awakVal) : '--',
      unit: '',
      qualityText: awakQ.text,
      qualityCls: awakQ.cls,
    },
    {
      label: isMulti ? 'Avg Fragmentation' : 'Fragmentation',
      icon: 'shuffle',
      color: '#fb923c',
      bg: 'rgba(251,146,60,0.15)',
      value: fmt(fragAvg, 1),
      unit: '/hr',
      qualityText: fragQ.text,
      qualityCls: fragQ.cls,
    },
    {
      label: isMulti ? 'Avg Time to Deep' : 'Time to Deep',
      icon: 'moon',
      color: '#3b82f6',
      bg: 'rgba(59,130,246,0.15)',
      value: fmt(deepAvg),
      unit: 'min',
      qualityText: deepQ.text,
      qualityCls: deepQ.cls,
    },
    {
      label: isMulti ? 'Avg Time to REM' : 'Time to REM',
      icon: 'bars',
      color: '#e879f9',
      bg: 'rgba(232,121,249,0.15)',
      value: fmt(remAvg),
      unit: 'min',
      qualityText: remQ.text,
      qualityCls: remQ.cls,
    },
  ]
})
</script>

<style scoped>
.metrics-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.mcard {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 18px;
  transition: border-color 0.2s, transform 0.2s;
}
.mcard:hover { border-color: var(--accent); transform: translateY(-2px); }

.mcard-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.mcard-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 7px;
}

.mcard-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-dim);
}

.mcard-body {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.mcard-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  letter-spacing: -0.5px;
}

.mcard-unit {
  font-size: 14px;
  font-weight: 400;
  color: var(--text-dim);
}

.mcard-sub {
  font-size: 11px;
  font-weight: 500;
  margin-top: 6px;
  min-height: 16px;
}
.q-good { color: var(--green, #34d399); }
.q-ok   { color: var(--yellow, #fbbf24); }
.q-fair { color: #fb923c; }
.q-low  { color: var(--red, #ef4444); }

@media (max-width: 900px) {
  .metrics-cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 500px) {
  .metrics-cards { grid-template-columns: 1fr; }
  .mcard-value { font-size: 24px; }
}
</style>
