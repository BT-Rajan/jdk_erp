import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Skeleton } from './Skeleton'

describe('Skeleton', () => {
  it('renders a hidden-from-assistive-tech placeholder block', () => {
    const { container } = render(<Skeleton className="h-4 w-32" />)
    const el = container.firstChild as HTMLElement
    expect(el).toHaveAttribute('aria-hidden', 'true')
    expect(el.className).toContain('animate-pulse')
    expect(el.className).toContain('h-4')
  })
})
