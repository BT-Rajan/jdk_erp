/** Mirrors backend/app/schemas/auth.py and schemas/user.py -- the one
 * client-side shape for what those endpoints return, so a field rename
 * on the backend surfaces here as a type error instead of a silent
 * `undefined` at runtime. */

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

/** The public-safe user shape (backend/app/schemas/user.py's UserOut)
 * -- never includes a password or anything else backend/app/models/user.py
 * doesn't already treat as safe to return to the client itself. */
export interface User {
  id: number
  organisation_id: number
  full_name: string
  email: string
  username: string
  is_active: boolean
  last_login_at: string | null
  role: string
  team_ids: number[]
}
