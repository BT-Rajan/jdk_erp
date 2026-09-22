import { useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate, type Location } from 'react-router-dom'
import { z } from 'zod'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
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
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <Card className="w-full max-w-sm space-y-6 p-8">
        <div className="space-y-1 text-center">
          <p className="font-display text-2xl text-gold-400">JDK ERP</p>
          <p className="text-sm text-gold-100/60">Sign in to your workspace</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <Alert variant="danger">{formError}</Alert>
          <TextField
            label="Username"
            autoComplete="username"
            required
            {...register('username')}
            error={errors.username?.message}
          />
          <TextField
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            {...register('password')}
            error={errors.password?.message}
          />
          <Button type="submit" className="w-full" isLoading={isSubmitting}>
            Sign in
          </Button>
        </form>
      </Card>
    </div>
  )
}
