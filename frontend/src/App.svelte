<script>
  import { onMount, onDestroy } from 'svelte'
  import { fly, fade } from 'svelte/transition'
  import { monitor } from './lib/store.svelte.js'
  import InputTile from './components/InputTile.svelte'
  import Slider from './components/Slider.svelte'
  import SegmentedSelect from './components/SegmentedSelect.svelte'
  import SensorBar from './components/SensorBar.svelte'

  onMount(async () => {
    await monitor.load()
    if (!monitor.error) monitor.listen()
  })

  onDestroy(() => monitor.destroy())

  const inputBusy = $derived(monitor.isPending('input_source'))

  // A guard can refuse a switch — the local_video one refuses to move the
  // picture to this machine unless it is verifiably producing a signal. Better
  // to explain that up front than to let the request fail.
  function guardReason(option) {
    if (option.guard !== 'local_video') return null
    if (monitor.display?.local_video) return null
    return 'This machine is not currently producing a video signal, so switching here would leave the monitor showing a dead input.'
  }

  async function pick(id) {
    try {
      await monitor.setInput(id)
    } catch {
      // The store surfaces the message; nothing further to do here.
    }
  }

  async function change(name, value) {
    try {
      await monitor.setFeature(name, value)
    } catch {
      /* same */
    }
  }
</script>

