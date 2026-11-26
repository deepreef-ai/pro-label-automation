/**
 * LOCKED: smoke tests of the multi-tenant screens 16-20 in mock mode (demo v0.2, W4 #60).
 *
 * Login (16), Platform: Companies (17), Add a company (18), Company admin (19) and Cost & usage (20).
 * Each test signs in through the login form with the synthetic demo directory (OTP 123456) and raises
 * no console error or uncaught page error. Playwright gives every test a fresh browser context, so the
 * session (localStorage `pl.session`) never leaks into the screen smoke tests in smoke.spec.ts.
 */
import { expect, test, type Page } from '@playwright/test'

function collectErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text()}`)
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
  return errors
}

async function fillLogin(page: Page, company: string, login: string, otp: string) {
  await page.goto('/login')
  await page.locator('#company').fill(company)
  await page.locator('#login').fill(login)
  await page.getByRole('button', { name: 'Send OTP' }).click()
  await page.locator('#otp').fill(otp)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function signIn(page: Page, company: string, login: string, path: string | RegExp) {
  await fillLogin(page, company, login, '123456')
  await expect(page).toHaveURL(path)
}

const pageTitle = (page: Page, title: string) => page.getByRole('heading', { level: 1, name: title, exact: true })

test.describe('multi-tenant screens (mock mode)', () => {
  test('/login renders the company sign-in', async ({ page }) => {
    const errors = collectErrors(page)
    await page.goto('/login')
    await expect(page.getByText('Sign in to your company workspace')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('Sunrise Flexo owner signs in and lands on the dashboard', async ({ page }) => {
    const errors = collectErrors(page)
    await signIn(page, 'sunriseflexo', 'owner@sunriseflexo.demo', /\/$/)
    await expect(pageTitle(page, 'Dashboard')).toBeVisible()
    await expect(page.locator('header').getByText('Sunrise Flexo Prints').first()).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('a wrong OTP shows "Wrong OTP" and stays on /login', async ({ page }) => {
    const errors = collectErrors(page)
    await fillLogin(page, 'sunriseflexo', 'owner@sunriseflexo.demo', '000000')
    await expect(page.getByText(/Wrong OTP/)).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
    expect(errors).toEqual([])
  })

  test('platform admin sees Companies, Cost & usage and Add a company; / goes to /platform', async ({ page }) => {
    const errors = collectErrors(page)
    await signIn(page, 'platform', 'admin@platform.demo', /\/platform$/)
    await expect(pageTitle(page, 'Companies')).toBeVisible()

    await page.goto('/platform/usage')
    await expect(pageTitle(page, 'Cost & usage')).toBeVisible()

    await page.goto('/platform/add-company')
    await expect(pageTitle(page, 'Add a company')).toBeVisible()

    await page.goto('/')
    await expect(page).toHaveURL(/\/platform$/)
    await expect(pageTitle(page, 'Companies')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('a company user gets "Platform admins only" on /platform', async ({ page }) => {
    const errors = collectErrors(page)
    await signIn(page, 'prolabels', 'store@prolabels.demo', /\/$/)
    await page.goto('/platform')
    await expect(page.getByText('Platform admins only')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('Sunrise Flexo owner sees Users & connections on /company', async ({ page }) => {
    const errors = collectErrors(page)
    await signIn(page, 'sunriseflexo', 'owner@sunriseflexo.demo', /\/$/)
    await page.goto('/company')
    await expect(pageTitle(page, 'Users & connections')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })
})
