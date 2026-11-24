import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// base: './' so the built dist/index.html can be opened directly via file://
// (double-click) as well as served from any static host/subpath.
// server.port pinned to 5173 (Tower 4 is on 5174) so both pilot mockups can
// run side by side without a port clash.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
  },
})
