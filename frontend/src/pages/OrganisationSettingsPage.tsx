import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

/** Mirrors backend/app/schemas/organisation.py's OrganisationOut. */
interface Organisation {
  id: number
  name: string
  code: string
  contact_email: string | null
  contact_phone: string | null
  address: string | null
  email_domain: string | null
  currency: string
  timezone: string
  production_staff_available_per_day?: number | null
  /** Decimal string from the API, e.g. "2.50"; default "0.00". */
  delivery_scrap_allowance_percent?: string
  is_active: boolean
}

const schema = z.object({
  name: z.string().min(1, 'Name is required'),
  code: z.string().min(1, 'Code is required'),
  contact_email: z
    .string()
    .refine((value) => value === '' || z.string().email().safeParse(value).success, 'Enter a valid email address'),
  contact_phone: z.string(),
  address: z.string(),
  email_domain: z.string(),
  // Mirrors backend/app/schemas/organisation.py's currency/timezone
  // validators -- UI-side validation ahead of the server's authoritative
  // check (docs/modules/common_validation.md), not a replacement for it.
  currency: z
    .string()
    .length(3, 'Currency must be a 3-letter ISO code, e.g. KWD')
    .regex(/^[A-Za-z]+$/, 'Currency must be letters only'),
  timezone: z.string().min(1, 'Timezone is required'),
  production_staff_available_per_day: z
    .string()
    .refine((value) => value === '' || /^\d+$/.test(value), 'Enter a whole number of staff'),
  // Mirrors the server rule: 0-999.99, at most 2 decimal places, never negative.
  delivery_scrap_allowance_percent: z
    .string()
    .regex(/^\d{1,3}(\.\d{1,2})?$/, 'Enter a percentage from 0 to 999.99, with up to 2 decimal places'),
})

type FormValues = z.infer<typeof schema>

function toFormValues(org: Organisation): FormValues {
  return {
    name: org.name,
    code: org.code,
    contact_email: org.contact_email ?? '',
    contact_phone: org.contact_phone ?? '',
    address: org.address ?? '',
    email_domain: org.email_domain ?? '',
    currency: org.currency,
    timezone: org.timezone,
    production_staff_available_per_day:
      org.production_staff_available_per_day == null ? '' : String(org.production_staff_available_per_day),
    delivery_scrap_allowance_percent: org.delivery_scrap_allowance_percent ?? '0',
  }
}

/** Admin-only Organisation settings: view and edit the caller's own
 * organisation, and activate/deactivate it (backend/app/api/organisations.py,
 * docs/modules/organisation.md #6). Deliberately minimal and
 * administrative, per that module's own "not a tenant-management
 * framework" principle -- no dashboard, no analytics, no hierarchy.
 * Server-side is the real boundary (Principle 3); AccessDeniedState
 * below is a usability courtesy for a non-admin who lands on this route
 * directly. */
