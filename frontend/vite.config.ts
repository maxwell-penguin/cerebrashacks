import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat': 'http://localhost:8000',
      '/visual-check': 'http://localhost:8000',
      '/audit': 'http://localhost:8000',
      '/generate': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
