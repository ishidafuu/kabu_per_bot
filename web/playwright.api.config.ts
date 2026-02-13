import { defineConfig, devices } from '@playwright/test';
import { existsSync } from 'node:fs';

const webPort = 4173;
const apiPort = 8100;
const apiPython = process.env.E2E_API_PYTHON ?? (existsSync('../.venv/bin/python') ? '../.venv/bin/python' : 'python3');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `PYTHONPATH=../src ${apiPython} ../scripts/run_web_test_api.py --host 127.0.0.1 --port ${apiPort}`,
      port: apiPort,
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
    {
      command: `VITE_USE_MOCK_API=false VITE_USE_MOCK_AUTH=true VITE_API_BASE_URL=/api/v1 VITE_DEV_PROXY_TARGET=http://127.0.0.1:${apiPort} npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      port: webPort,
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