export function OrganisationSettingsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [organisation, setOrganisation] = useState<Organisation | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | undefined>(undefined)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [statusConfirmOpen, setStatusConfirmOpen] = useState(false)
  const [statusError, setStatusError] = useState<string | undefined>(undefined)
  const [statusBusy, setStatusBusy] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    setError: setFieldError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  useEffect(() => {
    if (!canManage) return
    let cancelled = false
    setLoading(true)
    setLoadError(undefined)
    apiClient
      .get<Organisation>('/api/organisations/me')
      .then(({ data }) => {
        if (cancelled) return
        setOrganisation(data)
        reset(toFormValues(data))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(err instanceof ApiError ? err.message : 'Failed to load organisation.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [canManage, reset])

  if (!canManage) {
    return (
      <div className="space-y-6">
        <PageHeader title="Organisation" />
        <AccessDeniedState message="Only an organisation admin can manage organisation settings." />
      </div>
    )
  }

  async function onSubmit(values: FormValues) {
    setSaveError(null)
    const payload = {
      ...values,
      contact_email: values.contact_email || null,
      contact_phone: values.contact_phone || null,
      address: values.address || null,
      email_domain: values.email_domain || null,
      currency: values.currency.toUpperCase(),
      production_staff_available_per_day:
        values.production_staff_available_per_day === '' ? null : Number(values.production_staff_available_per_day),
      // Sent as a string so the exact decimal reaches the server.
      delivery_scrap_allowance_percent: values.delivery_scrap_allowance_percent,
    }
    try {
      const { data } = await apiClient.patch<Organisation>('/api/organisations/me', payload)
      setOrganisation(data)
      reset(toFormValues(data))
    } catch (err) {
      if (!(err instanceof ApiError)) {
        setSaveError('Something went wrong. Please try again.')
      } else if (err.fields) {
        for (const [field, message] of Object.entries(err.fields)) {
          if (field in schema.shape) setFieldError(field as keyof FormValues, { message })
          else setSaveError(message)
        }
      } else {
        setSaveError(err.message)
      }
    }
  }

  async function confirmStatusChange() {
    if (!organisation) return
    setStatusBusy(true)
    setStatusError(undefined)
    try {
      const { data } = await apiClient.patch<Organisation>('/api/organisations/me/status', {
        is_active: !organisation.is_active,
      })
      setOrganisation(data)
      setStatusConfirmOpen(false)
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : 'Failed to change organisation status.')
    } finally {
      setStatusBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Organisation" />
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Organisation" subtitle="Your organisation's own record -- the top-level boundary every user and record in JDK belongs to." />

      <Alert variant="danger">{loadError}</Alert>

      <Card className="p-6">
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <Alert variant="danger">{saveError}</Alert>

          <FormSectionHeading>Organisation details</FormSectionHeading>
          <TextField label="Name" required {...register('name')} error={errors.name?.message} />
          <TextField label="Code" required {...register('code')} error={errors.code?.message} />
          <TextField label="Contact email" type="email" {...register('contact_email')} error={errors.contact_email?.message} />
          <TextField label="Contact phone" {...register('contact_phone')} error={errors.contact_phone?.message} />
          <TextareaField label="Address" {...register('address')} error={errors.address?.message} />
          <TextField
            label="Company email domain"
            hint="Restricts new user emails to this domain. Leave blank for no restriction."
            {...register('email_domain')}
            error={errors.email_domain?.message}
          />
          <TextField
            label="Currency"
            hint="A 3-letter ISO 4217 code, e.g. KWD."
            required
            {...register('currency')}
            error={errors.currency?.message}
          />
          <TextField
            label="Timezone"
            hint="An IANA timezone name, e.g. Asia/Kuwait."
            required
            {...register('timezone')}
            error={errors.timezone?.message}
          />
          <TextField
            label="Production staff available per day"
            hint="Used by the 0–2 working-day feasibility manpower check. Leave blank if not set."
            {...register('production_staff_available_per_day')}
            error={errors.production_staff_available_per_day?.message}
          />
          <TextField
            label="Delivery scrap allowance (%)"
            hint="Delivery tolerance above the ordered quantity. Copied into each delivery when it is created; it never changes a Sales Order. 0 = none."
            inputMode="decimal"
            {...register('delivery_scrap_allowance_percent')}
            error={errors.delivery_scrap_allowance_percent?.message}
          />

          <div className="flex justify-end pt-2">
            <Button type="submit" isLoading={isSubmitting}>
              Save
            </Button>
          </div>
        </form>
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Status</FormSectionHeading>
        <Alert variant="danger">{statusError}</Alert>
        <div className="flex items-center gap-3">
          <Badge tone={organisation?.is_active ? 'success' : 'danger'}>
            {organisation?.is_active ? 'Active' : 'Inactive'}
          </Badge>
          <span className="text-sm text-gold-100/60">
            {organisation?.is_active
              ? 'Every user in this organisation can sign in.'
              : 'No user in this organisation can sign in.'}
          </span>
        </div>
        <div>
          <Button variant={organisation?.is_active ? 'danger' : 'secondary'} onClick={() => setStatusConfirmOpen(true)}>
            {organisation?.is_active ? 'Deactivate organisation' : 'Activate organisation'}
          </Button>
        </div>
      </Card>

      <ConfirmDialog
        open={statusConfirmOpen}
        title={organisation?.is_active ? 'Deactivate organisation' : 'Activate organisation'}
        message={
          organisation?.is_active
            ? 'Every user in this organisation, including you, will be signed out immediately and unable to sign back in. Reactivating requires contacting support directly -- it cannot be undone from here.'
            : 'Every user in this organisation will be able to sign in again.'
        }
        confirmLabel={organisation?.is_active ? 'Deactivate' : 'Activate'}
        danger={organisation?.is_active}
        busy={statusBusy}
        onConfirm={confirmStatusChange}
        onCancel={() => setStatusConfirmOpen(false)}
      />
    </div>
  )
}
