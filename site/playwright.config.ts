import { defineConfig } from '@playwright/test';

// The performance budget (DATA.md's synthetic dataset ×10, production build):
//   python3 ../collector/synthetic.py --scale 10 --out static/data
//   npm run build && npm run test:budget
export default defineConfig({
	testDir: 'tests',
	timeout: 60_000,
	workers: 1,
	reporter: 'list',
	use: {
		baseURL: `http://localhost:4173${process.env.BASE_PATH ?? ''}/`,
		launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {}
	},
	webServer: {
		command: 'npm run preview',
		port: 4173,
		reuseExistingServer: !process.env.CI
	}
});
