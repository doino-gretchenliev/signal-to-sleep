<template>
  <div class="stage-panel">
    <h3>Sleep Stages</h3>
    <div class="stage-track" v-if="total > 0">
      <div v-for="s in segments" :key="s.key"
        class="stage-seg"
        :style="{ width: s.pct + '%', backgroundColor: s.color }"
        :title="`${s.label}: ${s.duration} (${s.pct.toFixed(0)}%)`">
      </div>
    </div>
    <div class="stage-track empty" v-else>
      <span class="no-data">No stage data</span>
    </div>
    <div class="stage-details">
      <div v-for="s in segments" :key="'d'+s.key" class="stage-card">
        <span class="card-dot" :style="{ backgroundColor: s.color }"></span>
        <div class="card-info">
          <span class="card-name">{{ s.label }}</span>
          <span class="card-stats">
            <span class="card-dur">{{ s.duration }}</span>
            <span class="card-pct">{{ s.pct.toFixed(0) }}%</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { STAGES } from '../utils/stageColors'

const props = defineProps({ analyses: Array })

function fmtDur(m) {
  const h = Math.floor(m / 60), mm = Math.round(m % 60)
  return h > 0 ? `${h}h ${mm}m` : `${mm}m`
}
function mean(arr) { return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0 }

// STAGES imported from stageColors.js

const total = computed(() => {
  const aa = props.analyses || []
  return STAGES.reduce((s, st) => s + mean(aa.map(a => a[st.field] || 0)), 0)
})

const segments = computed(() => {
  const aa = props.analyses || []
  const t = total.value || 1
  return STAGES.map(st => {
    const mins = mean(aa.map(a => a[st.field] || 0))
    return { ...st, mins, pct: (mins / t) * 100, duration: fmtDur(mins) }
  })
})
</script>

<style scoped>
.stage-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}
h3 { font-size: 14px; font-weight: 500; color: var(--text-dim); margin: 0 0 16px; }
.stage-track {
  display: flex;
  height: 32px;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 20px;
  background: transparent;
  padding: 0;
  border: none;
}
.stage-track.empty {
  background: var(--surface2);
  height: 32px;
  border-radius: 8px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.no-data { font-size: 12px; color: var(--text-dim); }
.stage-seg {
  min-width: 2px;
  transition: width 0.6s ease;
}
.stage-details {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stage-card {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--surface2, rgba(255,255,255,0.04));
  border-radius: 8px;
  padding: 10px 12px;
}
.card-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  flex-shrink: 0;
}
.card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.card-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
}
.card-stats {
  display: flex;
  align-items: center;
  gap: 8px;
}
.card-dur {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}
.card-pct {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}
</style>
