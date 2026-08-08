<script>
  /**
   * A non-continuous feature.
   *
   * Choices are shown rather than hidden behind a dropdown — this is a
   * wall-panel sort of interface, often used from a phone at arm's length.
   *
   * Two layouts, because one does not stretch: up to four options fit as
   * segments in a grid column, with a highlight that slides so the eye can
   * follow which way the selection moved. Beyond that the labels would be
   * shaved down to "Prod…" and "9…", so wider sets take the full row and wrap
   * as chips instead.
   */
  let { feature, value, pending, onchange } = $props()

  const SEGMENT_LIMIT = 4

  const options = $derived(feature.options ?? [])
  const wide = $derived(options.length > SEGMENT_LIMIT)
  const index = $derived(options.findIndex((o) => o.id === value))
</script>

<div class="select" class:pending class:wide>
  <span class="name">{feature.label}</span>

  <div
    class="options"
    class:chips={wide}
    role="radiogroup"
    aria-label={feature.label}
    style="--count: {options.length}; --index: {index}"
  >
    {#if !wide && index >= 0}
      <span class="marker" aria-hidden="true"></span>
    {/if}
    {#each options as option (option.id)}
      <button
        role="radio"
        aria-checked={option.id === value}
        class:selected={option.id === value}
        disabled={pending}
        onclick={() => onchange(option.id)}
      >
        {option.label}
      </button>
    {/each}
  </div>
</div>

<style>
  .select {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.9rem 1rem 1rem;
  }

  /* The component is itself the grid item, so it can claim the full row. */
  .select.wide {
    grid-column: 1 / -1;
  }

  .name {
    font-size: 0.875rem;
    color: var(--text-dim);
  }

  .options {
    position: relative;
    display: grid;
    grid-template-columns: repeat(var(--count), 1fr);
    gap: 2px;
    padding: 3px;
    border-radius: 11px;
    background: rgba(10, 16, 30, 0.7);
    border: 1px solid var(--border);
  }

  .options.chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    background: none;
    border: none;
    padding: 0;
  }

  /* One sliding highlight instead of per-button backgrounds: the movement
     itself tells you which way the selection went. Segments only — with
     wrapped chips it would point at the wrong place. */
  .marker {
    position: absolute;
    top: 3px;
    bottom: 3px;
    left: 3px;
    width: calc((100% - 6px) / var(--count));
    border-radius: 8px;
    background: linear-gradient(
      140deg,
      rgba(34, 211, 238, 0.28),
      rgba(34, 211, 238, 0.1)
    );
    border: 1px solid rgba(34, 211, 238, 0.45);
    box-shadow: 0 0 16px -4px var(--accent-glow);
    transform: translateX(calc(var(--index) * 100%));
    transition: transform 0.42s var(--ease-out);
  }

  .pending .marker {
    animation: pulse 1.1s var(--ease-in-out) infinite;
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.45;
    }
  }

  button {
    position: relative;
    z-index: 1;
    padding: 0.45rem 0.5rem;
    border-radius: 8px;
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--text-dim);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition:
      color 0.3s var(--ease-out),
      background 0.3s var(--ease-out),
      border-color 0.3s var(--ease-out),
      box-shadow 0.3s var(--ease-out);
  }

  button:hover:not(:disabled) {
    color: var(--text);
  }

  button.selected {
    color: var(--text);
    font-weight: 600;
  }

  button:disabled {
    cursor: wait;
  }

  /* Chips carry their own border, since there is no sliding marker to follow. */
  .chips button {
    padding: 0.42rem 0.8rem;
    border: 1px solid var(--border);
    background: rgba(10, 16, 30, 0.7);
  }

  .chips button:hover:not(:disabled) {
    border-color: var(--border-strong);
  }

  .chips button.selected {
    background: linear-gradient(
      140deg,
      rgba(34, 211, 238, 0.28),
      rgba(34, 211, 238, 0.1)
    );
    border-color: rgba(34, 211, 238, 0.45);
    box-shadow: 0 0 16px -4px var(--accent-glow);
  }

  .pending .chips button.selected {
    animation: pulse 1.1s var(--ease-in-out) infinite;
  }

  @media (max-width: 560px) {
    .options:not(.chips) {
      grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
    }

    /* Wrapped segments would put the marker in the wrong place. */
    .options:not(.chips) .marker {
      display: none;
    }

    .options:not(.chips) button.selected {
      background: linear-gradient(
        140deg,
        rgba(34, 211, 238, 0.28),
        rgba(34, 211, 238, 0.1)
      );
      border: 1px solid rgba(34, 211, 238, 0.45);
    }
  }
</style>
