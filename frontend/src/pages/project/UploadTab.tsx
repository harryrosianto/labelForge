import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { useUploadImages } from '../../api/hooks'
import type { UploadIssue } from '../../api/types'
import { Button, ErrorText, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const ACCEPT = '.jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff,.zip'
const BATCH_FILES = 20 // gambar dikirim per batch agar progress terlihat; ZIP dikirim sendiri-sendiri

interface Summary {
  uploaded: number
  duplicates: UploadIssue[]
  skipped: UploadIssue[]
  errors: UploadIssue[]
}

function batches(files: File[]): File[][] {
  const zips = files.filter((f) => f.name.toLowerCase().endsWith('.zip')).map((f) => [f])
  const images = files.filter((f) => !f.name.toLowerCase().endsWith('.zip'))
  const out: File[][] = []
  for (let i = 0; i < images.length; i += BATCH_FILES) out.push(images.slice(i, i + BATCH_FILES))
  return [...out, ...zips]
}

function IssueList({ title, items, className }: { title: string; items: UploadIssue[]; className: string }) {
  if (!items.length) return null
  return (
    <details className="text-sm">
      <summary className={`cursor-pointer ${className}`}>
        {title}: {items.length}
      </summary>
      <ul className="mt-1 max-h-48 overflow-auto pl-4 text-slate-600">
        {items.map((i, n) => (
          <li key={n}>
            {i.filename} — {i.detail}
          </li>
        ))}
      </ul>
    </details>
  )
}

export function UploadTab() {
  const id = useProjectId()
  const upload = useUploadImages(id)
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [error, setError] = useState<unknown>(null)

  async function start(files: File[]) {
    if (!files.length) return
    const parts = batches(files)
    const result: Summary = { uploaded: 0, duplicates: [], skipped: [], errors: [] }
    setSummary(null)
    setError(null)
    setProgress({ done: 0, total: parts.length })
    try {
      for (const [i, part] of parts.entries()) {
        const r = await upload.mutateAsync(part)
        result.uploaded += r.uploaded.length
        result.duplicates.push(...r.duplicates)
        result.skipped.push(...r.skipped)
        result.errors.push(...r.errors)
        setProgress({ done: i + 1, total: parts.length })
        setSummary({ ...result })
      }
    } catch (e) {
      setError(e)
    } finally {
      setProgress(null)
    }
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => (e.preventDefault(), setDragging(true))}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          start(Array.from(e.dataTransfer.files))
        }}
        className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-12 text-center
          ${dragging ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 bg-white'}`}
      >
        <p className="text-lg font-medium">Tarik & lepas gambar atau file ZIP di sini</p>
        <p className="mt-1 text-sm text-slate-500">JPG, PNG, BMP, WEBP, TIFF, atau ZIP berisi gambar</p>
        <Button variant="primary" className="mt-4" disabled={!!progress} onClick={() => input.current?.click()}>
          Pilih file
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            start(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
      </div>

      {progress && (
        <div className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <div className="mb-2 flex items-center gap-2 text-sm">
            <Spinner /> Mengunggah batch {Math.min(progress.done + 1, progress.total)} dari {progress.total}…
          </div>
          <div className="h-2 rounded bg-slate-100">
            <div className="h-2 rounded bg-indigo-500" style={{ width: `${(progress.done / progress.total) * 100}%` }} />
          </div>
        </div>
      )}

      <ErrorText error={error} />

      {summary && (
        <div className="space-y-2 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <p className="font-medium text-emerald-700">{summary.uploaded} gambar baru ditambahkan</p>
          <IssueList title="Duplikat (dilewati)" items={summary.duplicates} className="text-slate-600" />
          <IssueList title="Bukan gambar (dilewati)" items={summary.skipped} className="text-slate-600" />
          <IssueList title="Gagal" items={summary.errors} className="text-rose-600" />
          {summary.uploaded > 0 && !progress && (
            <div className="flex gap-3 pt-2 text-sm">
              <Link to="../gallery" relative="path" className="font-medium text-indigo-600">
                Lihat galeri →
              </Link>
              <Link to="../autolabel" relative="path" className="font-medium text-indigo-600">
                Jalankan auto-label →
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
