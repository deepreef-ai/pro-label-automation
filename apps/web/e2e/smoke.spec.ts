/**
 * LOCKED test 7: smoke test of every screen in mock mode (SPEC section 5).
 *
 * Each route renders its single <h1> with the exact page title and raises no console
 * error or uncaught page error. The role switcher hides Money from the Store role.
 */
import { expect, test, type Page } from '@playwright/test'

const ROUTES: { path: string; title: string }[] = [
  { path: '/', title: 'Dashboard' },
  { path: '/marketing', title: 'Marketing' },
  { path: '/jobs', title: 'Jobs' },
  { path: '/jobs/JC-1301', title: 'Job 360' },
  { path: '/design', title: 'Design' },
  { path: '/store', title: 'Store' },
  { path: '/production', title: 'Production' },
  { path: '/qc', title: 'QC' },
  { path: '/dispatch', title: 'Dispatch' },
  { path: '/money', title: 'Money' },
  { path: '/agents', title: 'Agents Center' },
  { path: '/floor', title: 'Floor Board' },
  { path: '/settings', title: 'Settings' },
]

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text()}`)
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
  return errors
}

for (const { path, title } of ROUTES) {
  test(`${path} renders "${title}" without errors`, async ({ page }) => {
    const errors = collectErrors(page)
    await page.goto(path)
    const h1 = page.locator('h1')
    await expect(h1).toHaveCount(1)
    await expect(h1).toHaveText(title)
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })
}

test('role switcher hides Money for the Store role', async ({ page }) => {
  const errors = collectErrors(page)
  await page.goto('/jobs')
  const nav = page.getByRole('navigation', { name: 'Main' })
  await expect(nav.getByRole('link', { name: 'Money' })).toBeVisible()

  await page.getByRole('button', { name: /Change role/ }).click()
  await page.getByRole('menuitemradio', { name: 'Store', exact: true }).click()

  await expect(page.getByRole('button', { name: /Role: Store/ })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Money' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Store', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})
