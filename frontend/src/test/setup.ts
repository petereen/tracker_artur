import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'
import { i18nReady } from '../i18n'

// Components read translations synchronously, so the Mongolian catalogue must be in before any test runs.
await i18nReady

vi.stubGlobal('ResizeObserver', class {
  observe() {}
  unobserve() {}
  disconnect() {}
})

afterEach(cleanup)
