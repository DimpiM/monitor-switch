import { defineConfig, loadEnv } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Point `npm run dev` at a running service:
//   MONITORCTL_DEV_TARGET=http://your-pi:8765 npm run dev
const DEFAULT_DEV_TARGET = 'http://localhost:8765'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'MONITORCTL_')
  const target =
    process.env.MONITORCTL_DEV_TARGET ||
    env.MONITORCTL_DEV_TARGET ||
    DEFAULT_DEV_TARGET

  return {
    plugins: [svelte()],
    build: {
      // The build lands directly in the Python package so that `git clone` plus
      // the Ansible role is enough to get a working UI — no Node on the Pi.
      outDir: '../service/monitorctl/web',
      emptyOutDir: true,
      // One file each. On a Pi Zero over Wi-Fi, fewer round trips beats caching
      // granularity, and the whole bundle is well under 100 kB.
      rollupOptions: {
        output: {
          entryFileNames: 'app.js',
          chunkFileNames: 'app-[hash].js',
          assetFileNames: 'app.[ext]',
        },
      },
    },
    server: {
      proxy: {
        '/api': { target, changeOrigin: true },
        '/healthz': { target, changeOrigin: true },
      },
    },
  }
})
