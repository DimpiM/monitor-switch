<script>
  /**
   * A continuous feature.
   *
   * The bus cannot keep up with a dragging finger — each write is the better
   * part of a second — so the thumb follows input locally and only the final
   * value is sent. Anything else would queue dozens of writes and make the UI
   * feel broken.
   */
  let { feature, value, pending, onchange } = $props()

  let dragging = $state(false)
  let local = $state(null)

  // Track the server while idle; while dragging, local intent wins. This also
  // seeds the initial value, so the thumb is correct on first paint.
  $effect(() => {
    if (!dragging) local = value
  })

  const min = $derived(feature.min ?? 0)
  const max = $derived(feature.max ?? 100)
  const percent = $derived(
    max > min ? ((Number(local ?? 0) - min) / (max - min)) * 100 : 0,
  )

  function commit() {
    dragging = false
    if (Number(local) !== Number(value)) onchange(Number(local))
  }
</script>

<div class="slider" class:pending>
  <div class="head">
    <span class="name">{feature.label}</span>
    <span class="value mono">
      {local ?? '—'}<span class="unit">{feature.unit || ''}</span>
    </span>
  </div>

  <div class="track-wrap">
    <div class="track" aria-hidden="true">
      <div class="fill" style="width: {percent}%">
        <span class="fill-glow"></span>
      </div>
    </div>
    <input
      type="range"
      {min}
      {max}
      step="1"
      bind:value={local}
      aria-label={feature.label}
      oninput={() => (dragging = true)}
      onchange={commit}
      onpointerup={commit}
      onkeyup={commit}
    />
  </div>
</div>

<style>
  .slider {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    padding: 0.9rem 1rem 1.05rem;
    border-radius: var(--radius);
    border: 1px solid transparent;
    transition: border-color 0.3s var(--ease-out), background 0.3s var(--ease-out);
  }

  .slider:hover {
    background: rgba(255, 255, 255, 0.02);
  }

  .slider.pending {
    border-color: var(--accent-soft);
  }

  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }

  .name {
    font-size: 0.875rem;
    color: var(--text-dim);
  }

  .value {
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text);
    transition: color 0.2s var(--ease-out);
  }

  .slider.pending .value {
    color: var(--accent);
  }

  .unit {
    margin-left: 1px;
    font-size: 0.75rem;
    color: var(--text-faint);
  }

  .track-wrap {
    position: relative;
    height: 22px;
    display: flex;
    align-items: center;
  }

  .track {
    position: absolute;
    inset: 0 0 0 0;
    margin: auto;
    height: 5px;
    border-radius: 999px;
    background: rgba(120, 160, 220, 0.14);
    overflow: hidden;
  }

  .fill {
    position: relative;
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, rgba(34, 211, 238, 0.5), var(--accent));
    transition: width 0.12s linear;
  }

  /* A travelling highlight along the filled part. Slow enough to read as a
     glow rather than a loading bar. */
  .fill-glow {
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent,
      rgba(255, 255, 255, 0.55),
      transparent
    );
    transform: translateX(-100%);
    animation: sweep 3.4s var(--ease-in-out) infinite;
  }

  @keyframes sweep {
    0%,
    55% {
      transform: translateX(-100%);
    }
    100% {
      transform: translateX(100%);
    }
  }

  input[type='range'] {
    position: relative;
    width: 100%;
    margin: 0;
    background: transparent;
    -webkit-appearance: none;
    appearance: none;
    cursor: pointer;
  }

  input[type='range']::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 17px;
    height: 17px;
    border-radius: 50%;
    background: #eafcff;
    border: 2px solid var(--accent);
    box-shadow: 0 0 12px var(--accent-glow);
    transition: transform 0.18s var(--ease-out), box-shadow 0.18s var(--ease-out);
  }

  input[type='range']:hover::-webkit-slider-thumb,
  input[type='range']:active::-webkit-slider-thumb {
    transform: scale(1.18);
    box-shadow: 0 0 20px var(--accent-glow);
  }

  input[type='range']::-moz-range-thumb {
    width: 15px;
    height: 15px;
    border-radius: 50%;
    background: #eafcff;
    border: 2px solid var(--accent);
    box-shadow: 0 0 12px var(--accent-glow);
  }

  input[type='range']::-moz-range-track {
    background: transparent;
  }
</style>
