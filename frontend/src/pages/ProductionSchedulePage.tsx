import { useCallback, useEffect, useMemo, useState } from 'react'
import { AccessDeniedState } from '@/components/ui/AccessDeniedState'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { FormSectionHeading } from '@/components/ui/FormSectionHeading'
import { Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { DateField } from '@/components/forms/DateField'
import { TextField } from '@/components/forms/TextField'
import { TextareaField } from '@/components/forms/TextareaField'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate, formatNumber } from '@/lib/format'
import type { LookupOption, PaginatedResponse } from './rfqShared'

/** Mirror backend/app/api/production_schedule.py. */
export interface ScheduleEntry {
  id: number
  production_plan_id: number
  machine_id: number
  scheduled_date: string
  sequence: number
  product_id: number
  product_name: string | null
  quantity: string
  unit_of_measure_id: number
  status: 'scheduled' | 'cancelled'
  source_type: 'customer_demand' | 'independent'
  sales_order_number: string | null
  required_by_date: string | null
  late: boolean
  cancellation_reason: string | null
}

export interface MachineDay {
  machine_id: number
  machine_name: string
  capacity_quantity: string | null
  capacity_unit_of_measure_id: number
  capacity_note: string | null
  scheduled_load: string | null
  remaining_capacity: string | null
  overload_quantity: string | null
  entries: ScheduleEntry[]
}

export interface ScheduleDay {
  date: string
  is_working_day: boolean
  machines: MachineDay[]
}

export interface PlanSchedule {
  production_plan_id: number
  status: string
  unit_of_measure_id: number
  planned_quantity: string
  scheduled_quantity: string
  unscheduled_quantity: string
  fully_scheduled: boolean
  required_by_date: string | null
  entries: ScheduleEntry[]
  overloaded_dates: string[]
  exceptions: string[]
}

const qty = (value: string | null) => (value === null ? '—' : formatNumber(value, { maximumFractionDigits: 4 }))

const SCHEDULE_EXCEPTION_LABELS: Record<string, string> = {
  late: 'Late vs required-by',
  capacity_overload: 'Capacity overload',
  not_fully_scheduled: 'Not fully scheduled',
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  // The factory runs on Kuwait time.
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kuwait' }).format(new Date())
}

function useUnits() {
  const [units, setUnits] = useState<LookupOption[]>([])
  useEffect(() => {
    apiClient
      .get<PaginatedResponse<LookupOption>>('/api/units-of-measure', { params: { page_size: 200 } })
      .then((res) => setUnits(res.data.data))
      .catch(() => undefined)
  }, [])
  return useMemo(() => new Map(units.map((u) => [u.id, u.code ?? ''])), [units])
}

type EntryDialog = { kind: 'move'; entry: ScheduleEntry } | { kind: 'cancel'; entry: ScheduleEntry } | null

/** Move / change quantity / cancel one schedule entry (shared by the day
 * screen and the plan dialog). The server enforces every rule. */
