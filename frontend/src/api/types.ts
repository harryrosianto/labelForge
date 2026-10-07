// Tipe respons API backend (labelforge/schemas/*).

export type ImageStatus = 'unlabeled' | 'auto_labeled' | 'reviewed'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type JobTarget = 'all' | 'unlabeled' | 'selected'

export interface Project {
  id: number
  name: string
  description: string | null
  task_type: string
  created_at: string
  updated_at: string
  image_count: number
  class_count: number
}

export interface ProjectStats {
  total_images: number
  total_annotations: number
  images_by_status: Record<ImageStatus, number>
  annotations_by_class: { class_id: number; name: string; color: string; annotations: number }[]
  annotations_by_source: Record<string, number>
  unapproved_annotations: number
}

export interface LabelClass {
  id: number
  project_id: number
  name: string
  color: string
  text_prompt: string | null
  effective_prompt: string
  order_index: number
  annotation_count: number
  exemplar_count: number
}

export interface Annotation {
  id: number
  class_id: number
  x_min: number
  y_min: number
  x_max: number
  y_max: number
  source: string
  confidence: number | null
  is_approved: boolean
}

export interface ImageItem {
  id: number
  project_id: number
  original_filename: string
  width: number
  height: number
  status: ImageStatus
  created_at: string
  updated_at: string
  annotations: Annotation[]
}

export interface ImagePage {
  items: ImageItem[]
  total: number
  page: number
  page_size: number
}

export interface ImageDetail extends ImageItem {
  prev_id: number | null
  next_id: number | null
  position: number | null
  filtered_total: number | null
}

export interface UploadIssue {
  filename: string
  detail: string
  image_id: number | null
}

export interface UploadResult {
  uploaded: Omit<ImageItem, 'annotations'>[]
  duplicates: UploadIssue[]
  skipped: UploadIssue[]
  errors: UploadIssue[]
}

export interface ParamSpec {
  name: string
  type: 'float' | 'int' | 'bool'
  default: number | boolean
  label: string
  description: string
  min: number | null
  max: number | null
  step: number | null
}

export interface ProviderInfo {
  name: string
  label: string
  is_default: boolean
  default_mode: string
  modes: string[]
  available: boolean
  unavailable_reason: string | null
  params: Record<string, ParamSpec[]>
}

export interface Job {
  id: number
  project_id: number
  job_type: string
  provider: string
  mode: string | null
  params: Record<string, unknown>
  target: JobTarget
  include_reviewed: boolean
  status: JobStatus
  total: number
  processed: number
  failed_count: number
  warnings: string[]
  error: string | null
  cancel_requested: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: number
}

export interface JobItem {
  id: number
  image_id: number
  status: 'pending' | 'done' | 'error'
  num_detections: number | null
  error: string | null
  duration_ms: number | null
}

export interface Health {
  status: string
  version: string
  db: string
  workers: string[]
}

export interface ImageFilters {
  status?: ImageStatus
  class_id?: number
  source?: string
  max_conf?: number
}
