import { defineConfig } from '@playwright/test'

export default defineConfig({
  use: { baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:18081', channel: 'chrome', screenshot: 'only-on-failure' },
  testDir: './e2e',
  workers: 1,
  reporter: 'list',
})
