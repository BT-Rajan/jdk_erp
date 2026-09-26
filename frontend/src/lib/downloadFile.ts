import { apiClient } from './apiClient'

/** Downloads a stored file through GET /api/files/{id} -- the one files
 * endpoint, which applies the owning record's access rules -- and saves
 * it under its display name. Same approach as the RFQ/PO pages. Throws
 * on failure so the caller can show its own error. */
export interface StoredFile {
  id: number
  original_filename: string
}

export async function downloadFile(file: StoredFile): Promise<void> {
  const response = await apiClient.get(`/api/files/${file.id}`, { responseType: 'blob' })
  const url = window.URL.createObjectURL(response.data as Blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.original_filename
  link.click()
  window.URL.revokeObjectURL(url)
}
