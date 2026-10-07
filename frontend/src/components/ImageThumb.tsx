import { imageThumbUrl } from '../api/client'
import type { ImageItem, LabelClass } from '../api/types'
import { ImageStatusBadge } from './StatusBadge'

/** Thumbnail dengan overlay box. Koordinat anotasi ternormalisasi 0-1 → viewBox 0..1. */
export function ImageThumb({
  image,
  classes,
  selected,
  onToggle,
  onOpen,
}: {
  image: ImageItem
  classes: Map<number, LabelClass>
  selected: boolean
  onToggle: () => void
  onOpen: () => void
}) {
  const ratio = image.width / image.height
  return (
    <div
      className={`group relative overflow-hidden rounded-md bg-slate-200 ring-2 transition
        ${selected ? 'ring-indigo-500' : 'ring-transparent hover:ring-slate-300'}`}
    >
      <button type="button" className="block w-full" onClick={onOpen} title={image.original_filename}>
        <div className="relative w-full" style={{ aspectRatio: ratio }}>
          <img
            src={imageThumbUrl(image.id)}
            alt={image.original_filename}
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
          />
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
            {image.annotations.map((a) => (
              <rect
                key={a.id}
                x={a.x_min}
                y={a.y_min}
                width={a.x_max - a.x_min}
                height={a.y_max - a.y_min}
                fill="none"
                stroke={classes.get(a.class_id)?.color ?? '#fff'}
                strokeWidth={2}
                strokeDasharray={a.is_approved ? undefined : '4 3'}
                vectorEffect="non-scaling-stroke"
              />
            ))}
          </svg>
        </div>
      </button>
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Pilih ${image.original_filename}`}
        className={`absolute left-2 top-2 h-4 w-4 cursor-pointer accent-indigo-600
          ${selected ? '' : 'opacity-0 group-hover:opacity-100'}`}
      />
      <div className="flex items-center justify-between gap-1 bg-white px-2 py-1">
        <span className="truncate text-xs text-slate-600">{image.original_filename}</span>
        <ImageStatusBadge status={image.status} />
      </div>
    </div>
  )
}
