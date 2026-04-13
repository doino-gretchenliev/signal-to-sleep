<template>
  <div class="app">
    <AppHeader />
    <div class="container">
      <TimeBar />
      <PeriodsList />
      <div v-if="selectedAnalyses.length" id="dashboard-content">
        <DailySummary :analyses="selectedAnalyses" />
        <div class="chart-panel arch-panel">
          <h3>Sleep Timeline</h3>
          <SleepArchChart :items="selectedItems" />
          <SleepStageBar :analyses="selectedAnalyses" />
        </div>
        <ScoreCards :analyses="selectedAnalyses" />
        <VitalCards :analyses="selectedAnalyses" />
        <SleepMetricsCards :analyses="selectedAnalyses" />
        <div class="chart-panel">
          <h3>Energy Bank</h3>
          <EnergyBankChart :analyses="selectedAnalyses" />
        </div>
        <VitalsGrid :analyses="selectedAnalyses" />
        <div v-if="lowCoverage" class="coverage-banner">
          <span class="coverage-icon">&#9888;</span>
          <span>Limited sensor data ({{ coveragePct }}% coverage). Charts show only the available data. Scores are adjusted for uncertainty. Ensure Sensor Logger background recording is enabled for better results.</span>
        </div>
        <div class="charts-grid">
          <div class="chart-panel">
            <h3>Heart Rate</h3>
            <HeartRateChart :items="selectedItems" />
          </div>
          <div class="chart-panel">
            <h3>Movement</h3>
            <MovementChart :items="selectedItems" />
          </div>
          <div class="chart-panel">
            <h3>Respiratory Rate</h3>
            <RespiratoryChart :items="selectedItems" />
          </div>
          <div class="chart-panel">
            <h3>Noise Level</h3>
            <NoiseChart :items="selectedItems" />
          </div>
        </div>
        <div class="charts-grid single-col">
          <div class="chart-panel">
            <h3>Stage Distribution</h3>
            <StageDonutChart :analyses="selectedAnalyses" />
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <h2>Select a sleep period</h2>
        <p>Pick a time range above, then click a detected sleep period to view its analysis.</p>
      </div>
    </div>
    <footer class="app-footer">Made by Gretch. {{ new Date().getFullYear() }}</footer>
  </div>
</template>

<script setup>
import { ref, computed, watch, provide } from 'vue'
import AppHeader from './components/AppHeader.vue'
import TimeBar from './components/TimeBar.vue'
import PeriodsList from './components/PeriodsList.vue'
import ScoreCards from './components/ScoreCards.vue'
import VitalCards from './components/VitalCards.vue'
import SleepMetricsCards from './components/SleepMetricsCards.vue'
import DailySummary from './components/DailySummary.vue'
import SleepStageBar from './components/SleepStageBar.vue'
import VitalsGrid from './components/VitalsGrid.vue'
import EnergyBankChart from './components/charts/EnergyBankChart.vue'
import HeartRateChart from './components/charts/HeartRateChart.vue'
import MovementChart from './components/charts/MovementChart.vue'
import RespiratoryChart from './components/charts/RespiratoryChart.vue'
import SleepArchChart from './components/charts/SleepArchChart.vue'
import StageDonutChart from './components/charts/StageDonutChart.vue'
import NoiseChart from './components/charts/NoiseChart.vue'
import { useDateRange } from './composables/useDateRange'
import { useApi } from './composables/useApi'
import { useSleepData } from './composables/useSleepData'

const { rangeStart, rangeEnd, setRange, setPreset, rangeLabel } = useDateRange()
const { periods, selectedIds, loadedAnalyses, reloadPeriods, togglePeriod, toggleSelectAll, selectedItems, selectedAnalyses, analyzePeriod } = useSleepData(rangeStart, rangeEnd)

// Provide composables to child components
provide('dateRange', { rangeStart, rangeEnd, setRange, setPreset, rangeLabel })
provide('sleepData', { periods, selectedIds, loadedAnalyses, reloadPeriods, togglePeriod, toggleSelectAll, selectedItems, selectedAnalyses, analyzePeriod })

// Data coverage warning
const lowCoverage = computed(() => {
  const aa = selectedAnalyses.value || []
  if (!aa.length) return false
  return aa.some(a => (a.data_coverage ?? 1) < 0.5)
})
const coveragePct = computed(() => {
  const aa = selectedAnalyses.value || []
  if (!aa.length) return 100
  const avg = aa.reduce((s, a) => s + (a.data_coverage ?? 1), 0) / aa.length
  return Math.round(avg * 100)
})
</script>

<style scoped>
.app-footer {
  text-align: center;
  padding: 24px 0;
  margin-top: auto;
  font-size: 13px;
  color: var(--text-dim);
  letter-spacing: 0.5px;
}

.app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background-color: var(--bg);
  color: var(--text);
}

.container {
  flex: 1;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  padding: 2rem;
}

#dashboard-content {
  animation: fadeIn 0.3s ease-in-out;
}

.charts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
}

.charts-grid.single-col {
  grid-template-columns: 1fr;
}

.chart-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}

.chart-panel.full-width {
  grid-column: 1 / -1;
}

.arch-panel {
  margin-bottom: 16px;
  padding-bottom: 8px;
}

.chart-panel h3 {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-dim);
  margin-bottom: 16px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  text-align: center;
  color: var(--text-dim);
}

.empty-state h2 {
  font-size: 1.5rem;
  margin-bottom: 0.5rem;
  color: var(--text);
}

.empty-state p {
  font-size: 1rem;
  max-width: 400px;
}

.coverage-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: rgba(255, 180, 0, 0.12);
  border: 1px solid rgba(255, 180, 0, 0.3);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 24px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-dim);
}

.coverage-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 1px;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
