import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Tabs, TabPanel } from './Tabs'

function TabsFixture({ keepMounted = false }: { keepMounted?: boolean }) {
  const [activeId, setActiveId] = useState('details')
  return (
    <div>
      <Tabs
        items={[
          { id: 'details', label: 'Details' },
          { id: 'history', label: 'History' },
          { id: 'documents', label: 'Documents' },
        ]}
        activeId={activeId}
        onChange={setActiveId}
      />
      <TabPanel id="details" activeId={activeId}>
        Details content
      </TabPanel>
      <TabPanel id="history" activeId={activeId} keepMounted={keepMounted}>
        History content
      </TabPanel>
      <TabPanel id="documents" activeId={activeId}>
        Documents content
      </TabPanel>
    </div>
  )
}

describe('Tabs', () => {
  it('marks only the active tab as selected and shows only its panel', () => {
    render(<TabsFixture />)
    expect(screen.getByRole('tab', { name: 'Details' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByText('Details content')).toBeVisible()
    expect(screen.queryByText('History content')).not.toBeInTheDocument()
  })

  it('switches on click', async () => {
    render(<TabsFixture />)
    await userEvent.click(screen.getByRole('tab', { name: 'History' }))
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('History content')).toBeVisible()
  })

  it('navigates with ArrowRight/ArrowLeft/Home/End, wrapping at the ends', async () => {
    render(<TabsFixture />)
    const details = screen.getByRole('tab', { name: 'Details' })
    details.focus()

    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'History' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true')

    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Details' })).toHaveFocus()

    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Documents' })).toHaveFocus()

    await userEvent.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'Details' })).toHaveFocus()

    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Documents' })).toHaveFocus()
  })

  it('only the active tab is in the default tab order (roving tabindex)', () => {
    render(<TabsFixture />)
    expect(screen.getByRole('tab', { name: 'Details' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('tabindex', '-1')
  })

  it('keepMounted keeps an inactive panel in the DOM (hidden), for registered form fields', () => {
    render(<TabsFixture keepMounted />)
    const historyPanel = screen.getByText('History content')
    expect(historyPanel.closest('[role="tabpanel"]')).not.toBeVisible()
  })
})
