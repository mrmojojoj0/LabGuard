import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: env.LABGUARD_DASHBOARD_HOST || '127.0.0.1',
      port: Number(env.LABGUARD_DASHBOARD_PORT || 5173),
      proxy: { '/api': { target: env.LABGUARD_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
    },
  }
})
