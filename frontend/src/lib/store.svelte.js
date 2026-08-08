/**
 * The single source of truth for the UI.
 *
 * The service already keeps a cache and pushes changes over SSE, so the browser
 * never polls. What this adds is optimism: a slider must follow your finger at
 * 60 fps even though the monitor needs two seconds to agree, so local intent is
 * held separately from confirmed state and wins until the server catches up.
 */

import { api, subscribe } from './api.js'

class MonitorStore {
  features = $state([])
  state = $state({})
  display = $state(null)
  toggleBetween = $state([])

  connection = $state('connecting') // connecting | live | reconnecting | failed
  loading = $state(true)
  error = $state(null)

  /** Feature names with a write in flight — drives the busy treatment. */
  pending = $state(new Set())
  /** Local values not yet confirmed, so controls stay responsive. */
  optimistic = $state({})

  #unsubscribe = null

  async load() {
    this.loading = true
    this.error = null
    try {
      const [display, features, state] = await Promise.all([
        api.display(),
        api.features(),
        api.state(),
      ])
      this.display = display
      this.features = features.features
      this.toggleBetween = features.toggle_between || []
      this.state = state.state
      this.connection = 'live'
    } catch (err) {
      this.error = err.message
      this.connection = 'failed'
    } finally {
      this.loading = false
    }
  }

  listen() {
    this.#unsubscribe?.()
    this.#unsubscribe = subscribe({
      onState: (changed) => {
        this.state = { ...this.state, ...changed }
        // The server has spoken: drop any local guess for these features.
        const next = { ...this.optimistic }
        for (const name of Object.keys(changed)) delete next[name]
        this.optimistic = next
      },
      onStatus: (status) => {
        const wasDown = this.connection === 'reconnecting'
        this.connection = status
        // Anything could have changed while we were away.
        if (status === 'live' && wasDown) this.refresh()
      },
    })
  }

  destroy() {
    this.#unsubscribe?.()
    this.#unsubscribe = null
  }

  async refresh() {
    try {
      const { state } = await api.state()
      this.state = state
    } catch {
      // The SSE stream will deliver the truth soon enough.
    }
  }

  get(name) {
    return this.state[name] ?? null
  }

  /** Confirmed value, unless a local change is still in flight. */
  valueOf(name) {
    if (name in this.optimistic) return this.optimistic[name]
    return this.state[name]?.value ?? null
  }

  isPending(name) {
    return this.pending.has(name)
  }

  get currentInput() {
    return this.valueOf('input_source')
  }

  get inputFeature() {
    return this.features.find((f) => f.name === 'input_source') ?? null
  }

  get controls() {
    return this.features.filter((f) => f.category === 'control' && !f.readonly)
  }

  get sensors() {
    return this.features.filter((f) => f.category === 'sensor')
  }

  #markPending(name, on) {
    const next = new Set(this.pending)
    if (on) next.add(name)
    else next.delete(name)
    this.pending = next
  }

  async setFeature(name, value) {
    this.optimistic = { ...this.optimistic, [name]: value }
    this.#markPending(name, true)
    this.error = null
    try {
      const result = await api.setFeature(name, value)
      this.state = { ...this.state, [name]: result }
      const next = { ...this.optimistic }
      delete next[name]
      this.optimistic = next
    } catch (err) {
      this.error = err.message
      // Snap back to whatever the monitor actually says.
      const next = { ...this.optimistic }
      delete next[name]
      this.optimistic = next
      throw err
    } finally {
      this.#markPending(name, false)
    }
  }

  async setInput(target) {
    return this.setFeature('input_source', target)
  }

  async toggle() {
    this.#markPending('input_source', true)
    this.error = null
    try {
      const result = await api.toggle()
      this.state = { ...this.state, input_source: result }
    } catch (err) {
      this.error = err.message
      throw err
    } finally {
      this.#markPending('input_source', false)
    }
  }
}

export const monitor = new MonitorStore()
