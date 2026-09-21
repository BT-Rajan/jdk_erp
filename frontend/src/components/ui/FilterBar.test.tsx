import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FilterBar } from './FilterBar'

describe('FilterBar', () => {
  it('renders its children in a grid', () => {
    render(
      <FilterBar>
        <input placeholder="Search" />
        <select>
          <option>Active</option>
        </select>
      </FilterBar>,
    )
    expect(screen.getByPlaceholderText('Search')).toBeInTheDocument()
  })
})
