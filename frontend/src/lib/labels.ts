import type { ImageSource, ImageStatus, JobStatus, JobType } from '../api/types'

export const IMAGE_STATUS: Record<ImageStatus, [label: string, className: string]> = {
  unlabeled: ['Belum berlabel', 'bg-slate-100 text-slate-600'],
  auto_labeled: ['Auto-label', 'bg-amber-100 text-amber-800'],
  reviewed: ['Reviewed', 'bg-emerald-100 text-emerald-800'],
}

export const JOB_STATUS: Record<JobStatus, [label: string, className: string]> = {
  queued: ['Antre', 'bg-slate-100 text-slate-600'],
  running: ['Berjalan', 'bg-brand-100 text-brand-800'],
  completed: ['Selesai', 'bg-emerald-100 text-emerald-800'],
  failed: ['Gagal', 'bg-rose-100 text-rose-700'],
  cancelled: ['Dibatalkan', 'bg-slate-200 text-slate-600'],
}

export const IMAGE_STATUS_LABELS = Object.fromEntries(
  Object.entries(IMAGE_STATUS).map(([k, [label]]) => [k, label]),
) as Record<ImageStatus, string>

export const JOB_TYPE_LABELS: Record<JobType, string> = {
  autolabel: 'Auto-label',
  import: 'Import dataset',
  version_build: 'Buat versi',
  video_extract: 'Ekstraksi video',
  rtsp_capture: 'Capture kamera',
  export: 'Export dataset',
  train: 'Training',
}

export const IMAGE_SOURCE_LABELS: Record<ImageSource, string> = {
  upload: 'Upload',
  import: 'Import dataset',
  video: 'Video',
  rtsp: 'Kamera',
}
