import { useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate, type Location } from 'react-router-dom'
import { z } from 'zod'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { PasswordField } from '@/components/forms/PasswordField'
import { TextField } from '@/components/forms/TextField'
import { ApiError } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'

const schema = z.object({
  username: z.string().min(1, 'Username is required'),
  password: z.string().min(1, 'Password is required'),
})

type FormValues = z.infer<typeof schema>

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const redirectTo = (location.state as { from?: Location } | null)?.from?.pathname ?? '/'

  async function onSubmit(values: FormValues) {
    setFormError(null)
    try {
      await login(values.username, values.password)
      navigate(redirectTo, { replace: true })
    } catch (error) {
      // One message for bad username, bad password and an inactive
      // account alike (backend/app/services/auth_service.py's
      // GENERIC_LOGIN_ERROR) -- the UI surfaces it verbatim rather than
      // re-introducing the username-enumeration gap the backend
      // specifically closed (docs/audit/AUTHENTICATION_AUDIT.md #3).
      setFormError(error instanceof ApiError ? error.message : 'Something went wrong. Please try again.')
    }
  }

  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to your workspace">
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <Alert variant="danger">{formError}</Alert>

        <div className="flex flex-col gap-5">
          <TextField
            label="Username"
            autoComplete="username"
            autoFocus
            required
            disabled={isSubmitting}
            aria-invalid={Boolean(formError) || undefined}
            {...register('username')}
            error={errors.username?.message}
          />

          <PasswordField
            label="Password"
            autoComplete="current-password"
            required
            disabled={isSubmitting}
            aria-invalid={Boolean(formError) || undefined}
            {...register('password')}
            error={errors.password?.message}
          />
        </div>

        <Button type="submit" variant="gradient" className="mt-8 w-full" isLoading={isSubmitting}>
          Sign in
        </Button>

        <p className="mt-5 text-center text-xs text-gold-100/40">
          Forgotten your password? Contact your admin to have it reset.
        </p>
      </form>
    </AuthLayout>
  )
}
