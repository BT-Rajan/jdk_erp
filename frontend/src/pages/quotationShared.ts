/** Types and display labels shared by the quotation list, detail and form
 * pages. Every status, window and reason shown comes from the server
 * (backend/app/services/quotation_readiness_service.py) -- these maps only
 * turn its codes into words; nothing here derives a state. */

import type { BadgeTone } from '@/components/ui/Badge'

export interface QuotationLine {
  id: number
  line_number: number
  product_id: number
  quantity: string
  unit_of_measure_id: number
  unit_price: string
  line_amount: string
  min_selling_price: string | null
  max_selling_price: string | null
  price_approval_required: boolean
}

/** Mirrors backend/app/schemas/quotation.py's QuotationListRowOut. */
export interface Quotation {
  id: number
  quotation_number: string
  customer_id: number
  customer_name: string | null
  created_by_user_id: number | null
  created_by_name: string | null
  quotation_date: string
  requested_delivery_date: string | null
  status: string
  currency: string
  subtotal_amount: string
  total_amount: string
  price_approval_required: boolean
  price_decision: string | null
  price_decision_reason: string | null
  price_decision_at: string | null
  delivery_window: string | null
  readiness_status: string | null
  /** Server's answer: only the salesman owning the customer may edit a draft. */
  can_edit: boolean
  valid_until: string
  accepted_at: string | null
  rejected_at: string | null
  rejection_reason: string | null
  /** All computed on the server for the current user (S12). */
  is_expired: boolean
  order_eligible: boolean
  can_accept: boolean
  can_reject: boolean
  can_renew: boolean
  can_convert: boolean
  sales_order_id: number | null
  created_at: string
  updated_at: string
  lines: QuotationLine[]
}

export interface Readiness {
  status: string
  delivery_window: string | null
  conditions: string[]
  reason_codes: string[]
  feasibility_check_id: number | null
  feasibility_state: string | null
  commercial_approval_required: boolean
}

export interface FeasibilityCheck {
  id: number
  delivery_window: string
  result: string
  failed_stage: string | null
  reason_codes: string[]
  state: string
  calculated_at: string
  created_by_user_id: number | null
  decision_reason: string | null
  decided_at: string | null
  is_current: boolean
}

export const WINDOW_LABELS: Record<string, string> = {
  same_day: 'Same day',
  within_2_working_days: 'Within 2 working days',
  more_than_2_working_days: 'More than 2 working days',
  not_servable: 'Non-working date',
}

export const READINESS_LABELS: Record<string, string> = {
  ready: 'Ready',
  operational_assessment_required: 'Feasibility required',
  admin_override_required: 'Admin decision required',
  commercial_approval_required: 'Price approval required',
  not_servable: 'Not servable',
}

export const READINESS_TONES: Record<string, BadgeTone> = {
  ready: 'success',
  operational_assessment_required: 'warning',
  admin_override_required: 'warning',
  commercial_approval_required: 'warning',
  not_servable: 'danger',
}

export const REASON_LABELS: Record<string, string> = {
  requested_date_missing: 'No requested delivery date -- edit the quotation to add one.',
  requested_date_passed: 'The requested delivery date has passed -- edit the quotation to change it.',
  requested_date_non_working: 'The requested date is a non-working day -- an Admin decision is required on the feasibility check.',
  feasibility_required: 'Feasibility has not been checked yet.',
  feasibility_stale: 'The quotation changed since the last feasibility check -- run it again.',
  feasibility_rejected: 'Admin rejected the feasibility exception.',
  fg_insufficient: 'Not enough finished goods in stock.',
  bom_missing: 'A product has no active bill of materials.',
  raw_material_shortage: 'Not enough raw materials in stock.',
  lead_time_not_set: 'A product has no manufacturing lead time set.',
  lead_time_exceeds_window: 'Production lead time is longer than the time available.',
  manpower_not_configured: 'Production staff figures are not set.',
  manpower_insufficient: 'Not enough production staff available.',
  price_outside_range: 'A price is outside the permitted range -- price approval required.',
  price_range_not_set: 'A product has no permitted price range -- price approval required.',
  price_approval_rejected: 'Admin rejected the quoted prices.',
}

export function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? code
}

export const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  accepted: 'Accepted',
  rejected: 'Rejected',
  converted: 'Converted',
}

export const STATUS_TONES: Record<string, BadgeTone> = {
  draft: 'neutral',
  accepted: 'success',
  rejected: 'danger',
  converted: 'info',
}

/** Mirrors backend/app/schemas/sales_order.py's SalesOrderOut. */
export interface SalesOrderLine {
  id: number
  line_number: number
  product_id: number
  quantity: string
  unit_of_measure_id: number
  unit_price: string
  line_amount: string
}

export interface SalesOrder {
  id: number
  order_number: string
  quotation_id: number
  quotation_number: string | null
  customer_id: number
  customer_name: string | null
  order_date: string
  requested_delivery_date: string | null
  currency: string
  subtotal_amount: string
  total_amount: string
  status: string
  cancellation_reason: string | null
  cancelled_at: string | null
  /** Set automatically when the order is created (S14.2). */
  handed_off_at: string | null
  handoff_source: string | null
  updated_at: string
  lines: SalesOrderLine[]
  /** Server's answer for the current user. */
  can_cancel: boolean
  can_edit: boolean
}

export const ORDER_STATUS_LABELS: Record<string, string> = { handed_off: 'Handed off', cancelled: 'Cancelled' }
export const ORDER_STATUS_TONES: Record<string, BadgeTone> = { handed_off: 'success', cancelled: 'danger' }

export const HANDOFF_SOURCE_LABELS: Record<string, string> = {
  automatic: 'automatically on creation',
  migration: 'on upgrade (existing order)',
}
