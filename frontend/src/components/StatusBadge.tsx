import type { ImageStatus, JobStatus } from '../api/types'
import { IMAGE_STATUS, JOB_STATUS } from '../lib/labels'

function Badge({ text, className }: { text: string; className: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${className}`}>{text}</span>
}

export const ImageStatusBadge = ({ status }: { status: ImageStatus }) => {
  const [text, cls] = IMAGE_STATUS[status]
  return <Badge text={text} className={cls} />
}

export const JobStatusBadge = ({ status }: { status: JobStatus }) => {
  const [text, cls] = JOB_STATUS[status]
  return <Badge text={text} className={cls} />
}
