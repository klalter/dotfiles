import { test, expect } from '@playwright/test'

const BASE_URL = 'http://localhost:3030'

test.describe('Slidev draw.io themes', () => {
  test('modern theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/1`)
    await page.waitForSelector('.drawio-container', { timeout: 10000 })
    await expect(page.locator('.drawio-theme-modern')).toBeVisible()
    await expect(page).toHaveScreenshot('modern-theme.png')
  })

  test('dark theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/2`)
    await page.waitForSelector('.drawio-container', { timeout: 10000 })
    await expect(page.locator('.drawio-theme-dark')).toBeVisible()
    await expect(page).toHaveScreenshot('dark-theme.png')
  })

  test('neon theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/3`)
    await page.waitForSelector('.drawio-container', { timeout: 10000 })
    await expect(page.locator('.drawio-theme-neon')).toBeVisible()
    await expect(page).toHaveScreenshot('neon-theme.png')
  })

  test('minimal theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/4`)
    await page.waitForSelector('.drawio-container', { timeout: 10000 })
    await expect(page.locator('.drawio-theme-minimal')).toBeVisible()
    await expect(page).toHaveScreenshot('minimal-theme.png')
  })

  test('edit button appears on hover', async ({ page }) => {
    await page.goto(`${BASE_URL}/1`)
    await page.waitForSelector('.drawio-container', { timeout: 10000 })
    const container = page.locator('.drawio-container').first()
    await container.hover()
    await expect(page.locator('.drawio-edit-btn')).toBeVisible()
    await expect(page).toHaveScreenshot('edit-button-hover.png')
  })
})
