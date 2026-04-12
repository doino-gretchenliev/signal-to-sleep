<template>
  <div class="energy-wrap">
    <div class="energy-gauge">
      <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="gauge-svg">
        <!-- Background arc -->
        <path :d="bgArc" fill="none" stroke="var(--surface2, #2a2e3d)" :stroke-width="STROKE" stroke-linecap="round" />
        <!-- Filled arc -->
        <path :d="fillArc" fill="none" :stroke="gaugeColor" :stroke-width="STROKE" stroke-linecap="round"
          :style="{ transition: 'd 0.8s ease, stroke 0.3s' }" />
        <!-- Glow -->
        <path :d="fillArc" fill="none" :stroke="gaugeColor" :stroke-width="STROKE + 4" stroke-linecap="round"
          opacity="0.15" :style="{ filter: 'blur(6px)' }" />
      </svg>
      <div class="gauge-center">
        <div class="gauge-pct" :style="{ color: gaugeColor }">{{ energyPct }}<span class="gauge-sign">%</span></div>
        <div class="gauge-label">Energy</div>
      </div>
    </div>

    <div class="energy-bars">
      <div class="bar-row" v-for="bar in bars" :key="bar.label">
        <div class="bar-label">
          <span class="bar-dot" :style="{ background: bar.color }"></span>
          {{ bar.label }}
        </div>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: bar.pct + '%', background: bar.color }"></div>
        </div>
        <div class="bar-value">{{ bar.display }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ analyses: Array })

const SIZE = 160
const STROKE = 12
const R = (SIZE - STROKE) / 2
const CX = SIZE / 2
const CY = SIZE / 2

// Arc from 135° to 405° (270° sweep)
const START_ANGLE = 135
const SWEEP = 270

function polarToCart(cx, cy, r, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function arcPath(startDeg, endDeg) {
  const s = polarToCart(CX, CY, R, startDeg)
  const e = polarToCart(CX, CY, R, endDeg)
  const sweep = endDeg - startDeg
  const large = sweep > 180 ? 1 : 0
  return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`
}

const bgArc = computed(() => arcPath(START_ANGLE, START_ANGLE + SWEEP))

function mean(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0 }

// Energy model: weighted combination of recovery factors
const energyData = computed(() => {
  const aa = props.analyses || []
  if (!aa.length) return { pct: 0, deep: 0, rem: 0, hrv: 0, efficiency: 0 }

  const recovery = mean(aa.map(a => a.recovery_score || 0))
  const quality = mean(aa.map(a => a.sleep_quality_score || 0))
  const efficiency = mean(aa.map(a => a.sleep_efficiency || 0))
  const totalMin = mean(aa.map(a => a.total_duration_min || 0))
  const deepMin = mean(aa.map(a => a.deep_sleep_min || 0))
  const remMin = mean(aa.map(a => a.rem_sleep_min || 0))
  const deepPct = totalMin > 0 ? (deepMin / totalMin) * 100 : 0
  const remPct = totalMin > 0 ? (remMin / totalMin) * 100 : 0

  // Duration score: 7-9h is 100%, scale down outside
  const durHours = totalMin / 60
  const durScore = durHours >= 7 && durHours <= 9 ? 100
    : durHours < 7 ? (durHours / 7) * 100
    : Math.max(60, 100 - (durHours - 9) * 10)

  // Deep sleep score: 15-25% is ideal
  const deepScore = deepPct >= 15 && deepPct <= 25 ? 100
    : deepPct < 15 ? (deepPct / 15) * 100
    : Math.max(60, 100 - (deepPct - 25) * 3)

  // REM score: 20-25% is ideal
  const remScore = remPct >= 20 && remPct <= 25 ? 100
    : remPct < 20 ? (remPct / 20) * 100
    : Math.max(60, 100 - (remPct - 25) * 3)

  // Weighted energy
  const energy = Math.round(
    recovery * 0.30 +
    quality * 0.20 +
    durScore * 0.15 +
    deepScore * 0.15 +
    remScore * 0.10 +
    Math.min(100, efficiency) * 0.10
  )

  return {
    pct: Math.min(100, Math.max(0, energy)),
    deep: Math.round(deepScore),
    rem: Math.round(remScore),
    duration: Math.round(durScore),
    efficiency: Math.round(Math.min(100, efficiency)),
    recovery: Math.round(recovery),
  }
})

const energyPct = computed(() => energyData.value.pct)

const fillArc = computed(() => {
  const frac = Math.max(0.01, energyPct.value / 100)
  return arcPath(START_ANGLE, START_ANGLE + SWEEP * frac)
})

const gaugeColor = computed(() => {
  const p = energyPct.value
  if (p >= 70) return '#34d399'
  if (p >= 40) return '#fbbf24'
  return '#ef4444'
})

const bars = computed(() => {
  const d = energyData.value
  return [
    { label: 'Recovery', pct: d.recovery, display: d.recovery + '%', color: '#7c6ef0' },
    { label: 'Deep Sleep', pct: d.deep, display: d.deep + '%', color: '#3b82f6' },
    { label: 'REM Sleep', pct: d.rem, display: d.rem + '%', color: '#e879f9' },
    { label: 'Duration', pct: d.duration, display: d.duration + '%', color: '#2dd4bf' },
    { label: 'Efficiency', pct: d.efficiency, display: d.efficiency + '%', color: '#60a5fa' },
  ]
})
</script>

<style scoped>
.energy-wrap {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 8px 0;
}

.energy-gauge {
  position: relative;
  width: 160px;
  height: 160px;
  flex-shrink: 0;
}
.gauge-svg { width: 100%; height: 100%; }

.gauge-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.gauge-pct {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -1px;
}
.gauge-sign { font-size: 16px; font-weight: 400; opacity: 0.6; }
.gauge-label { font-size: 12px; color: var(--text-dim); margin-top: 4px; }

.energy-bars {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bar-label {
  width: 100px;
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.bar-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.bar-track {
  flex: 1;
  height: 6px;
  background: var(--surface2, #2a2e3d);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}
.bar-value {
  width: 36px;
  font-size: 12px;
  color: var(--text);
  text-align: right;
  font-weight: 600;
}

@media (max-width: 640px) {
  .energy-wrap { flex-direction: column; gap: 20px; }
  .energy-gauge { width: 130px; height: 130px; }
  .gauge-pct { font-size: 26px; }
  .bar-label { width: 80px; font-size: 11px; }
}
</style>
