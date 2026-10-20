import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://api:8000' } },
  test: { environment: 'node', exclude: ['e2e/**', 'node_modules/**'] },
})

