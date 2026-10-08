import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, json, queryString } from './client'
import { uploadWithProgress } from './upload'
import type {
  AugmentPreview,
  Camera,
  CaptureOptions,
  ExtractOptions,
  Job,
  Video,
  ClassMapping,
  DatasetStatsData,
  DatasetImport,
  DatasetVersion,
  VersionCompare,
  VersionSettings,
  VersionSummary,
  Exemplar,
  Health,
  ImageDetail,
  ImageItem,
  ImagePage,
  ImageFilters,
  JobItem,
  LabelClass,
  Project,
  ProjectStats,
  ProviderInfo,
  UploadResult,} from './types'

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
      api<{ deleted: number; protected: number[] }>(`/projects/${projectId}/images/bulk-delete`, json('POST', { image_ids: imageIds })),
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

// --- import dataset ----------------------------------------------------------

export const useImports = (projectId: number) =>
  useQuery({
    queryKey: [...keys.project(projectId), 'imports'],
    queryFn: () => api<DatasetImport[]>(`/projects/${projectId}/imports`),
    refetchInterval: (q) => (q.state.data?.some((i) => i.status === 'importing') ? 2000 : false),
  })

export const uploadImportZip = (projectId: number, file: File, onProgress: (fraction: number) => void) =>
  uploadWithProgress<DatasetImport>(`/projects/${projectId}/imports`, file, onProgress)

export function useStartImport(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, mapping, markForReview }: { id: number; mapping: Record<string, ClassMapping>; markForReview: boolean }) =>
      api<DatasetImport>(`/imports/${id}/start`, json('POST', { mapping, mark_for_review: markForReview })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.project(projectId) }),
  })
}

export function useDiscardImport(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/imports/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...keys.project(projectId), 'imports'] }),
  })
}

// --- versi dataset -------------------------------------------------------------

const versionsKey = (projectId: number) => [...keys.project(projectId), 'versions'] as const

export const useVersions = (projectId: number) =>
  useQuery({
    queryKey: versionsKey(projectId),
    queryFn: () => api<DatasetVersion[]>(`/projects/${projectId}/versions`),
    refetchInterval: (q) => (q.state.data?.some((v) => v.status === 'building') ? 2000 : false),
  })

export const useVersionPreview = (projectId: number, settings: VersionSettings, enabled: boolean) =>
  useQuery({
    queryKey: [...versionsKey(projectId), 'preview', settings],
    queryFn: () => api<VersionSummary>(`/projects/${projectId}/versions/preview`, json('POST', settings)),
    enabled,
    placeholderData: keepPreviousData,
  })

export function useCreateVersion(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: VersionSettings & { name: string; notes: string | null }) =>
      api<DatasetVersion>(`/projects/${projectId}/versions`, json('POST', body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.project(projectId) }),
  })
}

export function useUpdateVersion(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number; name?: string; notes?: string | null }) =>
      api<DatasetVersion>(`/versions/${id}`, json('PATCH', body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: versionsKey(projectId) }),
  })
}

export function useDeleteVersion(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/versions/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: versionsKey(projectId) }),
  })
}

export const useCompareVersions = (a: number | null, b: number | null) =>
  useQuery({
    queryKey: ['versions-compare', a, b],
    queryFn: () => api<VersionCompare>(`/versions/compare${queryString({ a, b })}`),
    enabled: a !== null && b !== null,
  })

// --- statistik dataset ---------------------------------------------------------

export const useDatasetStats = (projectId: number, filters: ImageFilters) =>
  useQuery({
    queryKey: [...keys.stats(projectId), 'dataset', filters],
    queryFn: () => api<DatasetStatsData>(`/projects/${projectId}/stats/dataset${queryString(filters)}`),
    placeholderData: keepPreviousData,
  })

export const useVersionStats = (versionId: number, enabled: boolean) =>
  useQuery({
    queryKey: ['version-stats', versionId],
    queryFn: () => api<DatasetStatsData>(`/versions/${versionId}/stats`),
    enabled,
    staleTime: Infinity, // isi versi tidak pernah berubah
  })

export function useAugmentPreview(projectId: number) {
  return useMutation({
    mutationFn: (body: VersionSettings & { count: number }) =>
      api<AugmentPreview>(`/projects/${projectId}/versions/preview-augmentation`, json('POST', body)),
  })
}

// --- video & kamera -------------------------------------------------------------

export const uploadVideo = (projectId: number, file: File, onProgress: (fraction: number) => void) =>
  uploadWithProgress<Video>(`/projects/${projectId}/videos`, file, onProgress)

export const useVideos = (projectId: number) =>
  useQuery({ queryKey: [...keys.project(projectId), 'videos'], queryFn: () => api<Video[]>(`/projects/${projectId}/videos`) })

export function useDeleteVideo(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/videos/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...keys.project(projectId), 'videos'] }),
  })
}

export const useExtractPreview = (videoId: number, options: ExtractOptions, enabled: boolean) =>
  useQuery({
    queryKey: ['video-extract-preview', videoId, options],
    queryFn: () => api<{ frames: number }>(`/videos/${videoId}/extract/preview`, json('POST', options)),
    enabled,
    placeholderData: keepPreviousData,
  })

export function useStartExtract(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ videoId, options }: { videoId: number; options: ExtractOptions }) =>
      api<Job>(`/videos/${videoId}/extract`, json('POST', options)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs(projectId) }),
  })
}

export const useCameras = (projectId: number) =>
  useQuery({ queryKey: [...keys.project(projectId), 'cameras'], queryFn: () => api<Camera[]>(`/projects/${projectId}/cameras`) })

export function useAddCamera(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; url: string }) => api<Camera>(`/projects/${projectId}/cameras`, json('POST', body)),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...keys.project(projectId), 'cameras'] }),
  })
}

export function useDeleteCamera(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<void>(`/cameras/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...keys.project(projectId), 'cameras'] }),
  })
}

export const useTestCamera = () =>
  useMutation({
    mutationFn: (id: number) =>
      api<{ ok: boolean; error?: string; width?: number; height?: number; preview?: string }>(`/cameras/${id}/test`, { method: 'POST' }),
  })

export function useStartCapture(projectId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ cameraId, options }: { cameraId: number; options: CaptureOptions }) =>
      api<Job>(`/cameras/${cameraId}/capture`, json('POST', options)),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs(projectId) }),
  })
}
