import { useParams } from 'react-router-dom'

import type { ImageFilters, ImageStatus } from '../api/types'

export function useProjectId(): number {
  return Number(useParams().projectId)
}

/** Filter galeri dibaca dari URL agar bisa dibagikan & dipakai editor untuk navigasi. */
export function filtersFromParams(params: URLSearchParams): ImageFilters {
  const num = (k: string) => (params.get(k) ? Number(params.get(k)) : undefined)
  return {
    status: (params.get('status') as ImageStatus) || undefined,
    class_id: num('class_id'),
    source: params.get('source') || undefined,
    max_conf: num('max_conf'),
  }
}
