import { describe, it, expect } from 'vitest'
import { escapeHtml, formatPrice, formatPercent } from './helpers'

describe('String utilities', () => {
  it('should escape HTML characters', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;')
  })

  it('should format price correctly', () => {
    expect(formatPrice(100)).toBe('¥100.00')
    expect(formatPrice(99.9)).toBe('¥99.90')
  })

  it('should format percent correctly', () => {
    expect(formatPercent(0.1234)).toBe('12.34%')
    expect(formatPercent(0.5)).toBe('50.00%')
  })
})
