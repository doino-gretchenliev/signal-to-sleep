import { ref, computed, watch, triggerRef } from 'vue'
import { fetchPeriods, fetchAnalysis } from './useApi'
import { useWebSocket } from './useWebSocket'

export function useSleepData(rangeStart, rangeEnd) {
  const periods = ref([])
  const selectedIds = ref(new Set())
  const loadedAnalyses = ref(new Map())
  const analyzing = ref(null) // period_id being analyzed, or null
  // ── Shared reload function ─────────────────────
  async function reloadPeriods() {
    if (!rangeStart.value || !rangeEnd.value) return
    try {
      // Always extend rangeEnd to "now" so freshly created periods aren't excluded
      const end = new Date(Math.max(rangeEnd.value.getTime(), Date.now()))
      const data = await fetchPeriods(rangeStart.value, end)
      periods.value = Array.isArray(data) ? data : []
      // Prune selected IDs that are no longer in range
      const validIds = new Set(periods.value.map(p => p.period_id))
      for (const id of selectedIds.value) {
        if (!validIds.has(id)) selectedIds.value.delete(id)
      }
      triggerRef(selectedIds)
    } catch (e) {
      console.error('Failed to fetch periods:', e)
    }
  }

  // ── WebSocket: real-time updates from backend ──
  useWebSocket(async (event) => {
    if (event.type === 'health_update') return // handled by useWebSocket internally

    console.log('[WS] event:', event.type)

    if (event.type === 'periods_detected' || event.type === 'data_refresh') {
      await reloadPeriods()
      await autoSelectAnalyzed()
    }

    if (event.type === 'analysis_complete') {
      const pid = event.period_id
      try {
        const analysis = await fetchAnalysis(pid)
        loadedAnalyses.value.set(pid, analysis)
        triggerRef(loadedAnalyses)
      } catch (e) {
        console.warn(`[WS] Failed to fetch analysis for ${pid}:`, e)
      }
      const p = periods.value.find(p => p.period_id === pid)
      if (p) p.has_analysis = true
      // Auto-select the newly analyzed period
      selectedIds.value.add(pid)
      triggerRef(selectedIds)
      // Clear analyzing spinner + timeout
      if (analyzing.value === pid) {
        analyzing.value = null
        if (analyzeTimeout) { clearTimeout(analyzeTimeout); analyzeTimeout = null }
      }
      await reloadPeriods()
    }
  })

  // Watch date range → reload periods
  watch(
    [rangeStart, rangeEnd],
    async () => {
      await reloadPeriods()
      // Auto-select + load all analyzed periods on first load
      if (selectedIds.value.size === 0) {
        await autoSelectAnalyzed()
      }
    },
    { immediate: true }
  )

  async function autoSelectAnalyzed() {
    const analyzed = periods.value.filter(p => p.has_analysis)
    const toFetch = analyzed.filter(p => !loadedAnalyses.value.has(p.period_id))
    // Fetch analyses in parallel
    await Promise.all(toFetch.map(async p => {
      try {
        const data = await fetchAnalysis(p.period_id)
        loadedAnalyses.value.set(p.period_id, data)
      } catch (e) {
        console.error(`Failed to fetch analysis for ${p.period_id}:`, e)
      }
    }))
    triggerRef(loadedAnalyses)
    // Auto-select only the most recent analyzed period
    if (analyzed.length > 0) {
      selectedIds.value.add(analyzed[0].period_id)
    }
    triggerRef(selectedIds)
  }

  function togglePeriod(id) {
    if (selectedIds.value.has(id)) {
      selectedIds.value.delete(id)
    } else {
      selectedIds.value.add(id)
      // Fetch analysis if available and not cached
      const period = periods.value.find(p => p.period_id === id)
      if (period?.has_analysis && !loadedAnalyses.value.has(id)) {
        fetchAnalysis(id).then(data => {
          loadedAnalyses.value.set(id, data)
          triggerRef(loadedAnalyses)
        })
      }
    }
    triggerRef(selectedIds)
  }

  function toggleSelectAll() {
    const allIds = periods.value.map(p => p.period_id)
    const allSelected = allIds.length > 0 && allIds.every(id => selectedIds.value.has(id))
    if (allSelected) {
      selectedIds.value.clear()
    } else {
      allIds.forEach(id => selectedIds.value.add(id))
      // Fetch any uncached analyses for analyzed periods
      periods.value
        .filter(p => p.has_analysis && !loadedAnalyses.value.has(p.period_id))
        .forEach(p => {
          fetchAnalysis(p.period_id).then(data => {
            loadedAnalyses.value.set(p.period_id, data)
            triggerRef(loadedAnalyses)
          })
        })
    }
    triggerRef(selectedIds)
  }

  let analyzeTimeout = null

  async function analyzePeriod(id) {
    if (analyzing.value === id) return // already analyzing this one
    analyzing.value = id

    // Safety timeout: if no WS completion after 5 min, clear the spinner
    if (analyzeTimeout) clearTimeout(analyzeTimeout)
    analyzeTimeout = setTimeout(() => {
      if (analyzing.value === id) {
        console.warn(`[Analyze] Timeout waiting for ${id}, clearing spinner`)
        analyzing.value = null
      }
    }, 5 * 60 * 1000)

    try {
      // Fire-and-forget: POST triggers background analysis,
      // completion comes via WebSocket 'analysis_complete' event
      const res = await fetch(`/api/analyze/${id}`, { method: 'POST' })
      if (!res.ok) {
        console.error(`[Analyze] HTTP ${res.status} for ${id}`)
        // Don't clear analyzing — the server might be restarting and will pick up later
        // The timeout above will clear it eventually
        return
      }
      const data = await res.json()
      console.log(`[Analyze] ${data.status} for ${id}`)
    } catch (e) {
      console.error('Analysis request failed:', e)
      // Network error — server might be down. Keep spinner, timeout will clear it.
    }
  }

  const selectedItems = computed(() => {
    const items = []
    for (const p of periods.value) {
      if (selectedIds.value.has(p.period_id) && loadedAnalyses.value.has(p.period_id)) {
        items.push({ period: p, analysis: loadedAnalyses.value.get(p.period_id) })
      }
    }
    return items
  })

  const selectedAnalyses = computed(() => selectedItems.value.map(i => i.analysis))

  return {
    periods, selectedIds, loadedAnalyses, analyzing,
    reloadPeriods, togglePeriod, toggleSelectAll, analyzePeriod,
    selectedItems, selectedAnalyses,
  }
}
