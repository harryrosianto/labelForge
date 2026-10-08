// Tipe respons API backend (labelforge/schemas/*).

export type ImageStatus = 'unlabeled' | 'auto_labeled' | 'reviewed'
export type ImageSource = 'upload' | 'import' | 'video' | 'rtsp'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type JobTarget = 'all' | 'unlabeled' | 'selected'
export type JobType = 'autolabel' | 'import' | 'version_build' | 'video_extract' | 'rtsp_capture' | 'train'

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
  source_type: ImageSource
  source_id: number | null
  source_label: string | null
  frame_time_s: number | null
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
  job_type: JobType
  provider: string | null
  mode: string | null
  params: Record<string, unknown>
  target: JobTarget
  include_reviewed: boolean
  status: JobStatus
  total: number
  processed: number
  failed_count: number
  warnings: string[]
  payload: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error: string | null
  cancel_requested: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
  progress: number
}

export interface JobItem {
  id: number
  image_id: number | null
  label: string | null
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
  source_type?: ImageSource
  class_id?: number
  source?: string
  max_conf?: number
}

export interface Exemplar {
  id: number
  class_id: number
  source_image_id: number | null
  source_annotation_id: number | null
  width: number
  height: number
  created_at: string
}

export type MappingAction = 'map' | 'create' | 'ignore'

export interface ClassMapping {
  action: MappingAction
  class_id?: number | null
  name?: string | null
}

export interface ImportAnalysis {
  format: 'yolo' | 'coco'
  images: number
  images_with_boxes: number
  boxes: number
  splits: Record<string, number>
  classes: { name: string; boxes: number; images: number }[]
  problem_counts: Record<string, { count: number; label: string }>
  problems: { kind: string; path: string; detail: string }[]
  suggested_mapping: Record<string, ClassMapping>
}

export interface DatasetImport {
  id: number
  project_id: number
  original_filename: string
  format: 'yolo' | 'coco' | null
  status: 'analyzed' | 'importing' | 'completed' | 'failed'
  error: string | null
  analysis: ImportAnalysis | null
  job_id: number | null
  created_at: string
}
