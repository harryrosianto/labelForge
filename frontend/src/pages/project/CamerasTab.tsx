import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useAddCamera, useCameras, useDeleteCamera, useJobs, useStartCapture, useTestCamera } from '../../api/hooks'
import type { Camera, CaptureOptions } from '../../api/types'
import { JobProgress } from '../../components/JobProgress'
import { Button, EmptyState, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

function AddCameraForm() {
  const projectId = useProjectId()
  const add = useAddCamera(projectId)
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  return (
    <form
      className="space-y-3 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200"
      onSubmit={(e) => {
        e.preventDefault()
        add.mutate({ name, url }, { onSuccess: () => (setName(''), setUrl('')) })
      }}
    >
      <h2 className="font-semibold">Tambah kamera RTSP</h2>
      <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
        <Field label="Nama">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Dock 1" required />
        </Field>
        <Field label="URL stream" hint="Disimpan terenkripsi; setelah disimpan hanya tampil tersamarkan.">
          <input className={inputClass} type="password" autoComplete="off" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="rtsp://user:password@192.168.1.10:554/Streaming/Channels/101" required />
        </Field>
      </div>
      <ErrorText error={add.error} />
      <Button type="submit" variant="primary" disabled={add.isPending || !name.trim() || !url.trim()}>
        {add.isPending && <Spinner />} Simpan kamera
      </Button>
    </form>
  )
}

function CaptureForm({ camera }: { camera: Camera }) {
  const projectId = useProjectId()
  const start = useStartCapture(projectId)
  const [interval, setIntervalS] = useState(10)
  const [limitMode, setLimitMode] = useState<'duration' | 'frames'>('duration')
  const [minutes, setMinutes] = useState(30)
  const [frames, setFrames] = useState(100)
  const [dedup, setDedup] = useState(6)

  const options: CaptureOptions = {
    interval_s: interval,
    duration_s: limitMode === 'duration' ? minutes * 60 : null,
    max_frames: limitMode === 'frames' ? frames : null,
    dedup_threshold: dedup,
  }
  const estimate = limitMode === 'duration' ? Math.floor((minutes * 60) / interval) + 1 : frames

  return (
    <form
      className="space-y-3 border-t border-slate-100 pt-3"
      onSubmit={(e) => {
        e.preventDefault()
        start.mutate({ cameraId: camera.id, options })
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Simpan frame tiap (detik)">
          <input type="number" min={0.2} step="any" className={inputClass} value={interval} onChange={(e) => setIntervalS(Number(e.target.value))} />
        </Field>
        <Field label="Berhenti setelah">
          <div className="flex gap-1">
            <input type="number" min={1} className={`${inputClass} w-24`} aria-label="Batas"
              value={limitMode === 'duration' ? minutes : frames}
              onChange={(e) => (limitMode === 'duration' ? setMinutes : setFrames)(Number(e.target.value))} />
            <select className={inputClass} value={limitMode} onChange={(e) => setLimitMode(e.target.value as 'duration' | 'frames')}>
              <option value="duration">menit</option>
              <option value="frames">frame</option>
            </select>
          </div>
        </Field>
        <Field label={`Lewati frame mirip (${dedup === 0 ? 'nonaktif' : `ambang ${dedup}`})`}>
          <input type="range" min={0} max={20} className="w-full accent-brand-600" value={dedup} onChange={(e) => setDedup(Number(e.target.value))} />
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={start.isPending || interval < 0.2}>
          {start.isPending && <Spinner />} Mulai capture
        </Button>
        <span className="text-sm text-slate-600">Maks. ± {estimate} frame sebelum frame mirip dilewati</span>
      </div>
      <ErrorText error={start.error} />
    </form>
  )
}

function CameraCard({ camera }: { camera: Camera }) {
  const projectId = useProjectId()
  const test = useTestCamera()
  const remove = useDeleteCamera(projectId)
  const { data: jobs = [] } = useJobs(projectId)
  const [open, setOpen] = useState(false)
  const related = jobs.filter((j) => j.job_type === 'rtsp_capture' && (j.payload as { camera_id?: number })?.camera_id === camera.id)

  return (
    <li className="space-y-3 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{camera.name}</span>
        <code className="truncate text-xs text-slate-500">{camera.url_masked}</code>
        <div className="ml-auto flex gap-1">
          <Button onClick={() => test.mutate(camera.id)} disabled={test.isPending}>
            {test.isPending && <Spinner />} Tes koneksi
          </Button>
          <Button onClick={() => setOpen(!open)}>{open ? 'Tutup' : 'Capture'}</Button>
          <Button variant="ghost" className="text-rose-600"
            onClick={() => confirm(`Hapus kamera "${camera.name}"? Frame yang sudah di-capture tetap ada.`) && remove.mutate(camera.id)}>
            Hapus
          </Button>
        </div>
      </div>
      {test.data && !test.data.ok && <p className="text-sm text-rose-600">{test.data.error}</p>}
      {test.data?.ok && (
        <div className="flex items-start gap-3">
          <img src={test.data.preview} alt={`Frame dari ${camera.name}`} className="w-64 rounded ring-1 ring-slate-200" />
          <p className="text-sm text-emerald-700">
            Terhubung · {test.data.width}×{test.data.height}
          </p>
        </div>
      )}
      <ErrorText error={test.error ?? remove.error} />
      {open && <CaptureForm camera={camera} />}
      {related.length > 0 && (
        <div className="space-y-2">
          {related.slice(0, 3).map((j) => (
            <JobProgress key={j.id} job={j} title="Capture" />
          ))}
          <Link to="../gallery?source_type=rtsp" relative="path" className="text-sm text-brand-700">
            Lihat frame di galeri →
          </Link>
        </div>
      )}
    </li>
  )
}

export function CamerasTab() {
  const projectId = useProjectId()
  const { data: cameras = [], isLoading } = useCameras(projectId)
  return (
    <div className="space-y-4">
      <AddCameraForm />
      {isLoading && <Spinner />}
      {!isLoading && cameras.length === 0 && (
        <EmptyState title="Belum ada kamera">Tambahkan kamera RTSP untuk mengambil frame langsung dari CCTV.</EmptyState>
      )}
      <ul className="space-y-3">
        {cameras.map((c) => (
          <CameraCard key={c.id} camera={c} />
        ))}
      </ul>
      <p className="text-xs text-slate-500">
        Capture berjalan di worker, jadi server harus bisa menjangkau kamera di jaringan. Selama capture berjalan, worker io sibuk.
      </p>
    </div>
  )
}
