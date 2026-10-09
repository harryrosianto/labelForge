/**
 * Grafik ringan berbasis SVG/HTML (tanpa library chart).
 * Spesifikasi: satu seri = satu hue (brand), batang <= 24px dengan ujung data membulat 4px
 * dan pangkal persegi, celah 2px antar batang, garis bantu tipis, teks memakai warna tinta,
 * tooltip saat disorot, dan tampilan tabel sebagai alternatif.
 */
import { useState, type ReactNode } from 'react'

const BRAND = 'var(--color-brand-500)'
// Ramp sekuensial tosca (terang → gelap) untuk heatmap.
const SEQUENTIAL = ['#e6f7f6', '#c0ebe9', '#8ddad7', '#4cc5c1', '#17b6b2', '#009a97', '#007d7a', '#00615f', '#004846']

const fmt = (n: number) => n.toLocaleString('id-ID')

export function ChartCard({
  title,
  subtitle,
  table,
  children,
}: {
  title: string
  subtitle?: string
  table: { columns: string[]; rows: (string | number)[][] }
  children: ReactNode
}) {
  const [asTable, setAsTable] = useState(false)
  return (
    <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200">
      <div className="mb-3 flex items-start gap-2">
        <div className="mr-auto">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        <button type="button" className="text-xs text-brand-700 hover:underline" onClick={() => setAsTable(!asTable)}>
          {asTable ? 'Lihat grafik' : 'Lihat tabel'}
        </button>
      </div>
      {asTable ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              {table.columns.map((c, i) => (
                <th key={c} className={`py-1 font-medium ${i > 0 ? 'text-right' : ''}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100">
                {r.map((v, j) => (
                  <td key={j} className={`py-1 ${j > 0 ? 'text-right tabular-nums' : ''}`}>
                    {typeof v === 'number' ? fmt(v) : v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        children
      )}
    </section>
  )
}

/** Batang horizontal: satu baris per kategori, nilai di ujung batang. */
export function HBarChart({
  rows,
}: {
  rows: { label: string; value: number; swatch?: string; detail?: string }[]
}) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <ul className="space-y-0.5">
      {rows.map((r) => (
        <li key={r.label} className="group flex items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-50" title={r.detail}>
          <span className="flex w-32 shrink-0 items-center gap-1.5 truncate text-sm text-slate-700">
            {r.swatch && <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: r.swatch }} />}
            <span className="truncate">{r.label}</span>
          </span>
          <span className="relative flex h-4 flex-1 items-center">
            <span
              className="h-3.5 rounded-r"
              style={{ width: `${(r.value / max) * 100}%`, minWidth: r.value ? 2 : 0, background: BRAND }}
            />
            <span className="ml-1.5 text-xs tabular-nums text-slate-600">{fmt(r.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Kolom vertikal (histogram / distribusi). */
export function ColumnChart({
  bins,
  height = 140,
  labelEvery = 1,
}: {
  bins: { label: string; value: number; tooltip?: string }[]
  height?: number
  labelEvery?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...bins.map((b) => b.value))
  const slot = 100 / bins.length
  return (
    <div className="relative">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} role="img">
        {/* garis dasar & garis bantu tengah */}
        <line x1="0" x2="100" y1={height - 0.5} y2={height - 0.5} stroke="#cbd5e1" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        <line x1="0" x2="100" y1={height / 2} y2={height / 2} stroke="#eef2f6" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {bins.map((b, i) => {
          const h = (b.value / max) * (height - 4)
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* area sentuh selebar slot, lebih besar dari batangnya */}
              <rect x={i * slot} y={0} width={slot} height={height} fill="transparent" />
              {b.value > 0 && (
                <rect
                  x={i * slot + slot * 0.08}
                  y={height - h}
                  width={slot * 0.84}
                  height={h}
                  rx={Math.min(1.2, slot * 0.2)}
                  fill={BRAND}
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
            </g>
          )
        })}
      </svg>
      <div className="mt-1 flex text-[10px] text-slate-500">
        {bins.map((b, i) => (
          <span key={i} className="truncate text-center" style={{ width: `${slot}%` }}>
            {i % labelEvery === 0 ? b.label : ''}
          </span>
        ))}
      </div>
      <div className="absolute right-0 top-0 text-[10px] text-slate-400">{fmt(max)}</div>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded bg-ink px-2 py-1 text-xs whitespace-nowrap text-white shadow"
          style={{ left: `${(hover + 0.5) * slot}%` }}
        >
          {bins[hover].tooltip ?? bins[hover].label}: <b>{fmt(bins[hover].value)}</b>
        </div>
      )}
    </div>
  )
}

/** Heatmap grid (counts[row][col]) dengan ramp sekuensial tosca. */
export function Heatmap({ counts, aspect = 16 / 9 }: { counts: number[][]; aspect?: number }) {
  const [hover, setHover] = useState<[number, number] | null>(null)
  const n = counts.length
  const max = Math.max(1, ...counts.flat())
  const color = (v: number) => (v === 0 ? '#f8fafc' : SEQUENTIAL[Math.min(SEQUENTIAL.length - 1, Math.ceil((v / max) * SEQUENTIAL.length) - 1)])
  return (
    <div>
      <div className="relative w-full overflow-hidden rounded ring-1 ring-slate-200" style={{ aspectRatio: aspect }}>
        <svg viewBox={`0 0 ${n} ${n}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" role="img">
          {counts.map((row, r) =>
            row.map((v, c) => (
              <rect
                key={`${r}-${c}`}
                x={c + 0.04}
                y={r + 0.04}
                width={0.92}
                height={0.92}
                fill={color(v)}
                onMouseEnter={() => setHover([r, c])}
                onMouseLeave={() => setHover(null)}
              />
            )),
          )}
        </svg>
        {hover && (
          <div className="pointer-events-none absolute left-2 top-2 rounded bg-ink px-2 py-1 text-xs text-white shadow">
            {fmt(counts[hover[0]][hover[1]])} pusat box di area ini
          </div>
        )}
      </div>
      <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
        <span>0</span>
        <span className="flex h-2 flex-1 overflow-hidden rounded">
          {SEQUENTIAL.map((c) => (
            <span key={c} className="flex-1" style={{ background: c }} />
          ))}
        </span>
        <span>{fmt(max)}</span>
      </div>
    </div>
  )
}
