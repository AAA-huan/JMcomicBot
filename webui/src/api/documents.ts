import { apiRequest } from './client'

export interface DocumentEntry {
  path: string
  title: string
}

export function listDocuments(): Promise<DocumentEntry[]> {
  return apiRequest('/documents')
}

export function getDocument(path: string): Promise<{ path: string; content: string }> {
  return apiRequest(`/documents/${path.split('/').map(encodeURIComponent).join('/')}`)
}
