import {
  CartesianGrid,
  Legend,
  Line,
  LineChart as RLineChart,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatNumber } from '@/lib/format'
import { ChartState } from './ChartState'
import { CHART_COLORS } from './palette'
import type { ChartSeries } from './types'

export interface LineChartProps<T extends Record<string, unknown>> {
  data: T[]
  xKey: string
  series: ChartSeries[]
  height?: number
  loading?: boolean
  error?: string
  emptyMessage?: string
  valueFormatter?: (value: number) => string
  xFormatter?: (value: unknown) => string
}

/** Trends over time. Modules pass data/config only -- never render
 * recharts directly, so the chart's look and its loading/empty/error
 * behaviour stay consistent everywhere it's used. */
export function LineChart<T extends Record<string, unknown>>({
  data,
  xKey,
  series,
  height = 300,
  loading,
  error,
  emptyMessage,
  valueFormatter = formatNumber,
  xFormatter,
}: LineChartProps<T>) {
  return (
    <ChartState loading={loading} error={error} empty={data.length === 0} emptyMessage={emptyMessage} height={height}>
      <RLineChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--color-ink-700)" strokeDasharray="3 3" />
        <XAxis
          dataKey={xKey}
          tickFormatter={xFormatter}
          stroke="var(--color-ink-600)"
          tick={{ fill: 'var(--color-gold-100)', fontSize: 12 }}
        />
        <YAxis
          width={80}
          tickFormatter={(value: number) => valueFormatter(value)}
          stroke="var(--color-ink-600)"
          tick={{ fill: 'var(--color-gold-100)', fontSize: 12 }}
        />
        <RTooltip
          formatter={(value) => valueFormatter(Number(value))}
          contentStyle={{ background: 'var(--color-ink-800)', border: '1px solid var(--color-ink-600)', borderRadius: 8 }}
          labelStyle={{ color: 'var(--color-gold-100)' }}
        />
        <Legend wrapperStyle={{ color: 'var(--color-gold-100)', fontSize: 12 }} />
        {series.map((s, index) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stroke={s.color ?? CHART_COLORS[index % CHART_COLORS.length]}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </RLineChart>
    </ChartState>
  )
}
