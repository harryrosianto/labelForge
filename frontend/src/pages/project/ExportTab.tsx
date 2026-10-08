import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, json } from '../../api/client'
import { useProject } from '../../api/hooks'
import { Button, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { downloadPost } from '../../lib/download'
import { useProjectId } from '../../lib/route'

type Format = 'yolo' | 'coco'

interface Preview {
  images: number
  annotations: number
  splits: Record<'train' | 'val' | 'test', number>
  per_class: Record<string, number>
  empty_images: number
}

const FORMATS: [Format, string, string][] = [
  ['yolo', 'YOLO', 'images/, labels/ (txt ternormalisasi), data.yaml, siap untuk training YOLO'],
  ['coco', 'COCO JSON', 'images/ + annotations/instances_{split}.json (bbox pixel)'],
]

export function ExportTab() {
  const id = useProjectId()
  const { data: project } = useProject(id)
  const [format, setFormat] = useState<Format>('yolo')
  const [reviewedOnly, setReviewedOnly] = useState(true)
  const [split, setSplit] = useState({ train: 80, val: 20, test: 0 })
  const [seed, setSeed] = useState(42)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const total = split.train + split.val + split.test
  const body = {
    format,
    reviewed_only: reviewedOnly,
    split: { train: split.train / 100, val: split.val / 100, test: split.test / 100 },
    seed,
  }
  const valid = split.train > 0 && total > 0

  const preview = useQuery({
    queryKey: ['projects', id, 'export-preview', body],
    queryFn: () => api<Preview>(`/projects/${id}/export/preview`, json('POST', body)),
    enabled: valid,
  })

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,28rem)_1fr]">
      <form
        className="space-y-5 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError(null)
          try {
            await downloadPost(`/projects/${id}/export`, body)
          } catch (err) {
            setError(err)
          } finally {
            setBusy(false)
          }
        }}
      >
        <h2 className="font-semibold">Export dataset</h2>

        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium text-slate-700">Format</legend>
          {FORMATS.map(([value, label, hint]) => (
            <label
              key={value}
              className={`flex cursor-pointer gap-3 rounded-md p-3 ring-1 ${
                format === value ? 'bg-brand-50 ring-brand-300' : 'ring-slate-200 hover:bg-slate-50'
              }`}
            >
              <input type="radio" name="format" checked={format === value} onChange={() => setFormat(value)} className="accent-brand-600" />
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-slate-500">{hint}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <fieldset className="space-y-1 text-sm">
          <legend className="mb-1 font-medium text-slate-700">Gambar</legend>
          <label className="flex items-center gap-2">
            <input type="radio" checked={reviewedOnly} onChange={() => setReviewedOnly(true)} className="accent-brand-600" />
            Hanya yang sudah reviewed (disarankan)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={!reviewedOnly} onChange={() => setReviewedOnly(false)} className="accent-brand-600" />
            Reviewed + auto-label (box AI belum dicek ikut)
          </label>
          <p className="text-xs text-slate-500">Gambar yang belum berlabel tidak pernah ikut diekspor.</p>
        </fieldset>

        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">Split (%)</legend>
          <div className="grid grid-cols-3 gap-2">
            {(['train', 'val', 'test'] as const).map((s) => (
              <Field key={s} label={s}>
                <input
                  type="number"
                  min={0}
                  max={100}
                  className={inputClass}
                  value={split[s]}
                  onChange={(e) => setSplit({ ...split, [s]: Math.max(0, Number(e.target.value)) })}
                />
              </Field>
            ))}
          </div>
          {total !== 100 && valid && <p className="mt-1 text-xs text-amber-700">Total {total}%, akan dinormalisasi.</p>}
          {!valid && <p className="mt-1 text-xs text-rose-600">Split train harus lebih dari 0.</p>}
        </fieldset>

        <Field label="Seed acak" hint="Seed sama → pembagian split sama, berguna agar export ulang konsisten">
          <input type="number" className={`${inputClass} w-32`} value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </Field>

        <ErrorText error={error} />
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !valid || !preview.data?.images}>
          {busy && <Spinner />} Download ZIP
        </Button>
      </form>

      <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 font-semibold">Isi export {project ? `: ${project.name}` : ''}</h2>
        {preview.isLoading && <Spinner />}
        <ErrorText error={preview.error} />
        {preview.data && preview.data.images === 0 && (
          <p className="text-sm text-amber-700">
            Belum ada gambar {reviewedOnly ? 'yang reviewed' : 'berlabel'}. Review gambar di editor (Enter = approve).
          </p>
        )}
        {preview.data && preview.data.images > 0 && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-3 gap-3">
              {(['train', 'val', 'test'] as const).map((s) => (
                <div key={s} className="rounded-md bg-slate-50 p-3 text-center ring-1 ring-slate-200">
                  <p className="text-xs uppercase text-slate-500">{s}</p>
                  <p className="text-xl font-semibold text-ink">{preview.data.splits[s]}</p>
                </div>
              ))}
            </div>
            <p className="text-slate-600">
              {preview.data.images} gambar · {preview.data.annotations} box
              {preview.data.empty_images > 0 && ` · ${preview.data.empty_images} gambar tanpa objek (contoh negatif)`}
            </p>
            <table className="w-full">
              <thead>
                <tr className="text-left text-xs uppercase text-slate-500">
                  <th className="py-1 font-medium">Index</th>
                  <th className="py-1 font-medium">Class</th>
                  <th className="py-1 text-right font-medium">Box</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(preview.data.per_class).map(([name, n], i) => (
                  <tr key={name} className="border-t border-slate-100">
                    <td className="py-1 tabular-nums text-slate-500">{i}</td>
                    <td className="py-1">{name}</td>
                    <td className={`py-1 text-right tabular-nums ${n === 0 ? 'text-amber-700' : ''}`}>{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.values(preview.data.per_class).some((n) => n === 0) && (
              <p className="text-xs text-amber-700">Ada class tanpa box, model tidak akan belajar mengenalinya.</p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
