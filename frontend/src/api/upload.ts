/** Upload satu file dengan progress (fetch belum mendukung progress upload). */
export function uploadWithProgress<T>(path: string, file: File, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api${path}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      let body: { detail?: unknown } | null = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else reject(new Error(typeof body?.detail === 'string' ? body.detail : `${xhr.status} ${xhr.statusText}`))
    }
    xhr.onerror = () => reject(new Error('Upload gagal (koneksi terputus)'))
    const form = new FormData()
    form.append('file', file, file.name)
    xhr.send(form)
  })
}