<div class="shell">
  <header>
    <div class="brand">
      <span class="mark" aria-hidden="true"></span>
      <div>
        <h1>monitor<span class="thin">switch</span></h1>
        {#if monitor.display}
          <p class="sub mono">
            {monitor.display.manufacturer}
            {monitor.display.model} · bus {monitor.display.bus} · VCP
            {monitor.display.vcp_version}
          </p>
        {/if}
      </div>
    </div>

    <div
      class="link"
      class:live={monitor.connection === 'live'}
      class:down={monitor.connection === 'reconnecting' ||
        monitor.connection === 'failed'}
      role="status"
    >
      <span class="pip" aria-hidden="true"></span>
      <span class="eyebrow">
        {#if monitor.connection === 'live'}live
        {:else if monitor.connection === 'reconnecting'}reconnecting
        {:else if monitor.connection === 'failed'}offline
        {:else}connecting{/if}
      </span>
    </div>
  </header>

  {#if monitor.error}
    <div class="alert" role="alert" transition:fly={{ y: -8, duration: 260 }}>
      <strong>{monitor.error}</strong>
      <button onclick={() => (monitor.error = null)} aria-label="Dismiss">×</button>
    </div>
  {/if}

  {#if monitor.loading}
    <div class="loading" transition:fade>
      <span class="spinner" aria-hidden="true"></span>
      <span>Reading the monitor…</span>
    </div>
  {:else if monitor.inputFeature}
    <section transition:fly={{ y: 14, duration: 420 }}>
      <div class="section-head">
        <span class="eyebrow">Source</span>
        {#if monitor.toggleBetween.length >= 2}
          <button
            class="toggle"
            disabled={inputBusy}
            onclick={() => monitor.toggle().catch(() => {})}
          >
            Toggle
          </button>
        {/if}
      </div>

      <div class="tiles">
        {#each monitor.inputFeature.options as option (option.id)}
          {@const reason = guardReason(option)}
          <InputTile
            {option}
            active={monitor.currentInput === option.id}
            busy={inputBusy && monitor.valueOf('input_source') === option.id}
            waiting={inputBusy}
            blocked={!!reason}
            {reason}
            onselect={pick}
          />
        {/each}
      </div>
    </section>

    {#if monitor.controls.filter((f) => f.name !== 'input_source').length}
      <section class="panel controls" transition:fly={{ y: 14, duration: 420, delay: 60 }}>
        <span class="eyebrow">Picture &amp; sound</span>
        <div class="control-grid">
          {#each monitor.controls.filter((f) => f.name !== 'input_source') as feature (feature.name)}
            {#if feature.type === 'continuous'}
              <Slider
                {feature}
                value={monitor.valueOf(feature.name)}
                pending={monitor.isPending(feature.name)}
                onchange={(v) => change(feature.name, v)}
              />
            {:else if feature.options?.length}
              <SegmentedSelect
                {feature}
                value={monitor.valueOf(feature.name)}
                pending={monitor.isPending(feature.name)}
                onchange={(v) => change(feature.name, v)}
              />
            {/if}
          {/each}
        </div>
      </section>
    {/if}

    <section transition:fly={{ y: 14, duration: 420, delay: 120 }}>
      <span class="eyebrow">Readings</span>
      <SensorBar sensors={monitor.sensors} state={monitor.state} />
    </section>
  {:else}
    <div class="alert" role="alert">
      This monitor exposes no input-source feature. See
      <code>docs/profiles.md</code> for how to describe it.
    </div>
  {/if}
</div>

<style>
  .shell {
    max-width: 940px;
    margin: 0 auto;
    padding: 2.2rem 1.25rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.9rem;
  }

  .mark {
    width: 34px;
    height: 34px;
    border-radius: 9px;
    border: 1.5px solid var(--accent);
    box-shadow: 0 0 18px -4px var(--accent-glow), inset 0 0 14px -6px var(--accent-glow);
    position: relative;
  }

  .mark::after {
    content: '';
    position: absolute;
    inset: 7px;
    border-radius: 3px;
    background: var(--accent);
    opacity: 0.75;
    animation: blink 3.6s var(--ease-in-out) infinite;
  }

  @keyframes blink {
    0%,
    100% {
      opacity: 0.75;
      transform: scale(1);
    }
    50% {
      opacity: 0.3;
      transform: scale(0.82);
    }
  }

  h1 {
    font-size: 1.35rem;
    letter-spacing: -0.02em;
  }

  .thin {
    color: var(--text-faint);
    font-weight: 300;
  }

  .sub {
    margin: 0.15rem 0 0;
    font-size: 0.7rem;
    color: var(--text-faint);
  }

  .link {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.75rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: rgba(10, 16, 30, 0.6);
  }

  .pip {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--text-faint);
  }

  .link.live .pip {
    background: var(--ok);
    box-shadow: 0 0 10px rgba(52, 211, 153, 0.8);
    animation: blink 2.6s var(--ease-in-out) infinite;
  }

  .link.down .pip {
    background: var(--warn);
    animation: blink 0.9s var(--ease-in-out) infinite;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
  }

  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .toggle {
    padding: 0.35rem 0.9rem;
    border-radius: 999px;
    border: 1px solid var(--border-strong);
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--text-dim);
    transition: all 0.28s var(--ease-out);
  }

  .toggle:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--accent);
    box-shadow: 0 0 18px -6px var(--accent-glow);
  }

  .toggle:disabled {
    opacity: 0.4;
    cursor: wait;
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 0.9rem;
  }

  .controls {
    padding: 1.1rem 0.6rem 0.8rem;
    gap: 0.5rem;
  }

  .controls > .eyebrow {
    padding: 0 0.9rem;
  }

  .control-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
    gap: 0.15rem;
  }

  .alert {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.8rem 1rem;
    border-radius: var(--radius);
    border: 1px solid rgba(251, 113, 133, 0.4);
    background: rgba(251, 113, 133, 0.1);
    color: #ffd9de;
    font-size: 0.875rem;
  }

  .alert button {
    font-size: 1.3rem;
    line-height: 1;
    color: inherit;
    opacity: 0.7;
  }

  .alert button:hover {
    opacity: 1;
  }

  .loading {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    padding: 3rem 0;
    color: var(--text-dim);
  }

  .spinner {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    animation: spin 0.85s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  @media (max-width: 560px) {
    .shell {
      padding: 1.4rem 0.9rem 3rem;
      gap: 1.5rem;
    }

    .tiles {
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    }
  }
</style>
