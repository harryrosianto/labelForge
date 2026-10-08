import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { keys, uploadVideo, useDeleteVideo, useExtractPreview, useJobs, useStartExtract, useVideos } from '../../api/hooks'
import type { ExtractOptions, Video } from '../../api/types'
import { JobProgress } from '../../components/JobProgress'
import { Button, ErrorText, Field, inputClass, Spinner } from '../../components/ui'
import { useProjectId } from '../../lib/route'

const fmtDuration = (s: number | null) => {
  if (!s) return '-'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`
}

function ExtractForm({ video }: { video: Video }) {
  const projectId = useProjectId()
  const start = useStartExtract(projectId)
  const [mode, setMode] = useState<'every_s' | 'fps'>('every_s')
  const [rate, setRate] = useState(1)
  const [startS, setStartS] = useState(0)
  const [endS, setEndS] = useState<number | ''>('')
  const [maxFrames, setMaxFrames] = useState(500)
  const [dedup, setDedup] = useState(6)

  const options: ExtractOptions = {
    every_s: mode === 'every_s' ? rate : null,
    fps: mode === 'fps' ? rate : null,
    start_s: startS,
    end_s: endS === '' ? null : endS,
    max_frames: maxFrames,
    dedup_threshold: dedup,
  }
  const valid = rate > 0 && (endS === '' || endS > startS)
  const preview = useExtractPreview(video.id, options, valid)

  return (
    <form
      className="space-y-3 border-t border-slate-100 pt-3"
      onSubmit={(e) => {
        e.preventDefault()
        start.mutate({ videoId: video.id, options })
      }}
    >
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Ambil frame">
          <div className="flex gap-1">
            <input type="number" min={0.01} step="any" className={`${inputClass} w-20`} value={rate}
              onChange={(e) => setRate(Number(e.target.value))} aria-label="Nilai interval" />
            <select className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as 'every_s' | 'fps')}>
              <option value="every_s">detik sekali</option>
              <option value="fps">frame/detik</option>
            </select>
          </div>
        </Field>
        <Field label="Mulai (detik)">
          <input type="number" min={0} className={inputClass} value={startS} onChange={(e) => setStartS(Number(e.target.value))} />
        </Field>
        <Field label="Sampai (detik)" hint="Kosong = sampai akhir">
          <input type="number" min={0} className={inputClass} value={endS}
            onChange={(e) => setEndS(e.target.value === '' ? '' : Number(e.target.value))} />
        </Field>
        <Field label="Maks. frame">
          <input type="number" min={1} className={inputClass} value={maxFrames} onChange={(e) => setMaxFrames(Number(e.target.value))} />
        </Field>
      </div>
      <label className="block text-sm">
        <span className="flex justify-between">
          <span className="text-slate-700">Lewati frame yang mirip frame sebelumnya</span>
          <span className="text-slate-500">{dedup === 0 ? 'nonaktif' : `ambang ${dedup}`}</span>
        </span>
        <input type="range" min={0} max={20} className="w-full accent-brand-600" value={dedup} onChange={(e) => setDedup(Number(e.target.value))} />
        <span className="text-xs text-slate-500">Makin besar, makin banyak frame serupa yang dilewati. Berguna untuk CCTV yang jarang berubah.</span>
      </label>
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={!valid || start.isPending}>
          {start.isPending && <Spinner />} Ekstrak frame
        </Button>
        {preview.data && <span className="text-sm text-slate-600">± {preview.data.frames} frame diambil sebelum frame mirip dilewati</span>}
      </div>
      <ErrorText error={start.error ?? preview.error} />
    </form>
  )
}

function VideoCard({ video }: { video: Video }) {
  const projectId = useProjectId()
  const remove = useDeleteVideo(projectId)
  const { data: jobs = [] } = useJobs(projectId)
  const [open, setOpen] = useState(false)
  const related = jobs.filter((j) => j.job_type === 'video_extract' && (j.payload as { video_id?: number })?.video_id === video.id)

  return (
    <li className="space-y-3 rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{video.original_filename}</span>
        <span className="text-sm text-slate-500">
          {fmtDuration(video.duration_s)} · {video.width}×{video.height} · {video.fps} fps
        </span>
        <Button className="ml-auto" onClick={() => setOpen(!open)}>
          {open ? 'Tutup' : 'Ekstrak frame'}
        </Button>
        <Button
          variant="ghost"
          className="text-rose-600"
          onClick={() => confirm(`Hapus file video "${video.original_filename}"? Frame yang sudah diekstrak tetap ada.`) && remove.mutate(video.id)}
        >
          Hapus
        </Button>
      </div>
      {open && <ExtractForm video={video} />}
      {related.length > 0 && (
        <div className="space-y-2">
          {related.slice(0, 3).map((j) => (
            <JobProgress key={j.id} job={j} title="Ekstraksi frame" />
          ))}
          <Link to="../gallery?source_type=video" relative="path" className="text-sm text-brand-700">
            Lihat frame di galeri →
          </Link>
        </div>
      )}
      <ErrorText error={remove.error} />
    </li>
  )
}

export function VideoPanel() {
  const projectId = useProjectId()
  const qc = useQueryClient()
  const { data: videos = [], isLoading } = useVideos(projectId)
  const input = useRef<HTMLInputElement>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)

  async function upload(file: File | undefined) {
    if (!file) return
    setError(null)
    setProgress(0)
    try {
      await uploadVideo(projectId, file, setProgress)
      qc.invalidateQueries({ queryKey: [...keys.project(projectId), 'videos'] })
    } catch (e) {
      setError(e)
    } finally {
      setProgress(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col items-center rounded-lg border-2 border-dashed border-slate-300 bg-white p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => (e.preventDefault(), upload(e.dataTransfer.files[0]))}>
        <p className="text-lg font-medium">Upload video</p>
        <p className="mt-1 text-sm text-slate-500">MP4, AVI, MKV, MOV, WEBM. Frame diambil berkala dan masuk sebagai gambar belum berlabel.</p>
        {progress !== null ? (
          <div className="mt-4 w-64">
            <div className="mb-1 flex items-center justify-center gap-2 text-sm">
              <Spinner /> {progress < 1 ? `Mengunggah ${Math.round(progress * 100)}%` : 'Membaca video…'}
            </div>
            <div className="h-2 rounded bg-slate-100">
              <div className="h-2 rounded bg-brand-500" style={{ width: `${progress * 100}%` }} />
            </div>
          </div>
        ) : (
          <Button variant="primary" className="mt-4" onClick={() => input.current?.click()}>
            Pilih video
          </Button>
        )}
        <input ref={input} type="file" accept=".mp4,.avi,.mkv,.mov,.m4v,.webm,.mpg,.mpeg" hidden
          onChange={(e) => (upload(e.target.files?.[0]), (e.target.value = ''))} />
      </div>
      <ErrorText error={error} />
      {isLoading && <Spinner />}
      <ul className="space-y-3">
        {videos.map((v) => (
          <VideoCard key={v.id} video={v} />
        ))}
      </ul>
    </div>
  )
}
