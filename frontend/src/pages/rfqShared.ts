/** Types and small helpers shared by the RFQ list page (RfqsPage.tsx)
 * and the RFQ form page (RfqFormPage.tsx). */

/** Mirrors backend/app/schemas/rfq.py's RfqOut. */
export interface RfqFile {
  id: number
  original_filename: string
  mime_type: string
  size_bytes: number
}

export interface RfqResponseLine {
  id: number
  rfq_line_id: number
  unit_price: string
  /** null -> quoted at the RFQ line's own requested quantity. */
  quantity: string | null
  delivery_days: number | null
  remarks: string | null
}

export interface RfqResponse {
  id: number
  invitation_id: number
  response_received_at: string
  supplier_quotation_number: string | null
  quotation_date: string | null
  valid_until: string | null
  payment_terms: string | null
  delivery_terms: string | null
  freight_terms: string | null
  note: string | null
  created_by_user_id: number | null
  lines: RfqResponseLine[]
  files: RfqFile[]
}

export interface RfqInvitationFollowUp {
  id: number
  note: string
  created_by_user_id: number | null
  created_at: string
}

export interface RfqInvitation {
  id: number
  supplier_id: number
  status: 'sent' | 'quoted' | 'declined'
  invited_at: string
  last_emailed_at: string | null
  pdf_file: RfqFile | null
  /** Every revision's PDF, oldest to newest -- none are ever deleted. */
  pdf_files: RfqFile[]
  responses: RfqResponse[]
  follow_ups: RfqInvitationFollowUp[]
}

export interface RfqLine {
  id: number
  raw_material_id: number
  quantity: string
  unit_of_measure_id: number
  required_by_date: string | null
  remarks: string | null
}

export interface Rfq {
  id: number
  organisation_id: number
  rfq_number: string
  status: 'draft' | 'issued' | 'response_received' | 'selected' | 'rejected' | 'cancelled' | 'converted'
  revision_number: number
  priority: 'normal' | 'urgent'
  rfq_date: string
  required_delivery_date: string | null
  requested_by_user_id: number | null
  requested_by_name: string | null
  notes: string | null
  cancel_reason: string | null
  decided_by_user_id: number | null
  decided_at: string | null
  decision_note: string | null
  selected_response_id: number | null
  purchase_order_id: number | null
  lines: RfqLine[]
  invitations: RfqInvitation[]
  acceptance_files: RfqFile[]
}

export interface LookupOption {
  id: number
  name: string
  code: string | null
  is_active: boolean
}

export interface MaterialOption extends LookupOption {
  unit_of_measure_id: number
}

export interface PaginatedResponse<T> {
  data: T[]
  pagination: { page: number; page_size: number; total: number; total_pages: number }
}

const DECIMAL_RE = /^\d+(\.\d+)?$/

export function isPositiveDecimal(value: string): boolean {
  return DECIMAL_RE.test(value) && Number(value) > 0
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}
