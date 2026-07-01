/**
 * Playwright visual regression tests for slidev-addon-drawio themes.
 *
 * Prerequisites:
 *   1. Start the example Slidev dev server: cd example && npm run dev
 *   2. Run: npm run test:visual
 *
 * Slide index (0-indexed in URL, but Slidev uses 1-indexed):
 *   Slide 1 = cover
 *   Slide 2 = modern theme embed
 *   Slide 3 = dark theme embed
 *   Slide 4 = neon theme embed
 *   Slide 5 = minimal theme embed
 *   Slide 6 = full-page modern
 *   Slide 7 = full-page dark
 */
import { test, expect } from '@playwright/test'

const BASE_URL = process.env.SLIDEV_URL || 'http://localhost:3030'

// Wait for diagram to finish loading (loading spinner gone)
async function waitForDiagram(page: import('@playwright/test').Page) {
  await page.waitForSelector('.drawio-container', { timeout: 15000 })
  // Wait for loading spinner to disappear
  await page.waitForFunction(
    () => !document.querySelector('.drawio-loading'),
    { timeout: 15000 }
  ).catch(() => {
    // Loading might have already finished; ignore timeout
  })
  // Give iframe a moment to paint
  await page.waitForTimeout(500)
}

test.describe('Slidev draw.io themes', () => {
  test('cover slide renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/1`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('h1')).toBeVisible()
    await expect(page).toHaveScreenshot('01-cover.png', { fullPage: true })
  })

  test('modern theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/2`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-theme-modern')).toBeVisible()
    await expect(page).toHaveScreenshot('02-modern-theme.png', { fullPage: true })
  })

  test('dark theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/3`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-theme-dark')).toBeVisible()
    await expect(page).toHaveScreenshot('03-dark-theme.png', { fullPage: true })
  })

  test('neon theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/4`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-theme-neon')).toBeVisible()
    await expect(page).toHaveScreenshot('04-neon-theme.png', { fullPage: true })
  })

  test('minimal theme renders correctly', async ({ page }) => {
    await page.goto(`${BASE_URL}/5`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-theme-minimal')).toBeVisible()
    await expect(page).toHaveScreenshot('05-minimal-theme.png', { fullPage: true })
  })

  test('full-page modern layout renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/6`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-full-container')).toBeVisible()
    await expect(page).toHaveScreenshot('06-full-page-modern.png', { fullPage: true })
  })

  test('full-page dark layout renders', async ({ page }) => {
    await page.goto(`${BASE_URL}/7`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-full-container')).toBeVisible()
    await expect(page).toHaveScreenshot('07-full-page-dark.png', { fullPage: true })
  })

  test('edit button is visible when editable=true', async ({ page }) => {
    await page.goto(`${BASE_URL}/2`)
    await waitForDiagram(page)
    await expect(page.locator('.drawio-edit-btn')).toBeVisible()
    await expect(page).toHaveScreenshot('08-edit-button-visible.png')
  })

  test('edit button opens editor overlay', async ({ page }) => {
    await page.goto(`${BASE_URL}/2`)
    await waitForDiagram(page)

    const editBtn = page.locator('.drawio-edit-btn').first()
    await editBtn.click()

    // Editor overlay should appear
    await page.waitForSelector('.drawio-editor-overlay', { timeout: 5000 })
    await expect(page.locator('.drawio-editor-overlay')).toBeVisible()
    await expect(page).toHaveScreenshot('09-editor-overlay.png', { fullPage: true })
  })

  test('editor close button works', async ({ page }) => {
    await page.goto(`${BASE_URL}/2`)
    await waitForDiagram(page)

    // Open editor
    await page.locator('.drawio-edit-btn').first().click()
    await page.waitForSelector('.drawio-editor-overlay', { timeout: 5000 })

    // Close editor
    await page.locator('.drawio-editor-close').click()
    await page.waitForFunction(
      () => !document.querySelector('.drawio-editor-overlay'),
      { timeout: 5000 }
    )
    await expect(page.locator('.drawio-editor-overlay')).not.toBeVisible()
  })
})
