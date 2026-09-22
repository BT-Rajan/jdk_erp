/** Proves the "one form system" claim end to end: react-hook-form +
 * zod + these field components, wired together exactly as a real
 * module would. Nothing here is a new abstraction -- register()'s
 * return value is just native input props, which every field already
 * accepts. */
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TextField } from './TextField'
import { NumberField } from './NumberField'
import { FormActions } from './FormActions'

const schema = z.object({
  name: z.string().min(1, 'Name is required'),
  age: z.coerce.number().min(18, 'Must be at least 18'),
})

// z.coerce.number() accepts any input type before coercing, so the
// form's field-value type (what register()/handleSubmit see) and the
// resolver's parsed output type (what onSubmit receives) genuinely
// differ -- react-hook-form's third useForm generic exists for exactly
// this case.
type FormInput = z.input<typeof schema>
type FormOutput = z.output<typeof schema>

function TestForm({ onSubmit }: { onSubmit: (values: FormOutput) => void }) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormInput, unknown, FormOutput>({ resolver: zodResolver(schema) })

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <TextField label="Name" required {...register('name')} error={errors.name?.message} />
      <NumberField label="Age" required {...register('age')} error={errors.age?.message} />
      <FormActions onCancel={() => {}} submitting={isSubmitting} />
    </form>
  )
}

describe('react-hook-form + zod + Common Form fields', () => {
  it('surfaces zod validation errors through each field\'s own error prop, UI-side, before any submit happens', async () => {
    render(<TestForm onSubmit={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Name is required')).toBeInTheDocument()
    expect(await screen.findByText('Must be at least 18')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true')
  })

  it('calls onSubmit with the parsed values once validation passes', async () => {
    const onSubmit = vi.fn()
    render(<TestForm onSubmit={onSubmit} />)

    await userEvent.type(screen.getByLabelText('Name'), 'Ada Lovelace')
    await userEvent.type(screen.getByLabelText('Age'), '30')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
    expect(onSubmit.mock.calls[0][0]).toEqual({ name: 'Ada Lovelace', age: 30 })
  })

  it('does not call onSubmit while a field still fails validation', async () => {
    const onSubmit = vi.fn()
    render(<TestForm onSubmit={onSubmit} />)

    await userEvent.type(screen.getByLabelText('Name'), 'Ada Lovelace')
    await userEvent.type(screen.getByLabelText('Age'), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Must be at least 18')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
