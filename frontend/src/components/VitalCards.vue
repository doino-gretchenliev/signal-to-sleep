<template>
  <div class="vital-cards">
    <div class="vcard">
      <div class="vcard-header">
        <span class="vcard-icon hrv-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
        </span>
        <span class="vcard-label">Resting HRV</span>
      </div>
      <div class="vcard-body">
        <span class="vcard-value">{{ hrvValue }}</span>
        <span class="vcard-unit">ms</span>
      </div>
      <div class="vcard-sub" :class="hrvQuality.cls">{{ hrvQuality.text }}</div>
    </div>

    <div class="vcard">
      <div class="vcard-header">
        <span class="vcard-icon hr-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
        </span>
        <span class="vcard-label">Resting HR</span>
      </div>
      <div class="vcard-body">
        <span class="vcard-value">{{ hrValue }}</span>
        <span class="vcard-unit">bpm</span>
      </div>
      <div class="vcard-sub" :class="hrQuality.cls">{{ hrQuality.text }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ analyses: Array })

function mean(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0 }

const hrvValue = computed(() => {
  const vals = (props.analyses || []).map(a => a.avg_hrv || 0).filter(v => v > 0)
  return vals.length ? Math.round(mean(vals) * 10) / 10 : '--'
})

const hrValue = computed(() => {
  const vals = (props.analyses || []).map(a => a.min_heart_rate || a.avg_heart_rate || 0).filter(v => v > 0)
  return vals.length ? Math.round(mean(vals) * 10) / 10 : '--'
})

const hrvQuality = computed(() => {
  const v = typeof hrvValue.value === 'number' ? hrvValue.value : 0
  if (v >= 50) return { text: 'Excellent', cls: 'q-good' }
  if (v >= 30) return { text: 'Good', cls: 'q-ok' }
  if (v >= 15) return { text: 'Fair', cls: 'q-fair' }
  if (v > 0) return { text: 'Low', cls: 'q-low' }
  return { text: '', cls: '' }
})

const hrQuality = computed(() => {
  const v = typeof hrValue.value === 'number' ? hrValue.value : 999
  if (v < 55) return { text: 'Athletic', cls: 'q-good' }
  if (v < 65) return { text: 'Excellent', cls: 'q-good' }
  if (v < 75) return { text: 'Good', cls: 'q-ok' }
  if (v < 85) return { text: 'Average', cls: 'q-fair' }
  return { text: 'Elevated', cls: 'q-low' }
})
</script>

<style scoped>
.vital-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}

.vcard {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 24px;
  transition: border-color 0.2s, transform 0.2s;
}
.vcard:hover { border-color: var(--accent); transform: translateY(-2px); }

.vcard-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.vcard-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
}
.hrv-icon { color: #a78bfa; background: rgba(167,139,250,0.15); }
.hr-icon  { color: #f87171; background: rgba(248,113,113,0.15); }

.vcard-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-dim);
}

.vcard-body {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.vcard-value {
  font-size: 36px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  letter-spacing: -1px;
}

.vcard-unit {
  font-size: 16px;
  font-weight: 400;
  color: var(--text-dim);
}

.vcard-sub {
  font-size: 12px;
  font-weight: 500;
  margin-top: 8px;
}
.q-good { color: var(--green, #34d399); }
.q-ok   { color: var(--yellow, #fbbf24); }
.q-fair { color: #fb923c; }
.q-low  { color: var(--red, #ef4444); }

@media (max-width: 640px) {
  .vital-cards { grid-template-columns: 1fr; }
  .vcard-value { font-size: 28px; }
}
</style>
