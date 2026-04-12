/**
 * useApi - Composable for API interactions
 */

/**
 * Fetch health status
 * @returns {Promise<Object>} Health data
 */
export async function fetchHealth() {
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`Health fetch failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch MQTT status
 * @returns {Promise<Object>} MQTT status data
 */
export async function fetchMqttStatus() {
  const response = await fetch('/api/mqtt/status')
  if (!response.ok) {
    throw new Error(`MQTT status fetch failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch sleep periods for a date range
 * @param {Date|string} start - Start date
 * @param {Date|string} end - End date
 * @returns {Promise<Array>} Array of sleep periods
 */
export async function fetchPeriods(start, end) {
  const startStr = start instanceof Date ? start.toISOString() : start
  const endStr = end instanceof Date ? end.toISOString() : end

  const params = new URLSearchParams({
    start: startStr,
    end: endStr,
  })

  const response = await fetch(`/api/sleep-periods?${params}`)
  if (!response.ok) {
    throw new Error(`Periods fetch failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch analysis for a specific sleep period
 * @param {string} periodId - The period ID
 * @returns {Promise<Object>} Analysis data
 */
export async function fetchAnalysis(periodId) {
  const response = await fetch(`/api/analysis/${periodId}`)
  if (!response.ok) {
    throw new Error(`Analysis fetch failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Stream analysis events for a sleep period using EventSource
 * @param {string} periodId - The period ID
 * @param {Function} onProgress - Callback for progress updates
 * @param {Function} onComplete - Callback when analysis completes
 * @param {Function} onError - Callback for errors
 * @returns {EventSource} The EventSource object (caller should close it)
 */
export function analyzeStream(periodId, onProgress, onComplete, onError) {
  const eventSource = new EventSource(`/api/analyze/${periodId}/stream`)

  eventSource.addEventListener('progress', (event) => {
    try {
      const data = JSON.parse(event.data)
      onProgress(data)
    } catch (e) {
      console.error('Failed to parse progress event:', e)
    }
  })

  eventSource.addEventListener('complete', (event) => {
    try {
      const data = JSON.parse(event.data)
      onComplete(data)
      eventSource.close()
    } catch (e) {
      console.error('Failed to parse complete event:', e)
      eventSource.close()
    }
  })

  eventSource.addEventListener('error', (event) => {
    console.error('EventSource error:', event)
    if (onError) {
      onError(event)
    }
    eventSource.close()
  })

  return eventSource
}

/**
 * Start a manual sleep session
 * @returns {Promise<Object>} { status, period_id } or { status, message }
 */
export async function startSleep() {
  const response = await fetch('/api/sleep/start', { method: 'POST' })
  if (!response.ok) {
    throw new Error(`Sleep start failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Stop the current sleep session
 * @returns {Promise<Object>} { status, period_id, duration_min } or { status, message }
 */
export async function stopSleep() {
  const response = await fetch('/api/sleep/stop', { method: 'POST' })
  if (!response.ok) {
    throw new Error(`Sleep stop failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Delete one or more sleep periods
 * @param {string[]} periodIds - Array of period IDs to delete
 * @returns {Promise<Object>} { status, deleted, count }
 */
export async function deletePeriods(periodIds) {
  const response = await fetch('/api/sleep-periods', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(periodIds),
  })
  if (!response.ok) {
    throw new Error(`Delete failed: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Create a manual sleep period with explicit start/end
 */
export async function createManualPeriod({ started_at, ended_at, sleep_type }) {
  const response = await fetch('/api/sleep-periods/manual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ started_at, ended_at, sleep_type }),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || response.statusText)
  }
  return response.json()
}

/**
 * Update an existing sleep period's start/end times or type
 */
export async function updatePeriod(periodId, updates) {
  const response = await fetch(`/api/sleep-periods/${periodId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.detail || response.statusText)
  }
  return response.json()
}

export const useApi = {
  fetchHealth,
  fetchMqttStatus,
  fetchPeriods,
  fetchAnalysis,
  analyzeStream,
  startSleep,
  stopSleep,
  deletePeriods,
  createManualPeriod,
  updatePeriod,
}
