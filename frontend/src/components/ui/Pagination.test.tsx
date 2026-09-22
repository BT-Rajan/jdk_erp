import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pagination } from './Pagination'

describe('Pagination', () => {
  it('renders nothing when there is only one page', () => {
    const { container } = render(<Pagination page={1} totalPages={1} total={3} onPageChange={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('disables Previous on the first page and Next on the last', () => {
    render(<Pagination page={1} totalPages={3} total={30} onPageChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Next' })).not.toBeDisabled()
  })

  it('calls onPageChange with the next/previous page', async () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} totalPages={3} total={30} onPageChange={onPageChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(onPageChange).toHaveBeenCalledWith(3)

    await userEvent.click(screen.getByRole('button', { name: 'Previous' }))
    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('shows the page-size control even on a single page, when wired in', () => {
    render(
      <Pagination page={1} totalPages={1} total={5} onPageChange={vi.fn()} pageSize={20} onPageSizeChange={vi.fn()} />,
    )
    expect(screen.getByText('Per page')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Previous' })).not.toBeInTheDocument()
  })

  it('calls onPageSizeChange with the chosen size', async () => {
    const onPageSizeChange = vi.fn()
    render(
      <Pagination page={1} totalPages={2} total={30} onPageChange={vi.fn()} pageSize={20} onPageSizeChange={onPageSizeChange} pageSizeOptions={[10, 20, 50]} />,
    )
    await userEvent.selectOptions(screen.getByRole('combobox'), '50')
    expect(onPageSizeChange).toHaveBeenCalledWith(50)
  })

  it('omits the page-size control entirely when not wired in', () => {
    render(<Pagination page={1} totalPages={3} total={30} onPageChange={vi.fn()} />)
    expect(screen.queryByText('Per page')).not.toBeInTheDocument()
  })
})
