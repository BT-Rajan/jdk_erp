import { useEffect, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { TextField } from '@/components/forms/TextField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

/** Mirrors backend/app/schemas/working_calendar.py. */
interface Holiday {
  id: number
  holiday_date: string
  description: string
}

interface WorkingCalendar {
  working_days: string[]
  timezone: string
  same_day_cutoff_time: string
  holidays: Holiday[]
}

const BASE_URL = '/api/organisations/me/working-calendar'

function capitalise(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** Admin Setup -> Working calendar: the organisation's one working
 * calendar used for Sales delivery-window decisions
 * (backend/app/services/working_calendar_service.py). The working week
 * and Kuwait time are fixed business rules shown for reference; the
 * same-day cut-off and holidays are Admin-configured. Server-side
 * require_admin is the real boundary; AccessDeniedState is a courtesy. */
export function WorkingCalendarSettingsPage() {
  const { user } = useAuth()
  const isAdmin = isAdminRole(user?.role)

  const [calendar, setCalendar] = useState<WorkingCalendar | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [cutoff, setCutoff] = useState('')
  const [cutoffError, setCutoffError] = useState<string | null>(null)
  const [cutoffSaved, setCutoffSaved] = useState<string | null>(null)
  const [savingCutoff, setSavingCutoff] = useState(false)

  const [holidayDate, setHolidayDate] = useState('')
  const [holidayDescription, setHolidayDescription] = useState('')
  const [holidayError, setHolidayError] = useState<string | null>(null)
  const [holidayBusy, setHolidayBusy] = useState(false)

  function apply(data: WorkingCalendar) {
    setCalendar(data)
    setCutoff(data.same_day_cutoff_time.slice(0, 5))
  }

  function reload() {
    return apiClient.get<WorkingCalendar>(BASE_URL).then(({ data }) => apply(data))
  }

  useEffect(() => {
    if (!isAdmin) return
    reload().catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Failed to load the working calendar.'))
  }, [isAdmin])

  async function saveCutoff() {
    if (!/^\d{2}:\d{2}$/.test(cutoff)) {
      setCutoffError('Enter a valid time, e.g. 14:00.')
      return
    }
    setSavingCutoff(true)
    setCutoffError(null)
    setCutoffSaved(null)
    try {
      const { data } = await apiClient.put<WorkingCalendar>(`${BASE_URL}/cutoff`, { same_day_cutoff_time: cutoff })
      apply(data)
      setCutoffSaved('Saved.')
    } catch (err) {
      setCutoffError(err instanceof ApiError ? err.message : 'Failed to save the cut-off time.')
    } finally {
      setSavingCutoff(false)
    }
  }

  async function addHoliday() {
    if (!holidayDate || !holidayDescription.trim()) {
      setHolidayError('Enter a date and a description.')
      return
    }
    setHolidayBusy(true)
    setHolidayError(null)
    try {
      await apiClient.post(`${BASE_URL}/holidays`, { holiday_date: holidayDate, description: holidayDescription.trim() })
      setHolidayDate('')
      setHolidayDescription('')
      await reload()
    } catch (err) {
      setHolidayError(err instanceof ApiError ? err.message : 'Failed to add the holiday.')
    } finally {
      setHolidayBusy(false)
    }
  }

  async function removeHoliday(holiday: Holiday) {
    setHolidayBusy(true)
    setHolidayError(null)
    try {
      await apiClient.delete(`${BASE_URL}/holidays/${holiday.id}`)
      await reload()
    } catch (err) {
      setHolidayError(err instanceof ApiError ? err.message : 'Failed to remove the holiday.')
    } finally {
      setHolidayBusy(false)
    }
  }

  if (!isAdmin) return <AccessDeniedState />

  return (
    <div className="space-y-6">
      <PageHeader title="Working calendar" subtitle="Working days, holidays and the same-day cut-off used for Sales delivery dates." />
      <Alert variant="danger">{loadError}</Alert>

      {!calendar && !loadError ? (
        <Spinner />
      ) : calendar ? (
        <>
          <Card className="space-y-3 p-6">
            <FormSectionHeading>Working week</FormSectionHeading>
            <p className="text-sm text-gold-100/60">
              {calendar.working_days.map(capitalise).join(', ')}. Friday and Saturday are non-working. All times are{' '}
              {calendar.timezone} time.
            </p>
          </Card>

          <Card className="space-y-4 p-6">
            <FormSectionHeading>Same-day cut-off</FormSectionHeading>
            <Alert variant="danger">{cutoffError}</Alert>
            <Alert variant="success">{cutoffSaved}</Alert>
            <TextField
              label="Cut-off time"
              type="time"
              hint="A same-day delivery request is accepted up to this time (Kuwait time)."
              required
              value={cutoff}
              onChange={(event) => setCutoff(event.target.value)}
            />
            <div className="flex justify-end">
              <Button onClick={saveCutoff} isLoading={savingCutoff}>
                Save cut-off
              </Button>
            </div>
          </Card>

          <Card className="space-y-4 p-6">
            <FormSectionHeading>Holidays</FormSectionHeading>
            <Alert variant="danger">{holidayError}</Alert>
            {calendar.holidays.length === 0 ? (
              <EmptyState title="No holidays" message="Add the organisation's non-working dates below." />
            ) : (
              <ul className="divide-y divide-gold-100/10">
                {calendar.holidays.map((holiday) => (
                  <li key={holiday.id} className="flex items-center justify-between py-2 text-sm">
                    <span>
                      {holiday.holiday_date} — {holiday.description}
                    </span>
                    <Button variant="secondary" onClick={() => removeHoliday(holiday)} disabled={holidayBusy}>
                      Remove
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <DateField label="Date" required value={holidayDate} onChange={(event) => setHolidayDate(event.target.value)} />
              <TextField
                label="Description"
                required
                maxLength={120}
                value={holidayDescription}
                onChange={(event) => setHolidayDescription(event.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={addHoliday} isLoading={holidayBusy}>
                Add holiday
              </Button>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
