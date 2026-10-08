import { ApiError, json } from '../api/client'

/** POST ke endpoint yang mengembalikan file, lalu simpan lewat browser. */
export async function downloadPost(path: string, body: object, fallbackName = 'dataset.zip') {
  const res = await fetch(`/api${path}`, { ...json('POST', body), headers: { 'Content-Type': 'application/json' } })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new ApiError(res.status, typeof detail?.detail === 'string' ? detail.detail : res.statusText)
  }
  const name = /filename="?([^"]+)"?/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}
