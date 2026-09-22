import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ContextMenu } from './ContextMenu'

describe('ContextMenu', () => {
  it('is closed until the wrapped element is right-clicked', () => {
    render(
      <ContextMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect: vi.fn() }]}>
        <div>Row</div>
      </ContextMenu>,
    )
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('opens on right-click, positioned at the cursor, and selecting an option calls onSelect and closes it', async () => {
    const onSelect = vi.fn()
    render(
      <ContextMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect }]}>
        <div>Row</div>
      </ContextMenu>,
    )
    await userEvent.pointer({ keys: '[MouseRight]', target: screen.getByText('Row') })

    const menu = screen.getByRole('menu', { name: 'Row actions' })
    expect(menu).toBeInTheDocument()
    expect(menu).toHaveStyle({ position: 'fixed' })

    await userEvent.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(onSelect).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    render(
      <ContextMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect: vi.fn() }]}>
        <div>Row</div>
      </ContextMenu>,
    )
    await userEvent.pointer({ keys: '[MouseRight]', target: screen.getByText('Row') })
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when clicking outside', async () => {
    render(
      <div>
        <button type="button">Outside</button>
        <ContextMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect: vi.fn() }]}>
          <div>Row</div>
        </ContextMenu>
      </div>,
    )
    await userEvent.pointer({ keys: '[MouseRight]', target: screen.getByText('Row') })
    expect(screen.getByRole('menu')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Outside' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('does not suppress an onContextMenu handler already on the wrapped element', async () => {
    const existingHandler = vi.fn()
    render(
      <ContextMenu label="Row actions" options={[{ key: 'edit', label: 'Edit', onSelect: vi.fn() }]}>
        <div onContextMenu={existingHandler}>Row</div>
      </ContextMenu>,
    )
    await userEvent.pointer({ keys: '[MouseRight]', target: screen.getByText('Row') })
    expect(existingHandler).toHaveBeenCalledOnce()
  })
})
