<template>
  <div class="scores-grid">
    <div class="score-card" v-for="gauge in gauges" :key="gauge.label">
      <div class="label">{{ gauge.label }}</div>
      <div class="gauge-wrap">
        <svg width="100" height="100" viewBox="0 0 100 100">
          <circle class="gauge-bg" cx="50" cy="50" r="42" />
          <circle class="gauge-fill" cx="50" cy="50" r="42"
            :stroke="gauge.color"
            :stroke-dasharray="circumference"
            :stroke-dashoffset="gauge.offset"
            stroke-linecap="round" />
        </svg>
        <div class="gauge-text">
          <span class="pct" :style="{color: gauge.color}">
            {{ gauge.value }}<span class="pct-sign">%</span>
          </span>
        </div>
      </div>
    </div>

    <div class="score-card">
      <div class="label">{{ multi ? 'Total In Bed' : 'Total Time' }}</div>
      <div class="big-value">{{ totalDur }}</div>
      <div class="sub">{{ multi ? `${analyses.length} sessions combined` : 'in bed' }}</div>
    </div>

    <div class="score-card">
      <div class="label">{{ multi ? 'Total Asleep' : 'Time Asleep' }}</div>
      <div class="big-value">{{ asleepDur }}</div>
      <div class="sub">actual sleep</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ analyses: Array })

const R = 42
const circumference = 2 * Math.PI * R

function mean(arr) {
  return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0
}
function scoreColor(s) {
  if (s >= 80) return 'var(--green)'
  if (s >= 50) return 'var(--yellow)'
  return 'var(--red)'
}
function fmtDur(m) {
  const h = Math.floor(m / 60), mm = Math.round(m % 60)
  return h > 0 ? `${h}h ${mm}m` : `${mm}m`
}

const single = computed(() => props.analyses.length === 1)
const multi = computed(() => props.analyses.length > 1)

function sum(arr) {
  return arr.reduce((a, b) => a + b, 0)
}

const gauges = computed(() => {
  const aa = props.analyses || []
  if (multi.value) {
    // For multi-session: compute combined efficiency from summed values
    const totalSleep = sum(aa.map(a => (a.light_sleep_min || 0) + (a.deep_sleep_min || 0) + (a.rem_sleep_min || 0)))
    const totalInBed = sum(aa.map(a => a.total_duration_min || 0))
    const efficiency = totalInBed > 0 ? Math.min(100, (totalSleep / totalInBed) * 100) : 0
    // Scores are still averaged — they're qualitative per-session assessments
    const recovery = mean(aa.map(a => a.recovery_score || 0))
    const quality = mean(aa.map(a => a.sleep_quality_score || 0))
    return [
      { label: 'Avg Recovery', value: Math.round(recovery), color: scoreColor(recovery), offset: circumference - (Math.min(100, recovery) / 100) * circumference },
      { label: 'Avg Quality', value: Math.round(quality), color: scoreColor(quality), offset: circumference - (Math.min(100, quality) / 100) * circumference },
      { label: 'Combined Eff.', value: Math.round(efficiency), color: scoreColor(efficiency), offset: circumference - (Math.min(100, efficiency) / 100) * circumference },
    ]
  }
  const recovery = mean(aa.map(a => a.recovery_score || 0))
  const quality = mean(aa.map(a => a.sleep_quality_score || 0))
  const efficiency = Math.min(100, mean(aa.map(a => a.sleep_efficiency || 0)))
  return [
    { label: 'Recovery', value: Math.round(recovery), color: scoreColor(recovery), offset: circumference - (Math.min(100, recovery) / 100) * circumference },
    { label: 'Sleep Quality', value: Math.round(quality), color: scoreColor(quality), offset: circumference - (Math.min(100, quality) / 100) * circumference },
    { label: 'Efficiency', value: Math.round(efficiency), color: scoreColor(efficiency), offset: circumference - (Math.min(100, efficiency) / 100) * circumference },
  ]
})

const totalDur = computed(() => {
  const aa = props.analyses || []
  // Always sum when multi-session (total time in bed across all sessions)
  const m = multi.value
    ? sum(aa.map(a => a.total_duration_min || 0))
    : aa[0]?.total_duration_min || 0
  return fmtDur(m)
})

const asleepDur = computed(() => {
  const aa = props.analyses || []
  // Always sum when multi-session (total actual sleep across all sessions)
  const m = multi.value
    ? sum(aa.map(a => (a.light_sleep_min || 0) + (a.deep_sleep_min || 0) + (a.rem_sleep_min || 0)))
    : sum(aa.map(a => (a.light_sleep_min || 0) + (a.deep_sleep_min || 0) + (a.rem_sleep_min || 0)))
  return fmtDur(m)
})
</script>

<style scoped>
.scores-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.score-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  transition: border-color 0.2s, transform 0.2s;
}
.score-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.label { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }
.gauge-wrap { position: relative; width: 100px; height: 100px; margin: 0 auto 8px; }
.gauge-wrap svg { transform: rotate(-90deg); }
.gauge-bg { fill: none; stroke: var(--surface2); stroke-width: 7; }
.gauge-fill { fill: none; stroke-width: 7; stroke-linecap: round; transition: stroke-dashoffset 0.8s ease, stroke 0.3s; }
.gauge-text { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.pct { font-size: 26px; font-weight: 700; letter-spacing: -1px; }
.pct-sign { font-size: 14px; font-weight: 400; color: var(--text-dim); }
.big-value { font-size: 28px; font-weight: 700; margin-top: 20px; color: var(--text); }
.sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
</style>
