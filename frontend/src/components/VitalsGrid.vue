<template>
  <div class="vitals-grid">
    <!-- Avg Heart Rate -->
    <div class="vital-card">
      <div class="vital-value">{{ avgHeartRate }}</div>
      <div class="vital-label">Avg Heart Rate</div>
      <div class="vital-unit">bpm</div>
    </div>

    <!-- Min Heart Rate -->
    <div class="vital-card">
      <div class="vital-value">{{ minHeartRate }}</div>
      <div class="vital-label">Min Heart Rate</div>
      <div class="vital-unit">bpm</div>
    </div>

    <!-- Max Heart Rate -->
    <div class="vital-card">
      <div class="vital-value">{{ maxHeartRate }}</div>
      <div class="vital-label">Max Heart Rate</div>
      <div class="vital-unit">bpm</div>
    </div>

    <!-- Respiratory Rate -->
    <div class="vital-card">
      <div class="vital-value">{{ respiratoryRate }}</div>
      <div class="vital-label">Respiratory Rate</div>
      <div class="vital-unit">breaths/min</div>
    </div>

    <!-- HRV RMSSD -->
    <div class="vital-card">
      <div class="vital-value">{{ hrvRmssd }}</div>
      <div class="vital-label">HRV RMSSD</div>
      <div class="vital-unit">ms</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { avg } from '../utils/formatting';

const props = defineProps({
  analyses: Array
});

/**
 * Calculate average heart rate across all analyses
 */
const avgHeartRate = computed(() => {
  if (props.analyses.length === 0) return '--';
  const rates = props.analyses.map(a => a.avg_heart_rate || 0).filter(r => r > 0);
  return rates.length === 0 ? '--' : Math.round(avg(rates));
});

/**
 * Calculate minimum heart rate across all analyses
 */
const minHeartRate = computed(() => {
  if (props.analyses.length === 0) return '--';
  const rates = props.analyses.map(a => a.min_heart_rate || 0).filter(r => r > 0);
  return rates.length === 0 ? '--' : Math.round(Math.min(...rates));
});

/**
 * Calculate maximum heart rate across all analyses
 */
const maxHeartRate = computed(() => {
  if (props.analyses.length === 0) return '--';
  const rates = props.analyses.map(a => a.max_heart_rate || 0).filter(r => r > 0);
  return rates.length === 0 ? '--' : Math.round(Math.max(...rates));
});

/**
 * Calculate average respiratory rate
 */
const respiratoryRate = computed(() => {
  if (props.analyses.length === 0) return '--';
  const rates = props.analyses.map(a => a.avg_respiratory_rate || 0).filter(r => r > 0);
  return rates.length === 0 ? '--' : Math.round(avg(rates) * 10) / 10; // 1 decimal place
});

/**
 * Calculate average HRV RMSSD
 */
const hrvRmssd = computed(() => {
  if (props.analyses.length === 0) return '--';
  const values = props.analyses.map(a => a.avg_hrv || 0).filter(v => v > 0);
  return values.length === 0 ? '--' : Math.round(avg(values));
});
</script>

<style scoped>
.vitals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  padding: 2rem;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  border-radius: 0.75rem;
  border: 1px solid rgba(59, 130, 246, 0.1);
}

.vital-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem 1.5rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 0.75rem;
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}

.vital-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(59, 130, 246, 0.3), transparent);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.vital-card:hover {
  border-color: rgba(59, 130, 246, 0.3);
  background: rgba(30, 41, 59, 0.5);
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(59, 130, 246, 0.1);
}

.vital-card:hover::before {
  opacity: 1;
}

.vital-value {
  font-size: 2.5rem;
  font-weight: 700;
  color: #e5e7eb;
  line-height: 1;
  margin-bottom: 0.75rem;
}

.vital-label {
  color: #d1d5db;
  font-size: 0.95rem;
  font-weight: 500;
  text-align: center;
  margin-bottom: 0.375rem;
}

.vital-unit {
  color: #9ca3af;
  font-size: 0.875rem;
  font-weight: 400;
}

@media (max-width: 1024px) {
  .vitals-grid {
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    padding: 1.5rem;
  }

  .vital-card {
    padding: 1.5rem 1rem;
  }

  .vital-value {
    font-size: 2rem;
  }

  .vital-label {
    font-size: 0.875rem;
  }
}

@media (max-width: 768px) {
  .vitals-grid {
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  }

  .vital-value {
    font-size: 1.75rem;
  }

  .vital-label {
    font-size: 0.8rem;
  }

  .vital-unit {
    font-size: 0.75rem;
  }
}

@media (max-width: 640px) {
  .vitals-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
    padding: 1rem;
  }

  .vital-card {
    padding: 1rem 0.75rem;
  }

  .vital-value {
    font-size: 1.5rem;
    margin-bottom: 0.5rem;
  }

  .vital-label {
    font-size: 0.75rem;
    margin-bottom: 0.25rem;
  }

  .vital-unit {
    font-size: 0.65rem;
  }
}
</style>
