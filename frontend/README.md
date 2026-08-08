# Frontend

Svelte 5 + Vite. The production build is committed to
`../service/monitorctl/web/` so that `git clone` plus the Ansible role gives a
working UI — no Node toolchain is needed on the Raspberry Pi.

## Develop against a running service

```bash
npm install
MONITORCTL_DEV_TARGET=http://your-pi:8765 npm run dev
```

## Build

```bash
npm run build      # writes ../service/monitorctl/web/
```

**Commit the build output together with the source change.** CI rebuilds and
fails if the two have drifted apart.

## Notes

- A write takes ~2 s on the monitor's serial bus. Controls hold local intent and
  show a busy state rather than pretending the change was instant.
- Sliders send only the final value. Streaming every intermediate position would
  queue dozens of writes the bus cannot absorb.
- State arrives over SSE (`/api/events`); the browser never polls.
- All motion is behind `prefers-reduced-motion`.
