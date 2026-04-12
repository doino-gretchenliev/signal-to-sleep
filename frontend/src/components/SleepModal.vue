<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-dialog">
      <h3 class="modal-title">{{ isEdit ? 'Edit Sleep Period' : 'Add Sleep Period' }}</h3>

      <div class="field">
        <label>Type</label>
        <div class="type-toggle">
          <button
            :class="{ active: form.sleep_type === 'nap' }"
            @click="form.sleep_type = 'nap'"
          >Nap</button>
          <button
            :class="{ active: form.sleep_type === 'night' }"
            @click="form.sleep_type = 'night'"
          >Night</button>
        </div>
      </div>

      <div class="field">
        <label>Start</label>
        <input type="datetime-local" v-model="form.startLocal" class="dt-input" />
      </div>

      <div class="field">
        <label>End</label>
        <input type="datetime-local" v-model="form.endLocal" class="dt-input" />
      </div>

      <div class="duration-preview" v-if="durationText">
        {{ durationText }}
      </div>

      <div class="error" v-if="error">{{ error }}</div>

      <div class="modal-actions">
        <button class="btn-cancel" @click="$emit('close')">Cancel</button>
        <button class="btn-save" :disabled="saving || !isValid" @click="handleSave">
          {{ saving ? 'Saving…' : (isEdit ? 'Update' : 'Create') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { createManualPeriod, updatePeriod } from '../composables/useApi'

const props = defineProps({
  /** null for create, period object for edit */
  period: { type: Object, default: null },
})
const emit = defineEmits(['close', 'saved'])

const isEdit = computed(() => !!props.period)

/** Format a Date to local datetime-local string */
function toLocalDT(d) {
  const dt = new Date(d)
  const off = dt.getTimezoneOffset()
  const local = new Date(dt.getTime() - off * 60000)
  return local.toISOString().slice(0, 16)
}

/** Parse a datetime-local string back to UTC ISO */
function localDTtoUTC(str) {
  return new Date(str).toISOString()
}

const now = new Date()
const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000)

const form = reactive({
  sleep_type: props.period?.sleep_type || 'nap',
  startLocal: props.period ? toLocalDT(props.period.started_at) : toLocalDT(oneHourAgo),
  endLocal: props.period ? toLocalDT(props.period.ended_at) : toLocalDT(now),
})

const saving = ref(false)
const error = ref('')

const durationMs = computed(() => {
  const s = new Date(form.startLocal).getTime()
  const e = new Date(form.endLocal).getTime()
  return e - s
})

const isValid = computed(() => durationMs.value > 0)

const durationText = computed(() => {
  const ms = durationMs.value
  if (ms <= 0) return 'End must be after start'
  const min = Math.round(ms / 60000)
  const h = Math.floor(min / 60)
  const m = min % 60
  return h > 0 ? `Duration: ${h}h ${m}m` : `Duration: ${m}m`
})

async function handleSave() {
  error.value = ''
  saving.value = true
  try {
    const started_at = localDTtoUTC(form.startLocal)
    const ended_at = localDTtoUTC(form.endLocal)

    if (isEdit.value) {
      await updatePeriod(props.period.period_id, {
        started_at,
        ended_at,
        sleep_type: form.sleep_type,
      })
    } else {
      await createManualPeriod({
        started_at,
        ended_at,
        sleep_type: form.sleep_type,
      })
    }
    emit('saved')
    emit('close')
  } catch (e) {
    error.value = e.message || 'Failed to save'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal-dialog {
  background: #161a2e;
  border: 1px solid rgba(124, 110, 240, 0.15);
  border-radius: 16px;
  padding: 28px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(124, 110, 240, 0.06);
}

.modal-title {
  margin: 0 0 20px;
  font-size: 18px;
  font-weight: 700;
  color: #f3f4f6;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-dim, #9ca3af);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}

.type-toggle {
  display: flex;
  gap: 6px;
  background: #131627;
  border-radius: 10px;
  padding: 4px;
}
.type-toggle button {
  flex: 1;
  padding: 8px 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--text-dim, #9ca3af);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}
.type-toggle button.active {
  background: rgba(124, 110, 240, 0.18);
  border-color: rgba(124, 110, 240, 0.35);
  color: var(--accent, #7c6ef0);
  box-shadow: 0 2px 8px rgba(124, 110, 240, 0.1);
}
.type-toggle button:not(.active):hover {
  background: rgba(255, 255, 255, 0.04);
  color: #d1d5db;
}

.dt-input {
  width: 100%;
  padding: 10px 14px;
  background: #131627;
  border: 1px solid rgba(124, 110, 240, 0.2);
  border-radius: 8px;
  color: #f3f4f6;
  font-size: 15px;
  font-family: 'SF Mono', 'Fira Code', 'Menlo', monospace;
  letter-spacing: 0.5px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-sizing: border-box;
  -webkit-appearance: none;
  appearance: none;
  color-scheme: dark;
}
.dt-input:focus {
  border-color: var(--accent, #7c6ef0);
  box-shadow: 0 0 0 3px rgba(124, 110, 240, 0.12);
}
.dt-input:hover:not(:focus) {
  border-color: rgba(124, 110, 240, 0.35);
}
/* Style the calendar/clock icons for dark theme */
.dt-input::-webkit-calendar-picker-indicator {
  filter: invert(0.8) sepia(0.3) saturate(5) hue-rotate(210deg);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  transition: background 0.15s;
}
.dt-input::-webkit-calendar-picker-indicator:hover {
  background: rgba(124, 110, 240, 0.2);
}
/* Firefox */
.dt-input::-moz-calendar-picker-indicator {
  filter: invert(0.8);
}

.duration-preview {
  font-size: 13px;
  color: var(--text-dim, #9ca3af);
  margin-bottom: 16px;
  padding: 8px 12px;
  background: rgba(124, 110, 240, 0.08);
  border-radius: 6px;
  text-align: center;
}

.error {
  color: #fca5a5;
  font-size: 13px;
  margin-bottom: 12px;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 4px;
}

.btn-cancel {
  padding: 8px 18px;
  background: transparent;
  border: 1px solid rgba(75, 85, 99, 0.5);
  border-radius: 8px;
  color: #d1d5db;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-cancel:hover {
  border-color: rgba(75, 85, 99, 0.8);
  background: rgba(31, 41, 55, 0.5);
}

.btn-save {
  padding: 8px 22px;
  background: rgba(124, 110, 240, 0.2);
  border: 1px solid rgba(124, 110, 240, 0.5);
  border-radius: 8px;
  color: var(--accent, #7c6ef0);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-save:hover:not(:disabled) {
  background: rgba(124, 110, 240, 0.35);
}
.btn-save:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
