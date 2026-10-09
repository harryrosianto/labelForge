// Tipe respons API backend (labelforge/schemas/*).

export type ImageStatus = 'unlabeled' | 'auto_labeled' | 'reviewed'
export type ImageSource = 'upload' | 'import' | 'video' | 'rtsp'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type JobTarget = 'all' | 'unlabeled' | 'selected'
export type JobType = 'autolabel' | 'import' | 'version_build' | 'video_extract' | 'rtsp_capture' | 'export' | 'train'

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

export interface WorkerInfo {
  name: string
  queues: string[]
  state: 'starting' | 'loading_model' | 'ready'
}

export interface Health {
  status: string
  version: string
  db: string
  workers: string[]
  worker_details: WorkerInfo[]
  queues_without_worker: string[]
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

export interface Preprocessing {
  resize: 'none' | 'stretch' | 'fit'
  width?: number | null
  height?: number | null
}

export interface AugmentationConfig {
  enabled: boolean
  multiplier: number
  hflip: number
  rotate_deg: number
  scale_min: number
  scale_max: number
  translate: number
  mosaic: number
  brightness: number
  contrast: number
  hue_deg: number
  saturation: number
  blur: number
  blur_max_kernel: number
  noise: number
  noise_std: number
  min_visibility: number
}

export interface VersionSettings {
  reviewed_only: boolean
  split: { train: number; val: number; test: number }
  seed: number
  preprocessing: Preprocessing
  augmentation?: AugmentationConfig
}

export interface AugmentPreview {
  classes: string[]
  samples: { image_id: number; width: number; height: number; data_url: string; boxes: number[][] }[]
}

export interface VersionSummary {
  images: number
  source_images: number
  augmented: number
  annotations: number
  splits: { train: number; val: number; test: number }
  per_class: { name: string; boxes: number; images: number }[]
  empty_images: number
}

export interface DatasetVersion {
  id: number
  project_id: number
  name: string
  notes: string | null
  status: 'building' | 'ready' | 'failed'
  config: VersionSettings & { classes: { name: string; color: string }[] }
  summary: VersionSummary | null
  image_count: number
  job_id: number | null
  created_at: string
  updated_at: string
}

export interface VersionCompare {
  a: { id: number; name: string; summary: VersionSummary }
  b: { id: number; name: string; summary: VersionSummary }
  images_only_in_a: number
  images_only_in_b: number
  images_in_both: number
  labels_changed: number
  split_changed: number
  per_class: { name: string; a: number; b: number }[]
  settings_changed: Record<string, { a: unknown; b: unknown }>
}

export interface DatasetStatsData {
  images: number
  boxes: number
  empty_images: number
  classes: { name: string; boxes: number; images: number; small: number; medium: number; large: number }[]
  box_size: {
    small: number
    medium: number
    large: number
    relative_side_hist: { from: number; to: number; count: number }[]
  }
  boxes_per_image: { label: string; count: number }[]
  aspect_ratio: { label: string; count: number }[]
  heatmap: { grid: number; counts: number[][] }
  image_sizes: { width: number; height: number; count: number }[]
  warnings: { kind: string; classes: string[]; message: string }[]
}

export interface Video {
  id: number
  project_id: number
  original_filename: string
  duration_s: number | null
  fps: number | null
  frame_count: number | null
  width: number | null
  height: number | null
  created_at: string
}

export interface ExtractOptions {
  every_s?: number | null
  fps?: number | null
  start_s: number
  end_s?: number | null
  max_frames: number
  dedup_threshold: number
}

export interface Camera {
  id: number
  project_id: number
  name: string
  url_masked: string
  created_at: string
}

export interface CaptureOptions {
  interval_s: number
  duration_s?: number | null
  max_frames?: number | null
  dedup_threshold: number
  reconnect_attempts?: number
}
