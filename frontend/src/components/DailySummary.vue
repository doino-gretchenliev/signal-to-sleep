<template>
  <div class="daily-summary" v-if="show">
    <div class="summary-header">
      <h3 class="summary-title">Daily Summary</h3>
      <span class="summary-sub">{{ analyses.length }} sessions combined</span>
    </div>
    <div class="summary-stats">
      <div class="stat">
        <span class="stat-label">Total Sleep</span>
        <span class="stat-value">{{ totalSleep }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Total In Bed</span>
        <span class="stat-value">{{ totalInBed }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Deep</span>
        <span class="stat-value deep">{{ totalDeep }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">REM</span>
        <span class="stat-value rem">{{ totalREM }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Light</span>
        <span class="stat-value light">{{ totalLight }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Awake</span>
        <span class="stat-value awake">{{ totalAwake }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Efficiency</span>
        <span class="stat-value" :class="effClass">{{ efficiency }}%</span>
      </div>
      <div class="stat">
        <span class="stat-label">Avg HR</span>
        <span class="stat-value">{{ avgHR }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ analyses: Array })

const show = computed(() => (props.analyses || []).length > 1)

function sum(arr, key) {
  return arr.reduce((t, a) => t + (a[key] || 0), 0)
}

function fmt(min) {
  const h = Math.floor(min / 60), m = Math.round(min % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const aa = computed(() => props.analyses || [])

const deepMin = computed(() => sum(aa.value, 'deep_sleep_min'))
const remMin = computed(() => sum(aa.value, 'rem_sleep_min'))
const lightMin = computed(() => sum(aa.value, 'light_sleep_min'))
const awakeMin = computed(() => sum(aa.value, 'awake_min'))
const sleepMin = computed(() => deepMin.value + remMin.value + lightMin.value)
const inBedMin = computed(() => sum(aa.value, 'total_duration_min'))

const totalSleep = computed(() => fmt(sleepMin.value))
const totalInBed = computed(() => fmt(inBedMin.value))
const totalDeep = computed(() => fmt(deepMin.value))
const totalREM = computed(() => fmt(remMin.value))
const totalLight = computed(() => fmt(lightMin.value))
const totalAwake = computed(() => fmt(awakeMin.value))

const efficiency = computed(() => {
  if (inBedMin.value <= 0) return '--'
  return Math.round(sleepMin.value / inBedMin.value * 100)
})

const effClass = computed(() => {
  const v = typeof efficiency.value === 'number' ? efficiency.value : 0
  if (v >= 85) return 'eff-good'
  if (v >= 70) return 'eff-ok'
  return 'eff-low'
})

const avgHR = computed(() => {
  const hrs = aa.value.map(a => a.avg_heart_rate).filter(v => v != null && v > 0)
  if (!hrs.length) return '--'
  return Math.round(hrs.reduce((a, b) => a + b, 0) / hrs.length)
})
</script>

<style scoped>
.daily-summary {
  background: linear-gradient(135deg, rgba(124, 110, 240, 0.08) 0%, rgba(59, 130, 246, 0.08) 100%);
  border: 1px solid rgba(124, 110, 240, 0.25);
  border-radius: 14px;
  padding: 20px 24px;
  margin-bottom: 24px;
}

.summary-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.summary-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
}

.summary-sub {
  font-size: 12px;
  color: var(--text-dim);
}

.summary-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 80px;
}

.stat-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.stat-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.5px;
}

.stat-value.deep { color: var(--deep); }
.stat-value.rem { color: var(--rem); }
.stat-value.light { color: var(--light); }
.stat-value.awake { color: var(--awake); }
.stat-value.eff-good { color: var(--green); }
.stat-value.eff-ok { color: var(--yellow); }
.stat-value.eff-low { color: var(--red); }

@media (max-width: 640px) {
  .summary-stats { gap: 12px; }
  .stat { min-width: 70px; }
  .stat-value { font-size: 18px; }
}
</style>
