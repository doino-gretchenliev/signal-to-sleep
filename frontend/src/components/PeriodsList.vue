<template>
  <div class="periods-wrap">
    <div class="periods-header">
      <span class="title">Sleep Periods</span>
      <span class="count" v-if="periodList.length">{{ periodList.length }} detected</span>
      <button class="add-btn" @click="showAddModal = true">
        <span class="add-icon">+</span> Add Sleep
      </button>
      <button class="toggle-btn" @click="handleToggleAll" v-if="periodList.length">
        {{ allSelected ? 'Deselect All' : 'Select All' }}
      </button>
      <button
        class="delete-btn"
        v-if="selectedCount > 0"
        @click="showConfirm = true"
      >
        Delete ({{ selectedCount }})
      </button>
    </div>

    <div v-if="periodList.length === 0" class="empty">
      No sleep periods detected for this range.
    </div>

    <div v-else class="periods-scroll">
      <div
        v-for="period in periodList"
        :key="period.period_id"
        class="period-chip"
        :class="{
          selected: isSelected(period.period_id),
          unanalyzed: !isPeriodAnalyzed(period.period_id),
          manual: period.source === 'manual',
        }"
        @click="handleClick(period)"
      >
        <div class="chip-top">
          <span class="chip-type" :class="period.sleep_type">
            {{ period.sleep_type === 'night' ? 'Night' : 'Nap' }}
          </span>
          <span class="chip-source" v-if="period.source === 'manual'">M</span>
          <span class="chip-check" v-if="isSelected(period.period_id)">&#10003;</span>
        </div>
        <div class="chip-date">{{ formatDate(period.started_at) }}</div>
        <div class="chip-time">{{ formatTime(period.started_at) }} — {{ period.ended_at ? formatTime(period.ended_at) : 'now' }}</div>
        <div class="chip-meta">
          <span class="chip-dur">{{ fmtDuration(period.duration_min) }}</span>
          <span class="chip-conf" v-if="period.confidence">{{ Math.round(period.confidence * 100) }}%</span>
          <button class="chip-edit" @click.stop="editingPeriod = period" title="Edit times">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </button>
        </div>
        <button
          v-if="!isPeriodAnalyzed(period.period_id) && analyzing !== period.period_id"
          class="chip-analyze"
          @click.stop="handleAnalyze(period.period_id)"
        >Analyze</button>
        <div v-else-if="analyzing === period.period_id" class="chip-analyzing">
          <span class="analyzing-spinner"></span>
          Analyzing…
        </div>
        <div v-else class="chip-done-wrap" @click.stop="handleAnalyze(period.period_id)">
          <span class="chip-done">Analyzed</span>
          <span class="chip-reanalyze">Re-analyze</span>
        </div>
      </div>
    </div>

    <!-- Add Sleep modal -->
    <SleepModal
      v-if="showAddModal"
      @close="showAddModal = false"
      @saved="handleModalSaved"
    />

    <!-- Edit Sleep modal -->
    <SleepModal
      v-if="editingPeriod"
      :period="editingPeriod"
      @close="editingPeriod = null"
      @saved="handleModalSaved"
    />

    <!-- Delete confirmation overlay -->
    <div v-if="showConfirm" class="confirm-overlay" @click.self="showConfirm = false">
      <div class="confirm-dialog">
        <p class="confirm-title">Delete {{ selectedCount }} sleep period{{ selectedCount > 1 ? 's' : '' }}?</p>
        <p class="confirm-desc">This will permanently remove the selected period{{ selectedCount > 1 ? 's' : '' }} and any associated analysis data.</p>
        <div class="confirm-actions">
          <button class="confirm-cancel" @click="showConfirm = false">Cancel</button>
          <button class="confirm-delete" :disabled="deleting" @click="handleDelete">
            {{ deleting ? 'Deleting…' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, inject } from 'vue'
import { fmtDuration } from '../utils/formatting'
import { deletePeriods } from '../composables/useApi'
import SleepModal from './SleepModal.vue'

const sleepData = inject('sleepData', {})
const { periods, selectedIds, loadedAnalyses, reloadPeriods, togglePeriod, toggleSelectAll, analyzePeriod, analyzing: composableAnalyzing } = sleepData

const periodList = computed(() => periods?.value || [])
const showConfirm = ref(false)
const showAddModal = ref(false)
const editingPeriod = ref(null)
const deleting = ref(false)
const analyzing = computed(() => composableAnalyzing?.value || null)

const handleModalSaved = async () => {
  if (reloadPeriods) await reloadPeriods()
}

const isSelected = (pid) => {
  return selectedIds?.value?.has(pid) || false
}

const selectedCount = computed(() => selectedIds?.value?.size || 0)

const allSelected = computed(() => {
  const list = periodList.value
  if (!list.length || !selectedIds?.value) return false
  return list.every(p => selectedIds.value.has(p.period_id))
})

const formatDate = (date) => {
  const d = date instanceof Date ? date : new Date(date)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

const formatTime = (date) => {
  const d = date instanceof Date ? date : new Date(date)
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
}

const isPeriodAnalyzed = (pid) => {
  const p = periodList.value.find(x => x.period_id === pid)
  return p?.has_analysis || (loadedAnalyses?.value?.has(pid))
}

const handleClick = (period) => {
  togglePeriod(period.period_id)
}

const handleToggleAll = () => toggleSelectAll()
const handleAnalyze = (pid) => analyzePeriod(pid)

const handleDelete = async () => {
  deleting.value = true
  try {
    const ids = [...selectedIds.value]
    await deletePeriods(ids)
    selectedIds.value.clear()
    showConfirm.value = false
    if (reloadPeriods) await reloadPeriods()
  } catch (e) {
    console.error('Failed to delete periods:', e)
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.periods-wrap {
  margin-bottom: 1.5rem;
  position: relative;
}

.periods-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.count {
  font-size: 12px;
  color: var(--text-dim);
}

.add-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 14px;
  background: rgba(124, 110, 240, 0.15);
  border: 1px solid rgba(124, 110, 240, 0.35);
  border-radius: 6px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.add-btn:hover { background: rgba(124, 110, 240, 0.25); border-color: var(--accent); }
.add-icon { font-size: 15px; font-weight: 400; line-height: 1; }

.toggle-btn {
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.toggle-btn:hover { border-color: var(--accent); background: var(--surface); }

.delete-btn {
  padding: 4px 12px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  border-radius: 6px;
  color: #fca5a5;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.delete-btn:hover {
  background: rgba(239, 68, 68, 0.25);
  border-color: rgba(239, 68, 68, 0.6);
}

.empty {
  padding: 2rem;
  text-align: center;
  color: var(--text-dim);
  font-size: 14px;
}

.periods-scroll {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding: 4px 0 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.periods-scroll::-webkit-scrollbar { height: 4px; }
.periods-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.period-chip {
  flex-shrink: 0;
  width: 160px;
  padding: 12px;
  background: var(--surface);
  border: 2px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.period-chip:hover {
  border-color: var(--accent);
  background: var(--surface2);
}
.period-chip.selected {
  border-color: var(--accent);
  background: rgba(124, 110, 240, 0.08);
  box-shadow: 0 0 12px rgba(124, 110, 240, 0.15);
}
.period-chip.unanalyzed {
  opacity: 0.65;
}

.chip-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.chip-type {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.chip-type.night { background: rgba(147,51,234,0.2); color: #d8b4fe; }
.chip-type.nap { background: rgba(234,179,8,0.2); color: #fde047; }

.chip-source {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
  background: rgba(139, 92, 246, 0.2);
  color: #c4b5fd;
  letter-spacing: 0.3px;
}

.chip-check {
  color: var(--accent);
  font-size: 14px;
  font-weight: 700;
}

.chip-date {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}

.chip-time {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.chip-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  margin-bottom: 6px;
}
.chip-dur { color: var(--text); font-weight: 500; }
.chip-conf { color: var(--accent); }
.chip-edit {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  margin-left: auto;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--text-dim);
  cursor: pointer;
  opacity: 0;
  transition: all 0.15s;
}
.period-chip:hover .chip-edit { opacity: 0.6; }
.chip-edit:hover { opacity: 1 !important; border-color: var(--accent); color: var(--accent); }

.chip-analyze {
  width: 100%;
  padding: 4px 0;
  background: rgba(124, 110, 240, 0.15);
  border: 1px solid rgba(124, 110, 240, 0.3);
  border-radius: 6px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.chip-analyze:hover { background: rgba(124, 110, 240, 0.25); }

.chip-done-wrap {
  position: relative;
  cursor: pointer;
  border-radius: 6px;
  padding: 4px 0;
  transition: all 0.2s;
}
.chip-done-wrap:hover {
  background: rgba(124, 110, 240, 0.15);
}
.chip-done-wrap:hover .chip-done {
  opacity: 0;
}
.chip-done-wrap:hover .chip-reanalyze {
  opacity: 1;
}

.chip-analyzing {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  animation: pulse 1.5s ease-in-out infinite;
}

.analyzing-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(124, 110, 240, 0.2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.chip-done {
  display: block;
  text-align: center;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: #86efac;
  letter-spacing: 0.5px;
  transition: opacity 0.15s;
}

.chip-reanalyze {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  opacity: 0;
  transition: opacity 0.15s;
}

/* ── Confirm overlay ─────────────────────────── */
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.confirm-dialog {
  background: #1e2340;
  border: 1px solid rgba(75, 85, 99, 0.6);
  border-radius: 12px;
  padding: 24px;
  max-width: 380px;
  width: 90%;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.confirm-title {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 700;
  color: #f3f4f6;
}

.confirm-desc {
  margin: 0 0 20px;
  font-size: 13px;
  color: #9ca3af;
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.confirm-cancel {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid rgba(75, 85, 99, 0.5);
  border-radius: 8px;
  color: #d1d5db;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.confirm-cancel:hover {
  border-color: rgba(75, 85, 99, 0.8);
  background: rgba(31, 41, 55, 0.5);
}

.confirm-delete {
  padding: 8px 16px;
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.5);
  border-radius: 8px;
  color: #fca5a5;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.confirm-delete:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.35);
  color: #fecaca;
}
.confirm-delete:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
