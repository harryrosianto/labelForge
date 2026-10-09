import { useState } from 'react'

import { bulkStatus, useAudits, useBulkStatus, useCreateAudit, useDeleteAudit } from '../api/hooks'
import type { Audit, ImageFilters } from '../api/types'
import { Button, ErrorText, Field, inputClass, Spinner } from './ui'

const pct = (rate: number | null) => (rate === null ? '-' : `${(rate * 100).toFixed(1)}%`)

/** Approve / kembalikan ke perlu review untuk semua hasil filter, atau hanya gambar terpilih. */
export function BulkStatusButtons({
  projectId,
  filters,
  imageIds,
  onDone,
}: {
  projectId: number
  filters: ImageFilters
  imageIds?: number[]
  onDone?: () => void
}) {
  const apply = useBulkStatus(projectId)
  const [checking, setChecking] = useState(false)
  const scope = imageIds ? 'terpilih' : 'hasil filter'

  const run = async (status: 'reviewed' | 'auto_labeled') => {
    const body = { status, filters, image_ids: imageIds }
    setChecking(true)
    try {
      const dry = await bulkStatus(projectId, { ...body, dry_run: true })
      if (dry.changed === 0) {
        alert(status === 'reviewed' ? `Tidak ada gambar auto-label di ${scope}.` : `Tidak ada gambar reviewed di ${scope}.`)
        return
      }
      const lines =
        status === 'reviewed'
          ? [
              `Tandai ${dry.changed} gambar sebagai reviewed?`,
              dry.without_boxes > 0 && `${dry.without_boxes} di antaranya tanpa box dan akan menjadi contoh negatif.`,
              dry.skipped_unlabeled > 0 && `${dry.skipped_unlabeled} gambar belum berlabel dilewati.`,
            ]
          : [`Kembalikan ${dry.changed} gambar reviewed ke status perlu review?`]
      if (confirm(lines.filter(Boolean).join('\n\n'))) apply.mutate(body, { onSuccess: onDone })
    } finally {
      setChecking(false)
    }
  }

  const busy = checking || apply.isPending
  return (
    <>
      <Button variant="secondary" disabled={busy} onClick={() => run('reviewed')}>
        {busy && <Spinner />} Approve {scope}
      </Button>
      <Button variant="ghost" disabled={busy} onClick={() => run('auto_labeled')}>
        Kembalikan ke perlu review
      </Button>
      <ErrorText error={apply.error} />
    </>
  )
}

/** Buat audit sampel dari filter aktif dan daftar audit sebelumnya. */
export function AuditPanel({
  projectId,
  filters,
  onOpen,
}: {
  projectId: number
  filters: ImageFilters
  onOpen: (audit: Audit) => void
}) {
  const [size, setSize] = useState(200)
  const create = useCreateAudit(projectId)
  const remove = useDeleteAudit(projectId)
  const { data: audits = [] } = useAudits(projectId)
  const base = { ...filters, audit_id: undefined }

  return (
    <div className="space-y-3 rounded-lg bg-white p-4 text-sm shadow-sm ring-1 ring-slate-200">
      <div>
        <h3 className="font-semibold">Audit sampel acak</h3>
        <p className="text-slate-600">
          Periksa sejumlah gambar auto-label acak dari filter aktif di editor. Hasilnya berupa perkiraan persentase label
          yang perlu dikoreksi, sebagai dasar sebelum approve massal.
        </p>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate({ filters: base, size }, { onSuccess: onOpen })
        }}
      >
        <Field label="Jumlah sampel">
          <input type="number" min={1} max={2000} className={`${inputClass} w-28`} value={size} onChange={(e) => setSize(Number(e.target.value))} />
        </Field>
        <Button type="submit" variant="primary" disabled={create.isPending || size < 1}>
          {create.isPending && <Spinner />} Ambil sampel
        </Button>
      </form>
      <ErrorText error={create.error ?? remove.error} />

      {audits.length > 0 && (
        <table className="w-full">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="py-1 font-medium">Audit</th>
              <th className="py-1 font-medium">Dicek</th>
              <th className="py-1 font-medium">Dikoreksi</th>
              <th className="py-1 font-medium">Error</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {audits.map((a) => (
              <tr key={a.id} className="border-t border-slate-100">
                <td className="py-1">
                  #{a.id} <span className="text-xs text-slate-500">{new Date(a.created_at).toLocaleDateString('id-ID')}</span>
                </td>
                <td className="py-1 tabular-nums">
                  {a.summary.checked}/{a.sample_size - a.summary.removed}
                </td>
                <td className="py-1 tabular-nums">{a.summary.corrected}</td>
                <td className="py-1 tabular-nums">{pct(a.summary.error_rate)}</td>
                <td className="py-1 text-right">
                  <Button variant="ghost" onClick={() => onOpen(a)}>
                    Buka
                  </Button>
                  <Button variant="ghost" className="text-rose-600" onClick={() => confirm(`Hapus catatan audit #${a.id}? Label tidak berubah.`) && remove.mutate(a.id)}>
                    Hapus
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** Ringkasan audit aktif di atas galeri (filter ?audit_id=). */
export function AuditBanner({
  projectId,
  auditId,
  onReview,
  onShowPopulation,
  onExit,
}: {
  projectId: number
  auditId: number
  onReview: () => void
  onShowPopulation: (audit: Audit) => void
  onExit: () => void
}) {
  const { data: audits, isLoading } = useAudits(projectId)
  const audit = audits?.find((a) => a.id === auditId)
  if (isLoading) return <Spinner />
  if (!audit) return null
  const s = audit.summary
  const total = audit.sample_size - s.removed
  const done = s.pending === 0

  return (
    <div className="space-y-2 rounded-lg bg-brand-50 p-3 text-sm ring-1 ring-brand-200">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-brand-800">Audit #{audit.id}</span>
        <span className="text-slate-600">
          sampel {audit.sample_size} dari {audit.population} gambar auto-label
        </span>
        <Button variant="ghost" className="ml-auto" onClick={onExit}>
          Keluar dari audit
        </Button>
      </div>
      <div className="h-2 rounded bg-white">
        <div className="h-2 rounded bg-brand-500 transition-all" style={{ width: `${total ? (s.checked / total) * 100 : 0}%` }} />
      </div>
      <p className="text-slate-700">
        {s.checked}/{total} dicek · {s.approved_unchanged} benar · {s.corrected} dikoreksi · perkiraan error{' '}
        <span className="font-semibold">{pct(s.error_rate)}</span>
      </p>
      <p className="text-xs text-slate-600">
        {done
          ? 'Audit selesai. Bila error kecil, tampilkan populasinya lalu approve massal; bila besar, review lebih teliti.'
          : 'Buka editor lalu periksa setiap gambar: Enter untuk approve bila benar, koreksi box bila salah. Navigasi editor hanya di dalam sampel.'}
      </p>
      <div className="flex flex-wrap gap-2">
        {!done && (
          <Button variant="primary" onClick={onReview}>
            Review sampel di editor
          </Button>
        )}
        <Button variant={done ? 'primary' : 'secondary'} onClick={() => onShowPopulation(audit)}>
          Tampilkan populasi audit
        </Button>
      </div>
    </div>
  )
}
