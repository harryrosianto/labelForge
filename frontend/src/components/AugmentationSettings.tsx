import type { AugmentationConfig, AugmentPreview, LabelClass } from '../api/types'
import { Button, ErrorText, Spinner } from './ui'

type Key = keyof AugmentationConfig

const GROUPS: { title: string; fields: [Key, string, number, number, number, (v: number) => string][] }[] = [
  {
    title: 'Geometri',
    fields: [
      ['hflip', 'Flip horizontal (peluang)', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
      ['rotate_deg', 'Rotasi acak ±', 0, 45, 1, (v) => `${v}°`],
      ['scale_min', 'Skala minimum', 0.5, 1, 0.05, (v) => `${v.toFixed(2)}×`],
      ['scale_max', 'Skala maksimum', 1, 2, 0.05, (v) => `${v.toFixed(2)}×`],
      ['translate', 'Geser acak ±', 0, 0.3, 0.01, (v) => `${Math.round(v * 100)}%`],
      ['mosaic', 'Mosaic 2×2 (peluang)', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
    ],
  },
  {
    title: 'Warna & cahaya',
    fields: [
      ['brightness', 'Brightness ±', 0, 0.5, 0.05, (v) => `${Math.round(v * 100)}%`],
      ['contrast', 'Contrast ±', 0, 0.5, 0.05, (v) => `${Math.round(v * 100)}%`],
      ['hue_deg', 'Hue ±', 0, 30, 1, (v) => `${v}°`],
      ['saturation', 'Saturation ±', 0, 0.7, 0.05, (v) => `${Math.round(v * 100)}%`],
    ],
  },
  {
    title: 'Gangguan',
    fields: [
      ['blur', 'Blur (peluang)', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
      ['noise', 'Noise (peluang)', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`],
      ['noise_std', 'Kekuatan noise', 0, 30, 1, (v) => `${v}`],
    ],
  },
  {
    title: 'Box',
    fields: [['min_visibility', 'Buang box bila tersisa <', 0, 1, 0.05, (v) => `${Math.round(v * 100)}%`]],
  },
]

export function AugmentationSettings({
  value,
  onChange,
  preview,
  previewing,
  previewError,
  onPreview,
  classes,
}: {
  value: AugmentationConfig
  onChange: (v: AugmentationConfig) => void
  preview?: AugmentPreview
  previewing: boolean
  previewError: unknown
  onPreview: () => void
  classes: LabelClass[]
}) {
  const set = (k: Key, v: number | boolean) => onChange({ ...value, [k]: v })
  const colorOf = (name: string) => classes.find((c) => c.name === name)?.color ?? '#00b0ad'

  return (
    <fieldset className="space-y-3">
      <legend className="mb-1 text-sm font-medium text-slate-700">Augmentasi</legend>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="accent-brand-600" checked={value.enabled} onChange={(e) => set('enabled', e.target.checked)} />
        Buat salinan augmentasi untuk split train
        {value.enabled && (
          <select
            className="ml-2 rounded border border-slate-300 px-1.5 py-0.5 text-sm"
            value={value.multiplier}
            onChange={(e) => set('multiplier', Number(e.target.value))}
            aria-label="Jumlah salinan per gambar"
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}× per gambar
              </option>
            ))}
          </select>
        )}
      </label>
      {value.enabled && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {GROUPS.map((g) => (
              <div key={g.title} className="space-y-2 rounded-md bg-slate-50 p-3 ring-1 ring-slate-200">
                <h4 className="text-xs font-semibold uppercase text-slate-500">{g.title}</h4>
                {g.fields.map(([key, label, min, max, step, show]) => (
                  <label key={key} className="block text-sm">
                    <span className="flex justify-between">
                      <span className="text-slate-700">{label}</span>
                      <span className="tabular-nums text-slate-500">{show(value[key] as number)}</span>
                    </span>
                    <input
                      type="range"
                      className="w-full accent-brand-600"
                      min={min}
                      max={max}
                      step={step}
                      value={value[key] as number}
                      onChange={(e) => {
                        const v = Number(e.target.value)
                        // jaga agar skala min <= maks
                        if (key === 'scale_min') onChange({ ...value, scale_min: v, scale_max: Math.max(v, value.scale_max) })
                        else if (key === 'scale_max') onChange({ ...value, scale_max: v, scale_min: Math.min(v, value.scale_min) })
                        else set(key, v)
                      }}
                    />
                  </label>
                ))}
              </div>
            ))}
          </div>

          <div className="space-y-2">
            <Button onClick={onPreview} disabled={previewing}>
              {previewing && <Spinner />} Pratinjau augmentasi
            </Button>
            <ErrorText error={previewError} />
            {preview && preview.samples.length === 0 && <p className="text-sm text-slate-500">Belum ada gambar untuk dipratinjau.</p>}
            {preview && preview.samples.length > 0 && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {preview.samples.map((s, i) => (
                  <figure key={i} className="relative overflow-hidden rounded bg-slate-200" style={{ aspectRatio: s.width / s.height }}>
                    <img src={s.data_url} alt={`Contoh augmentasi ${i + 1}`} className="absolute inset-0 h-full w-full" />
                    <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
                      {s.boxes.map(([cls, x1, y1, x2, y2], j) => (
                        <rect key={j} x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none"
                          stroke={colorOf(preview.classes[cls])} strokeWidth={2} vectorEffect="non-scaling-stroke" />
                      ))}
                    </svg>
                  </figure>
                ))}
              </div>
            )}
            {preview && (
              <p className="text-xs text-slate-500">Contoh diacak ulang setiap pratinjau dengan seed yang sama; ubah seed untuk variasi lain.</p>
            )}
          </div>
        </>
      )}
    </fieldset>
  )
}
