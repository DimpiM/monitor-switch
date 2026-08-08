<script>
  /**
   * One input source. The primary control of the whole application, so it gets
   * the space and the motion budget.
   *
   * Three states worth distinguishing at a glance: this is where the picture is
   * now, this is being switched to right now, and this one cannot be switched
   * to at the moment because its guard says so.
   */
  let { option, active, busy, waiting, blocked, reason, onselect } = $props()

  // All three prevent a click, but they mean different things to a person:
  //   busy     this tile is the one being switched to right now
  //   waiting  some other switch is in flight; the bus takes one at a time
  //   blocked  a guard refuses this target outright
  const disabled = $derived(busy || waiting || blocked)
</script>

<button
  class="tile"
  class:active
  class:busy
  class:blocked
  aria-pressed={active}
  aria-label={option.label + (active ? ' — currently displayed' : '')}
  aria-busy={busy}
  {disabled}
  title={reason || ''}
  onclick={() => onselect(option.id)}
>
  <span class="sheen" aria-hidden="true"></span>
  <span class="scan" aria-hidden="true"></span>

  <span class="body">
    <span class="dot" aria-hidden="true"></span>
    <span class="label">{option.label}</span>
    <span class="status">
      {#if busy}switching…{:else if active}on screen{:else if blocked}unavailable{:else}switch{/if}
    </span>
  </span>

  <span class="corner tl" aria-hidden="true"></span>
  <span class="corner br" aria-hidden="true"></span>
</button>

<style>
  .tile {
    position: relative;
    display: block;
    width: 100%;
    min-height: 138px;
    padding: 1.25rem;
    text-align: left;
    overflow: hidden;
    isolation: isolate;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border);
    background: var(--surface);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    transition:
      transform 0.35s var(--ease-out),
      border-color 0.35s var(--ease-out),
      box-shadow 0.35s var(--ease-out),
      background 0.35s var(--ease-out);
  }

  .tile:hover:not(:disabled):not(.active) {
    transform: translateY(-3px);
    border-color: var(--border-strong);
    background: var(--surface-strong);
  }

  .tile:active:not(:disabled) {
    transform: translateY(0) scale(0.985);
    transition-duration: 0.08s;
  }

  /* A standing refusal is dimmed hard. Waiting out a switch only softens, so
     the panel does not look like it fell apart for two seconds. */
  .tile.blocked {
    opacity: 0.42;
    cursor: not-allowed;
  }

  .tile:disabled:not(.blocked):not(.busy) {
    opacity: 0.72;
    cursor: wait;
  }

  /* The active tile is the one thing on screen that glows and breathes. */
  .tile.active {
    border-color: var(--active);
    background: linear-gradient(
      145deg,
      rgba(244, 114, 182, 0.14),
      rgba(24, 34, 58, 0.85) 62%
    );
    box-shadow:
      0 0 0 1px var(--active-glow),
      0 0 34px -6px var(--active-glow),
      inset 0 0 44px -22px var(--active-glow);
    animation: breathe 4.5s var(--ease-in-out) infinite;
  }

  @keyframes breathe {
    0%,
    100% {
      box-shadow:
        0 0 0 1px var(--active-glow),
        0 0 30px -8px var(--active-glow),
        inset 0 0 40px -24px var(--active-glow);
    }
    50% {
      box-shadow:
        0 0 0 1px var(--active-glow),
        0 0 46px -4px var(--active-glow),
        inset 0 0 56px -18px var(--active-glow);
    }
  }

  /* A highlight that sweeps once on hover — reads as glass catching light. */
  .sheen {
    position: absolute;
    inset: 0;
    z-index: -1;
    background: linear-gradient(
      105deg,
      transparent 38%,
      rgba(190, 230, 255, 0.11) 50%,
      transparent 62%
    );
    transform: translateX(-100%);
    transition: transform 0.85s var(--ease-out);
  }

  .tile:hover:not(:disabled) .sheen {
    transform: translateX(100%);
  }

  /* Only while a switch is actually in flight. Two seconds of real work
     deserves an honest indicator rather than an instant lie. */
  .scan {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    height: 2px;
    z-index: 1;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    opacity: 0;
  }

  .tile.busy .scan {
    opacity: 1;
    animation: scan 1.15s var(--ease-in-out) infinite;
  }

  @keyframes scan {
    0% {
      transform: translateY(0);
    }
    100% {
      transform: translateY(136px);
    }
  }

  .tile.busy {
    border-color: var(--accent);
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    height: 100%;
  }

  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--text-faint);
    box-shadow: 0 0 0 4px rgba(120, 160, 220, 0.08);
    transition: background 0.3s var(--ease-out), box-shadow 0.3s var(--ease-out);
  }

  .tile.active .dot {
    background: var(--active);
    box-shadow: 0 0 0 4px rgba(244, 114, 182, 0.18), 0 0 14px var(--active-glow);
  }

  .tile.busy .dot {
    background: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-soft), 0 0 14px var(--accent-glow);
  }

  .label {
    margin-top: auto;
    font-size: 1.32rem;
    font-weight: 600;
    letter-spacing: -0.015em;
  }

  .status {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-faint);
    transition: color 0.3s var(--ease-out);
  }

  .tile.active .status {
    color: var(--active);
  }

  .tile.busy .status {
    color: var(--accent);
  }

  /* Bracket corners — cheap way to read as instrumentation. */
  .corner {
    position: absolute;
    width: 13px;
    height: 13px;
    opacity: 0;
    transition: opacity 0.35s var(--ease-out);
  }

  .tl {
    top: 10px;
    left: 10px;
    border-top: 1.5px solid var(--active);
    border-left: 1.5px solid var(--active);
  }

  .br {
    bottom: 10px;
    right: 10px;
    border-bottom: 1.5px solid var(--active);
    border-right: 1.5px solid var(--active);
  }

  .tile.active .corner {
    opacity: 0.85;
  }

  @media (max-width: 560px) {
    .tile {
      min-height: 108px;
      padding: 1rem;
    }

    .label {
      font-size: 1.1rem;
    }

    @keyframes scan {
      0% {
        transform: translateY(0);
      }
      100% {
        transform: translateY(106px);
      }
    }
  }
</style>
