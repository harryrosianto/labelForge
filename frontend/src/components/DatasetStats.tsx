import type { DatasetStatsData, LabelClass } from '../api/types'
import { ChartCard, ColumnChart, Heatmap, HBarChart } from './charts'

const pct = (v: number) => `${Math.round(v * 100)}%`

export function DatasetStats({ stats, classes }: { stats: DatasetStatsData; classes?: LabelClass[] }) {
  const colorOf = new Map(classes?.map((c) => [c.name, c.color]))
  const mainSize = stats.image_sizes[0]
  const aspect = mainSize ? mainSize.width / mainSize.height : 16 / 9

  return (
    <div className="space-y-4">
      {stats.warnings.length > 0 && (
        <ul className="space-y-1 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">
          {stats.warnings.map((w) => (
            <li key={w.kind} className="flex gap-2">
              <span aria-hidden>⚠</span>
              <span>
                <span className="sr-only">Peringatan: </span>
                {w.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Jumlah box per class"
          subtitle={`${stats.boxes.toLocaleString('id-ID')} box di ${stats.images.toLocaleString('id-ID')} gambar`}
          table={{
            columns: ['Class', 'Box', 'Gambar', 'Kecil', 'Sedang', 'Besar'],
            rows: stats.classes.map((c) => [c.name, c.boxes, c.images, c.small, c.medium, c.large]),
          }}
        >
          <HBarChart
            rows={stats.classes.map((c) => ({
              label: c.name,
              value: c.boxes,
              swatch: colorOf.get(c.name),
              detail: `${c.name}: ${c.boxes} box di ${c.images} gambar`,
            }))}
          />
        </ChartCard>

        <ChartCard
          title="Ukuran box"
          subtitle="Kategori ukuran mengikuti COCO: kecil < 32×32 px, sedang < 96×96 px"
          table={{
            columns: ['Sisi relatif', 'Box'],
            rows: stats.box_size.relative_side_hist.map((b) => [`${pct(b.from)} - ${pct(b.to)}`, b.count]),
          }}
        >
          <div className="mb-3 grid grid-cols-3 gap-2">
            {(['small', 'medium', 'large'] as const).map((k) => (
              <div key={k} className="rounded-md bg-slate-50 p-2 ring-1 ring-slate-200">
                <p className="text-xs text-slate-500">{{ small: 'Kecil', medium: 'Sedang', large: 'Besar' }[k]}</p>
                <p className="text-lg font-semibold text-ink">{stats.box_size[k].toLocaleString('id-ID')}</p>
              </div>
            ))}
          </div>
          <ColumnChart
            height={110}
            labelEvery={5}
            bins={stats.box_size.relative_side_hist.map((b) => ({
              label: pct(b.from),
              value: b.count,
              tooltip: `Sisi ${pct(b.from)} - ${pct(b.to)} dari gambar`,
            }))}
          />
          <p className="mt-1 text-xs text-slate-500">Sisi relatif = √(luas box / luas gambar)</p>
        </ChartCard>

        <ChartCard
          title="Box per gambar"
          subtitle={`${stats.empty_images.toLocaleString('id-ID')} gambar tanpa objek`}
          table={{ columns: ['Box per gambar', 'Gambar'], rows: stats.boxes_per_image.map((b) => [b.label, b.count]) }}
        >
          <ColumnChart bins={stats.boxes_per_image.map((b) => ({ label: b.label, value: b.count, tooltip: `${b.label} box` }))} />
        </ChartCard>

        <ChartCard
          title="Rasio aspek box (lebar : tinggi)"
          table={{ columns: ['Rasio', 'Box'], rows: stats.aspect_ratio.map((b) => [b.label, b.count]) }}
        >
          <ColumnChart bins={stats.aspect_ratio.map((b) => ({ label: b.label, value: b.count }))} />
        </ChartCard>

        <ChartCard
          title="Posisi pusat box"
          subtitle="Area gelap = banyak objek; area kosong bisa berarti model jarang melihat objek di sana"
          table={{
            columns: ['Baris', 'Kolom', 'Box'],
            rows: stats.heatmap.counts.flatMap((row, r) => row.map((v, c) => [r + 1, c + 1, v])).filter((x) => (x[2] as number) > 0),
          }}
        >
          <Heatmap counts={stats.heatmap.counts} aspect={aspect} />
        </ChartCard>

        <ChartCard
          title="Ukuran gambar"
          table={{ columns: ['Ukuran', 'Gambar'], rows: stats.image_sizes.map((s) => [`${s.width}×${s.height}`, s.count]) }}
        >
          <HBarChart rows={stats.image_sizes.map((s) => ({ label: `${s.width}×${s.height}`, value: s.count }))} />
        </ChartCard>
      </div>
    </div>
  )
}
