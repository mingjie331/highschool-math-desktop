import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: { assetsDir: 'static' },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/assets': 'http://127.0.0.1:8765',
      '/exports': 'http://127.0.0.1:8765',
    },
  },
})
