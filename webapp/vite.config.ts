import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5199,
    proxy: {
      // forward API calls to the stdlib Python SPICE bridge (server.py)
      '/api': 'http://127.0.0.1:8770',
    },
  },
})
