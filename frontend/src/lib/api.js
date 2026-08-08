/**
 * Talking to monitorctl.
 *
 * Every write goes to the monitor over a slow serial bus and is verified before
 * the service answers, so a switch takes around two seconds. Nothing here tries
 * to hide that — the UI shows the work in progress instead of pretending it was
 * instant and then correcting itself.
 */

// A verified switch takes ~2 s; a request that queues behind a background sweep
// can take longer. Well above that, but still short enough to surface a hang.
const TIMEOUT_MS = 20000

async function request(path, options = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      const error = new Error(body?.message || `HTTP ${response.status}`)
      error.code = body?.error || String(response.status)
      error.status = response.status
      throw error
    }
    return body
  } catch (err) {
    if (err.name === 'AbortError') {
      const error = new Error('The monitor did not answer in time.')
      error.code = 'timeout'
      throw error
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  display: () => request('/api/display'),
  features: () => request('/api/features'),
  state: () => request('/api/state'),
  setFeature: (name, value) =>
    request(`/api/feature/${encodeURIComponent(name)}`, {
      method: 'POST',
      body: JSON.stringify({ value }),
    }),
  setInput: (target) =>
    request(`/api/input/${encodeURIComponent(target)}`, { method: 'POST' }),
  toggle: () => request('/api/toggle', { method: 'POST' }),
}

/**
 * Subscribe to server-sent state changes.
 *
 * EventSource reconnects on its own, but only for clean disconnects. A Pi that
 * reboots, or Wi-Fi that drops, produces errors it will not recover from, so
 * this reconnects explicitly with a backoff and reports connection state.
 */
export function subscribe({ onState, onStatus }) {
  let source = null
  let closed = false
  let attempt = 0
  let retryTimer = null

  function connect() {
    if (closed) return
    source = new EventSource('/api/events')

    source.onopen = () => {
      attempt = 0
      onStatus?.('live')
    }

    source.addEventListener('state', (event) => {
      try {
        onState?.(JSON.parse(event.data))
      } catch {
        // A malformed frame is not worth tearing the connection down for.
      }
    })

    source.onerror = () => {
      if (closed) return
      onStatus?.('reconnecting')
      source.close()
      // 1s, 2s, 4s ... capped at 15s. A Pi Zero takes ~40 s to reboot.
      const delay = Math.min(1000 * 2 ** attempt++, 15000)
      retryTimer = setTimeout(connect, delay)
    }
  }

  connect()

  return () => {
    closed = true
    clearTimeout(retryTimer)
    source?.close()
  }
}
