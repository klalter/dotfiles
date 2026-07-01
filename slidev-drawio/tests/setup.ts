import { vi } from 'vitest'

// Mock fetch for diagram files
global.fetch = vi.fn()

// Mock window.postMessage
Object.defineProperty(window, 'postMessage', {
  value: vi.fn(),
  writable: true,
})

// Mock import.meta.env
Object.defineProperty(import.meta, 'env', {
  value: { BASE_URL: '/' },
  writable: true,
})
