import { useEffect, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { CheckboxField } from '@/components/forms/CheckboxField'
import { NumberField } from '@/components/forms/NumberField'
import { SelectField } from '@/components/forms/SelectField'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

/** Mirrors backend/app/schemas/email_account.py's EmailAccountOut. */
interface EmailAccount {
  provider: string
  email_address: string
  display_name: string
  username: string
  has_password: boolean
  incoming_protocol: 'imap' | 'pop3'
  imap_host: string
  imap_port: number
  imap_use_ssl: boolean
  pop3_host: string
  pop3_port: number
  pop3_use_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_use_tls: boolean
  is_active: boolean
  last_tested_at: string | null
  last_test_ok: boolean | null
  last_test_error: string | null
}

/** Mirrors email_account_service.PROVIDER_PRESETS. */
interface ProviderPreset {
  label: string
  imap_host: string
  imap_port: number
  imap_use_ssl: boolean
  pop3_host: string
  pop3_port: number
  pop3_use_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_use_tls: boolean
  note: string
}

const schema = z.object({
  provider: z.string().min(1),
  email_address: z
    .string()
    .refine((value) => value === '' || z.string().email().safeParse(value).success, 'Enter a valid email address'),
  display_name: z.string(),
  username: z.string(),
  password: z.string(),
  clear_password: z.boolean(),
  incoming_protocol: z.enum(['imap', 'pop3']),
  imap_host: z.string(),
  imap_port: z.coerce.number().int().min(1).max(65535),
  imap_use_ssl: z.boolean(),
  pop3_host: z.string(),
  pop3_port: z.coerce.number().int().min(1).max(65535),
  pop3_use_ssl: z.boolean(),
  smtp_host: z.string(),
  smtp_port: z.coerce.number().int().min(1).max(65535),
  smtp_use_tls: z.boolean(),
  is_active: z.boolean(),
})

type FormInput = z.input<typeof schema>
type FormOutput = z.output<typeof schema>

const emptyDefaults: FormInput = {
  provider: 'gmail',
  email_address: '',
  display_name: '',
  username: '',
  password: '',
  clear_password: false,
  incoming_protocol: 'imap',
  imap_host: 'imap.gmail.com',
  imap_port: 993,
  imap_use_ssl: true,
  pop3_host: 'pop.gmail.com',
  pop3_port: 995,
  pop3_use_ssl: true,
  smtp_host: 'smtp.gmail.com',
  smtp_port: 587,
  smtp_use_tls: true,
  is_active: true,
}

function toFormValues(account: EmailAccount): FormInput {
  return { ...account, password: '', clear_password: false }
}

/** Admin-only Communication -> Email settings: the one mailbox this
 * organisation sends and tests through (backend/app/api/communication.py,
 * ported from jdk_clean's single shared account into jdk_erp's
 * per-organisation model). Server-side is the real boundary
 * (Principle 3); AccessDeniedState below is a usability courtesy for a
 * non-admin who lands on this route directly. */
export function EmailSettingsPage() {
  const { user: currentUser } = useAuth()
  const canManage = isAdminRole(currentUser?.role)

  const [presets, setPresets] = useState<Record<string, ProviderPreset>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | undefined>(undefined)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [hasPassword, setHasPassword] = useState(false)

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  const [sendTestOpen, setSendTestOpen] = useState(false)
  const [sendTestTo, setSendTestTo] = useState('')
  const [sending, setSending] = useState(false)
  const [sendResult, setSendResult] = useState<{ ok: boolean; message: string } | null>(null)

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    setError: setFieldError,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormInput, unknown, FormOutput>({ resolver: zodResolver(schema), defaultValues: emptyDefaults })

  const protocol = watch('incoming_protocol')
  const clearPassword = watch('clear_password')

  useEffect(() => {
    if (!canManage) return
    let cancelled = false
    setLoading(true)
    setLoadError(undefined)
    Promise.all([
      apiClient.get<EmailAccount>('/api/communication/email'),
      apiClient.get<Record<string, ProviderPreset>>('/api/communication/email/providers'),
    ])
      .then(([accountRes, presetsRes]) => {
        if (cancelled) return
        reset(toFormValues(accountRes.data))
        setHasPassword(accountRes.data.has_password)
        setPresets(presetsRes.data)
        setTestResult(
          accountRes.data.last_tested_at
            ? { ok: !!accountRes.data.last_test_ok, message: accountRes.data.last_test_error ?? 'Connected successfully (incoming and outgoing).' }
            : null,
        )
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setLoadError(err instanceof ApiError ? err.message : 'Failed to load email settings.')
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
        <PageHeader title="Email" />
        <AccessDeniedState message="Only an organisation admin can manage email settings." />
      </div>
    )
  }

  function applyPreset(providerId: string) {
    const preset = presets[providerId]
    if (!preset) return
    setValue('imap_host', preset.imap_host)
    setValue('imap_port', preset.imap_port)
    setValue('imap_use_ssl', preset.imap_use_ssl)
    setValue('pop3_host', preset.pop3_host)
    setValue('pop3_port', preset.pop3_port)
    setValue('pop3_use_ssl', preset.pop3_use_ssl)
    setValue('smtp_host', preset.smtp_host)
    setValue('smtp_port', preset.smtp_port)
    setValue('smtp_use_tls', preset.smtp_use_tls)
  }

  async function onSubmit(values: FormOutput) {
    setSaveError(null)
    setTestResult(null)
    // "" (clear) and omitted (keep unchanged) are different things to
    // the backend (backend/app/schemas/email_account.py's
    // EmailAccountUpdateRequest.password) -- a plain text input can't
    // represent "no key at all" on its own, so `clear_password` is the
    // explicit opt-in for that case; leaving the field blank otherwise
    // keeps whatever password is already saved.
    const { password, clear_password: shouldClear, ...rest } = values
    const payload: Record<string, unknown> = { ...rest }
    if (shouldClear) payload.password = ''
    else if (password) payload.password = password

    try {
      const { data } = await apiClient.put<EmailAccount>('/api/communication/email', payload)
      reset(toFormValues(data))
      setHasPassword(data.has_password)
    } catch (err) {
      if (!(err instanceof ApiError)) {
        setSaveError('Something went wrong. Please try again.')
      } else if (err.fields) {
        // A whole-form error (e.g. the IMAP-port/SSL mismatch check)
        // carries no real field name -- the backend's generic validation
        // handler reports it under "_" (backend/app/core/error_handlers.py),
        // so it surfaces as the form-level alert instead of a
        // non-existent field's error.
        for (const [field, message] of Object.entries(err.fields)) {
          if (field in emptyDefaults) setFieldError(field as keyof FormInput, { message })
          else setSaveError(message)
        }
      } else {
        setSaveError(err.message)
      }
    }
  }

  async function handleTestConnection() {
    setTesting(true)
    setTestResult(null)
    try {
      const { data } = await apiClient.post<{ ok: boolean; message: string }>('/api/communication/email/test')
      setTestResult(data)
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof ApiError ? err.message : 'Failed to test connection.' })
    } finally {
      setTesting(false)
    }
  }

  async function handleSendTest() {
    setSending(true)
    setSendResult(null)
    try {
      const { data } = await apiClient.post<{ ok: boolean; message: string }>('/api/communication/email/send-test', {
        to_email: sendTestTo,
      })
      setSendResult(data)
    } catch (err) {
      setSendResult({ ok: false, message: err instanceof ApiError ? err.message : 'Failed to send test email.' })
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Email" />
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Email" subtitle="Configure the mailbox JDK ERP tests connections and sends mail through." />

      <Alert variant="danger">{loadError}</Alert>

      <Card className="p-6">
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <Alert variant="danger">{saveError}</Alert>

          <FormSectionHeading>Mailbox</FormSectionHeading>
          <SelectField
            label="Provider"
            {...register('provider', { onChange: (event) => applyPreset(event.target.value) })}
            error={errors.provider?.message}
          >
            {Object.entries(presets).map(([id, preset]) => (
              <option key={id} value={id}>
                {preset.label}
              </option>
            ))}
          </SelectField>
          <TextField label="Email address" type="email" {...register('email_address')} error={errors.email_address?.message} />
          <TextField label="Display name" hint="Shown as the sender name on outgoing mail." {...register('display_name')} error={errors.display_name?.message} />
          <TextField label="Username" hint="Leave blank to use the email address." {...register('username')} error={errors.username?.message} />
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            hint={hasPassword ? 'Leave blank to keep the currently saved password.' : undefined}
            disabled={clearPassword}
            {...register('password')}
            error={errors.password?.message}
          />
          {hasPassword && (
            <CheckboxField label="Clear the saved password" {...register('clear_password')} />
          )}
          <CheckboxField label="Active" hint="Turn off to stop this mailbox from being used, without losing its settings." {...register('is_active')} />

          <FormSectionHeading>Incoming mail</FormSectionHeading>
          <SelectField label="Protocol" {...register('incoming_protocol')} error={errors.incoming_protocol?.message}>
            <option value="imap">IMAP</option>
            <option value="pop3">POP3</option>
          </SelectField>
          {protocol === 'imap' ? (
            <>
              <TextField label="IMAP host" {...register('imap_host')} error={errors.imap_host?.message} />
              <NumberField label="IMAP port" {...register('imap_port')} error={errors.imap_port?.message} />
              <CheckboxField label="Use SSL/TLS" {...register('imap_use_ssl')} />
            </>
          ) : (
            <>
              <TextField label="POP3 host" {...register('pop3_host')} error={errors.pop3_host?.message} />
              <NumberField label="POP3 port" {...register('pop3_port')} error={errors.pop3_port?.message} />
              <CheckboxField label="Use SSL/TLS" {...register('pop3_use_ssl')} />
            </>
          )}

          <FormSectionHeading>Outgoing mail (SMTP)</FormSectionHeading>
          <TextField label="SMTP host" {...register('smtp_host')} error={errors.smtp_host?.message} />
          <NumberField label="SMTP port" {...register('smtp_port')} error={errors.smtp_port?.message} />
          <CheckboxField label="Use STARTTLS" {...register('smtp_use_tls')} />

          <div className="flex justify-end pt-2">
            <Button type="submit" isLoading={isSubmitting}>
              Save
            </Button>
          </div>
        </form>
      </Card>

      <Card className="space-y-3 p-6">
        <FormSectionHeading>Test connection</FormSectionHeading>
        <p className="text-sm text-gold-100/60">
          Opens a real connection with the saved settings and closes it again -- checks the credentials without
          sending anything.
        </p>
        <Alert variant={testResult?.ok ? 'success' : 'danger'}>{testResult?.message}</Alert>
        <div>
          <Button variant="secondary" onClick={handleTestConnection} isLoading={testing}>
            Test connection
          </Button>
        </div>

        <FormSectionHeading>Send test email</FormSectionHeading>
        <p className="text-sm text-gold-100/60">
          Actually sends a real email through this mailbox -- proves the whole pipeline works, not just that the
          credentials open a socket.
        </p>
        <Alert variant={sendResult?.ok ? 'success' : 'danger'}>{sendResult?.message}</Alert>
        {sendTestOpen ? (
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-64 flex-1">
              <TextField
                label="Send to"
                type="email"
                value={sendTestTo}
                onChange={(event) => setSendTestTo(event.target.value)}
              />
            </div>
            <Button onClick={handleSendTest} isLoading={sending} disabled={!sendTestTo}>
              Send
            </Button>
            <Button variant="ghost" onClick={() => setSendTestOpen(false)} disabled={sending}>
              Cancel
            </Button>
          </div>
        ) : (
          <div>
            <Button variant="secondary" onClick={() => setSendTestOpen(true)}>
              Send test email
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}
