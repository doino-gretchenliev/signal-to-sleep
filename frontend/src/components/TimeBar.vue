<template>
  <div class="time-bar">
    <div class="preset-buttons">
      <button
        v-for="preset in presets"
        :key="preset.label"
        class="preset-btn"
        :class="{ active: activePreset === preset.label }"
        @click="selectPreset(preset)"
      >
        {{ preset.label }}
      </button>
    </div>
    <div class="range-label">{{ rangeLabel }}</div>
  </div>
</template>

<script setup>
import { ref, inject, onMounted } from 'vue'

const { setPreset, rangeLabel } = inject('dateRange')

const presets = [
  { label: 'Last night', days: 1 },
  { label: '3 days', days: 3 },
  { label: '5 days', days: 5 },
  { label: 'Week', days: 7 },
  { label: '2 weeks', days: 14 },
  { label: 'Month', days: 30 },
  { label: '3 months', days: 90 },
]

const activePreset = ref('Week')

const selectPreset = (preset) => {
  activePreset.value = preset.label
  setPreset(preset.days)
}

onMounted(() => {
  // Set default preset on load
  selectPreset(presets[3]) // Week
})
</script>

<style scoped>
.time-bar {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 1rem 0;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}

.preset-buttons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.preset-btn {
  padding: 0.4rem 0.9rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  color: var(--text-dim);
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.preset-btn:hover {
  border-color: var(--accent);
  color: var(--text);
  background: var(--surface2);
}

.preset-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  box-shadow: 0 0 12px rgba(124, 110, 240, 0.3);
}

.range-label {
  padding: 0.4rem 0.9rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  color: var(--text-dim);
  font-size: 0.8rem;
  font-weight: 500;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .preset-btn {
    padding: 0.35rem 0.7rem;
    font-size: 0.75rem;
  }
}
</style>