function EntryActions({ dialog, onClose, onDone }: { dialog: EntryDialog; onClose: () => void; onDone: () => void }) {
  const [date, setDate] = useState('')
  const [quantity, setQuantity] = useState('')
  const [sequence, setSequence] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (dialog?.kind === 'move') {
      setDate(dialog.entry.scheduled_date)
      setQuantity(String(Number(dialog.entry.quantity)))
      setSequence(String(dialog.entry.sequence))
    }
    setReason('')
    setError(null)
  }, [dialog])

  async function submit() {
    if (!dialog) return
    setBusy(true)
    setError(null)
    try {
      if (dialog.kind === 'move') {
        const body: Record<string, unknown> = { reason: reason.trim() || null }
        if (date !== dialog.entry.scheduled_date) body.scheduled_date = date
        if (Number(quantity) !== Number(dialog.entry.quantity)) body.quantity = quantity.trim()
        if (Number(sequence) !== dialog.entry.sequence) body.sequence = Number(sequence)
        await apiClient.patch(`/api/production-schedule/${dialog.entry.id}`, body)
      } else {
        await apiClient.post(`/api/production-schedule/${dialog.entry.id}/cancel`, { reason })
      }
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={dialog !== null}
      title={dialog?.kind === 'cancel' ? 'Cancel schedule entry' : 'Reschedule'}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>Back</Button>
          <Button
            variant={dialog?.kind === 'cancel' ? 'danger' : 'primary'}
            onClick={submit}
            isLoading={busy}
            disabled={busy || (dialog?.kind === 'cancel' && !reason.trim())}
          >
            {dialog?.kind === 'cancel' ? 'Cancel Entry' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Alert variant="danger">{error}</Alert>
        {dialog?.kind === 'move' && (
          <>
            <DateField label="Production date" value={date} onChange={(e) => setDate(e.target.value)} />
            <TextField label="Quantity" type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
            <TextField label="Sequence" type="number" inputMode="numeric" value={sequence} onChange={(e) => setSequence(e.target.value)} />
            <TextareaField label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
          </>
        )}
        {dialog?.kind === 'cancel' && (
          <>
            <p className="text-sm text-gold-100/70">The Production Plan and its demand stay as they are.</p>
            <TextareaField label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />
          </>
        )}
      </div>
    </Modal>
  )
}

function EntriesTable({ entries, unit, onAction }: { entries: ScheduleEntry[]; unit: (id: number) => string; onAction?: (d: EntryDialog) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-gold-100/50">
            <th className="py-2 pr-3">Date</th>
            <th className="py-2 pr-3">#</th>
            <th className="py-2 pr-3">Product</th>
            <th className="py-2 pr-3 text-right">Quantity</th>
            <th className="py-2 pr-3">Plan</th>
            <th className="py-2 pr-3">Source</th>
            <th className="py-2 pr-3">Required By</th>
            <th className="py-2 pr-3">Status</th>
            {onAction && <th className="py-2" />}
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-t border-ink-700">
              <td className="py-2 pr-3">{formatDate(e.scheduled_date)}</td>
              <td className="py-2 pr-3">{e.sequence}</td>
              <td className="py-2 pr-3">{e.product_name ?? `Product ${e.product_id}`}</td>
              <td className="py-2 pr-3 text-right">{`${qty(e.quantity)} ${unit(e.unit_of_measure_id)}`}</td>
              <td className="py-2 pr-3">#{e.production_plan_id}</td>
              <td className="py-2 pr-3">{e.source_type === 'independent' ? 'Independent' : (e.sales_order_number ?? 'Customer demand')}</td>
              <td className="py-2 pr-3">
                {formatDate(e.required_by_date)} {e.late && e.status === 'scheduled' && <Badge tone="danger">Late</Badge>}
              </td>
              <td className="py-2 pr-3" title={e.cancellation_reason ?? undefined}>
                <Badge tone={e.status === 'scheduled' ? 'info' : 'neutral'}>{e.status === 'scheduled' ? 'Scheduled' : 'Cancelled'}</Badge>
              </td>
              {onAction && (
                <td className="py-2 text-right">
                  {e.status === 'scheduled' && (
                    <span className="flex justify-end gap-2">
                      <Button variant="secondary" onClick={() => onAction({ kind: 'move', entry: e })}>Move</Button>
                      <Button variant="danger" onClick={() => onAction({ kind: 'cancel', entry: e })}>Cancel</Button>
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Production -> Schedule (P4): what is supposed to be produced each day.
 * A schedule is a plan for production, not proof that it happened. */
export function ProductionSchedulePage() {
  const [day, setDay] = useState(todayIso())
  const [view, setView] = useState<ScheduleDay | null>(null)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<EntryDialog>(null)
  const unitsById = useUnits()
  const unit = (id: number) => unitsById.get(id) ?? ''

  const load = useCallback(() => {
    apiClient
      .get<ScheduleDay[]>('/api/production-schedule/days', { params: { start: day, end: day } })
      .then((res) => {
        setView(res.data[0] ?? null)
        setError(null)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) setDenied(true)
        else setError(err instanceof ApiError ? err.message : 'Failed to load the schedule.')
      })
  }, [day])

  useEffect(() => {
    load()
  }, [load])

  if (denied) return <AccessDeniedState message="The production schedule needs the production view permission." />

  return (
    <div className="space-y-6">
      <PageHeader title="Production Schedule" subtitle="What we are supposed to produce each day. A plan for production -- not proof that it happened." />
      <Alert variant="danger">{error}</Alert>
      <Card className="flex flex-wrap items-end gap-3 p-4 sm:p-6">
        <Button variant="secondary" onClick={() => setDay(shiftDate(day, -1))}>Previous day</Button>
        <DateField label="Production date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        <Button variant="secondary" onClick={() => setDay(shiftDate(day, 1))}>Next day</Button>
      </Card>
      {!view ? (
        <Spinner />
      ) : !view.is_working_day ? (
        <Card className="p-6 text-sm text-gold-100/70">{formatDate(view.date)} is not a working day (Friday/Saturday or a holiday).</Card>
      ) : (
        view.machines.map((m) => (
          <Card key={m.machine_id} className="space-y-3 p-4 sm:p-6">
            <FormSectionHeading>{m.machine_name}</FormSectionHeading>
            <div className="flex flex-wrap gap-6 text-sm">
              <span>
                <span className="text-gold-100/50">Capacity: </span>
                {m.capacity_quantity === null ? 'Not configured' : `${qty(m.capacity_quantity)} ${unit(m.capacity_unit_of_measure_id)}`}
              </span>
              <span>
                <span className="text-gold-100/50">Scheduled: </span>
                {m.scheduled_load === null ? '—' : `${qty(m.scheduled_load)} ${unit(m.capacity_unit_of_measure_id)}`}
              </span>
              <span>
                <span className="text-gold-100/50">Remaining: </span>
                {m.remaining_capacity === null ? '—' : `${qty(m.remaining_capacity)} ${unit(m.capacity_unit_of_measure_id)}`}
              </span>
              {m.overload_quantity !== null && Number(m.overload_quantity) > 0 && (
                <Badge tone="danger">{`Overloaded by ${qty(m.overload_quantity)} ${unit(m.capacity_unit_of_measure_id)}`}</Badge>
              )}
            </div>
            {m.capacity_note && <p className="text-xs text-gold-100/50">{m.capacity_note}</p>}
            {m.entries.length === 0 ? (
              <p className="text-sm text-gold-100/60">Nothing scheduled.</p>
            ) : (
              <EntriesTable entries={m.entries} unit={unit} onAction={setDialog} />
            )}
          </Card>
        ))
      )}
      <EntryActions
        dialog={dialog}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null)
          load()
        }}
      />
    </div>
  )
}

/** The schedule of one Production Plan: planned / scheduled / unscheduled,
 * its entries and exceptions, and scheduling more of it. */
export function PlanScheduleDialog({ planId, onClose }: { planId: number | null; onClose: () => void }) {
  const [view, setView] = useState<PlanSchedule | null>(null)
  const [date, setDate] = useState('')
  const [quantity, setQuantity] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dialog, setDialog] = useState<EntryDialog>(null)
  const unitsById = useUnits()
  const unit = (id: number) => unitsById.get(id) ?? ''

  const load = useCallback(() => {
    if (planId === null) return
    apiClient
      .get<PlanSchedule>(`/api/production-plans/${planId}/schedule`)
      .then((res) => setView(res.data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load the plan schedule.'))
  }, [planId])

  useEffect(() => {
    setView(null)
    setError(null)
    setDate('')
    setQuantity('')
    load()
  }, [load])

  async function schedule() {
    setBusy(true)
    setError(null)
    try {
      await apiClient.post('/api/production-schedule', { production_plan_id: planId, scheduled_date: date, quantity: quantity.trim() })
      setQuantity('')
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={planId !== null} title={`Schedule of plan #${planId ?? ''}`} onClose={onClose} size="wide" footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <div className="space-y-4">
        <Alert variant="danger">{error}</Alert>
        {!view ? (
          <Spinner />
        ) : (
          <>
            <div className="flex flex-wrap gap-6 text-sm">
              <span><span className="text-gold-100/50">Planned: </span>{`${qty(view.planned_quantity)} ${unit(view.unit_of_measure_id)}`}</span>
              <span><span className="text-gold-100/50">Scheduled: </span>{`${qty(view.scheduled_quantity)} ${unit(view.unit_of_measure_id)}`}</span>
              <span><span className="text-gold-100/50">Unscheduled: </span>{`${qty(view.unscheduled_quantity)} ${unit(view.unit_of_measure_id)}`}</span>
              <span><span className="text-gold-100/50">Required by: </span>{formatDate(view.required_by_date)}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {view.exceptions.map((e) => (
                <Badge key={e} tone={e === 'not_fully_scheduled' ? 'warning' : 'danger'}>
                  {SCHEDULE_EXCEPTION_LABELS[e] ?? e}
                </Badge>
              ))}
              {view.overloaded_dates.length > 0 && (
                <span className="text-xs text-gold-100/60">Overloaded: {view.overloaded_dates.map((d) => formatDate(d)).join(', ')}</span>
              )}
            </div>
            {view.entries.length > 0 && <EntriesTable entries={view.entries} unit={unit} onAction={setDialog} />}
            {view.status === 'planned' && !view.fully_scheduled && (
              <div className="flex flex-wrap items-end gap-3">
                <DateField label="Production date" value={date} onChange={(e) => setDate(e.target.value)} />
                <TextField label="Quantity" type="number" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
                <Button onClick={schedule} isLoading={busy} disabled={busy || !date || !quantity.trim()}>Schedule</Button>
              </div>
            )}
          </>
        )}
      </div>
      <EntryActions
        dialog={dialog}
        onClose={() => setDialog(null)}
        onDone={() => {
          setDialog(null)
          load()
        }}
      />
    </Modal>
  )
}
