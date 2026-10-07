import { Link, useParams } from 'react-router-dom'

// Annotation editor dikerjakan di tahap (e). Sementara: tampilkan gambar & tautan kembali.
export function EditorPage() {
  const { projectId, imageId } = useParams()
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <Link to={`/projects/${projectId}/gallery`} className="text-sm text-indigo-600">
        ← Kembali ke galeri
      </Link>
      <p className="text-slate-600">Editor anotasi tersedia di tahap berikutnya.</p>
      <img src={`/api/images/${imageId}/file`} alt="" className="w-full rounded-lg" />
    </div>
  )
}
