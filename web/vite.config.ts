import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const port = process.env.VECTOR_WEB_PORT || '8787'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${port}`,
      },
    },
  },
})
