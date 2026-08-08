<script>
  /**
   * Read-only readings, kept deliberately quiet. They are context, not
   * controls, so they sit at the bottom in a smaller type scale.
   */
  let { sensors, state } = $props()

  const shown = $derived(
    sensors
      .map((f) => ({ feature: f, reading: state[f.name] }))
      .filter((s) => s.reading && !s.reading.error),
  )
</script>

{#if shown.length}
  <div class="bar">
    {#each shown as { feature, reading } (feature.name)}
      <div class="cell">
        <span class="label">{feature.label}</span>
        <span class="value mono">{reading.display ?? '—'}</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
    gap: 1px;
    overflow: hidden;
    border-radius: var(--radius);
    background: var(--border);
    border: 1px solid var(--border);
  }

  .cell {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.7rem 0.85rem;
    background: rgba(8, 12, 22, 0.72);
  }

  .label {
    font-size: 0.625rem;
    font-weight: 600;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    color: var(--text-faint);
  }

  .value {
    font-size: 0.9rem;
    color: var(--text-dim);
  }
</style>
