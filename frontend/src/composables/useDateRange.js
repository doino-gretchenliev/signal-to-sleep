import { ref, computed } from 'vue'

/**
 * useDateRange - Composable for managing date range state
 */
export function useDateRange() {
  const rangeStart = ref(new Date(new Date().getTime() - 7 * 24 * 60 * 60 * 1000)) // 7 days ago
  const rangeEnd = ref(new Date())

  /**
   * Set a specific date range
   * @param {Date} start
   * @param {Date} end
   */
  function setRange(start, end) {
    rangeStart.value = new Date(start)
    rangeEnd.value = new Date(end)
  }

  /**
   * Set range to N days back from now
   * @param {number} days - Number of days back
   */
  function setPreset(days) {
    rangeEnd.value = new Date()
    rangeStart.value = new Date(new Date().getTime() - days * 24 * 60 * 60 * 1000)
  }

  /**
   * Computed label for the date range (e.g., "Apr 3 — Apr 10")
   */
  const rangeLabel = computed(() => {
    const formatter = new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
    })
    const startLabel = formatter.format(rangeStart.value)
    const endLabel = formatter.format(rangeEnd.value)
    return `${startLabel} — ${endLabel}`
  })

  return {
    rangeStart,
    rangeEnd,
    setRange,
    setPreset,
    rangeLabel,
  }
}
