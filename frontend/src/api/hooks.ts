import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, json, queryString } from './client'
import type {
  Exemplar,
  Health,
  ImageDetail,
  ImageItem,
  ImagePage,
  ImageFilters,
  Job,
  JobItem,
  LabelClass,
  Project,
  ProjectStats,
  ProviderInfo,
  UploadResult,
} from './types'

export const keys = {
  projects: ['projects'] as const,
  project: (id: number) => ['projects', id] as const,
  stats: (id: number) => ['projects', id, 'stats'] as const,
  classes: (id: number) => ['projects', id, 'classes'] as const,
  images: (id: number) => ['projects', id, 'images'] as const,
  jobs: (id: number) => ['projects', id, 'jobs'] as const,
  jobItems: (jobId: number) => ['jobs', jobId, 'items'] as const,
}

// --- projects --------------------------------------------------------------

export const useProjects = () =>
  useQuery({ queryKey: keys.projects, queryFn: () => api<Project[]>('/projects') })

export const useProject = (id: number) =>
  useQuery({ queryKey: keys.project(id), queryFn: () => api<Project>(`/projects/${id}`) })

export const useProjectStats = (id: number) =>
  useQuery({ queryKey: keys.stats(id), queryFn: () => api<ProjectStats>(`/projects/${id}/stats`) })

export function useSaveProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id?: number; name: string; description: string | null }) =>
      id
        ? api<Project>(`/projects/${id}`, json('PATCH', body))
        : api<Project>('/projects', json('POST', body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/projects/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  })
}

// --- classes ---------------------------------------------------------------

export const useClasses = (projectId: number) =>
  useQuery({
    queryKey: keys.classes(projectId),
    queryFn: () => api<LabelClass[]>(`/projects/${projectId}/classes`),
  })

/** Invalidate semua data project (class, statistik, galeri) setelah perubahan. */
function useInvalidateProject(projectId: number) {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: keys.project(projectId) })
}

export function useCreateClass(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: (body: { name: string; color?: string; text_prompt?: string | null }) =>
      api<LabelClass>(`/projects/${projectId}/classes`, json('POST', body)),
    onSuccess: invalidate,
  })
}

export function useUpdateClass(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; color?: string; text_prompt?: string | null }) =>
      api<LabelClass>(`/classes/${id}`, json('PATCH', body)),
    onSuccess: invalidate,
  })
}

export function useDeleteClass(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: (id: number) => api<void>(`/classes/${id}`, { method: 'DELETE' }),
    onSuccess: invalidate,
  })
}

export function useReorderClasses(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: (classIds: number[]) =>
      api<LabelClass[]>(`/projects/${projectId}/classes/order`, json('PUT', { class_ids: classIds })),
    onSuccess: invalidate,
  })
}

// --- images ----------------------------------------------------------------

export const useImages = (projectId: number, filters: ImageFilters, page: number, pageSize = 60) =>
  useQuery({
    queryKey: [...keys.images(projectId), filters, page, pageSize],
    queryFn: () =>
      api<ImagePage>(
        `/projects/${projectId}/images${queryString({ ...filters, page, page_size: pageSize })}`,
      ),
    placeholderData: keepPreviousData,
  })

export function useUploadImages(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: (files: File[]) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f, f.name))
      return api<UploadResult>(`/projects/${projectId}/images`, { method: 'POST', body: form })
    },
    onSettled: invalidate,
  })
}

export function useDeleteImages(projectId: number) {
  const invalidate = useInvalidateProject(projectId)
  return useMutation({
    mutationFn: (imageIds: number[]) =>
      api<{ deleted: number }>(`/projects/${projectId}/images/bulk-delete`, json('POST', { image_ids: imageIds })),
    onSuccess: invalidate,
  })
}

// --- providers & jobs -------------------------------------------------------

export const useProviders = () =>
  useQuery({ queryKey: ['providers'], queryFn: () => api<ProviderInfo[]>('/providers'), staleTime: 60_000 })

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health'), refetchInterval: 15_000 })

const isActive = (j: Job) => j.status === 'queued' || j.status === 'running'

export function useJobs(projectId: number) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: keys.jobs(projectId),
    queryFn: async () => {
      const jobs = await api<Job[]>(`/projects/${projectId}/jobs`)
      // Selama ada job berjalan, galeri & statistik ikut diperbarui.
      if (jobs.some(isActive)) {
        qc.invalidateQueries({ queryKey: keys.images(projectId) })
        qc.invalidateQueries({ queryKey: keys.stats(projectId) })
      }
      return jobs
    },
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 2000 : false),
  })
}

export const useJobItems = (jobId: number, enabled: boolean) =>
  useQuery({
    queryKey: keys.jobItems(jobId),
    queryFn: () => api<JobItem[]>(`/jobs/${jobId}/items?status=error`),
    enabled,
  })

export interface AutolabelRequest {
  provider: string
  mode: string
  params: Record<string, number | boolean>
  target: 'all' | 'unlabeled' | 'selected'
  image_ids?: number[]
  include_reviewed: boolean
}

export function useStartAutolabel(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AutolabelRequest) =>
      api<Job>(`/projects/${projectId}/jobs/autolabel`, json('POST', body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs(projectId) }),
  })
}

export function useCancelJob(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: number) => api<Job>(`/jobs/${jobId}/cancel`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs(projectId) }),
  })
}

// --- editor & exemplars ----------------------------------------------------

export const useImageDetail = (imageId: number, filters: ImageFilters) =>
  useQuery({
    queryKey: ['image', imageId, filters],
    queryFn: () => api<ImageDetail>(`/images/${imageId}${queryString(filters)}`),
  })

export interface AnnotationPayload {
  id: number | null
  class_id: number
  x_min: number
  y_min: number
  x_max: number
  y_max: number
  is_approved: boolean
}

export function useSaveAnnotations(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ imageId, annotations, approve }: { imageId: number; annotations: AnnotationPayload[]; approve: boolean }) =>
      api<ImageItem>(`/images/${imageId}/annotations`, json('PUT', { annotations, approve })),
    onSuccess: (_data, { imageId }) => {
      qc.invalidateQueries({ queryKey: ['image', imageId] })
      qc.invalidateQueries({ queryKey: keys.images(projectId) })
      qc.invalidateQueries({ queryKey: keys.stats(projectId) })
      qc.invalidateQueries({ queryKey: keys.classes(projectId) })
    },
  })
}

export const useExemplars = (classId: number, enabled = true) =>
  useQuery({
    queryKey: ['exemplars', classId],
    queryFn: () => api<Exemplar[]>(`/classes/${classId}/exemplars`),
    enabled,
  })

export function useCreateExemplar(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (annotationId: number) => api<Exemplar>(`/annotations/${annotationId}/exemplar`, { method: 'POST' }),
    onSuccess: (ex) => {
      qc.invalidateQueries({ queryKey: ['exemplars', ex.class_id] })
      qc.invalidateQueries({ queryKey: keys.classes(projectId) })
    },
  })
}

export function useDeleteExemplar(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ex: Exemplar) => api<void>(`/exemplars/${ex.id}`, { method: 'DELETE' }),
    onSuccess: (_d, ex) => {
      qc.invalidateQueries({ queryKey: ['exemplars', ex.class_id] })
      qc.invalidateQueries({ queryKey: keys.classes(projectId) })
    },
  })
}
