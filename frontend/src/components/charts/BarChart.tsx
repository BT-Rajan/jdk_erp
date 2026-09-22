import { Bar, BarChart as RBarChart, CartesianGrid, Legend, Tooltip as RTooltip, XAxis, YAxis } from 'recharts'
import { formatNumber } from '@/lib/format'
import { ChartState } from './ChartState'
import { CHART_COLORS } from './palette'
import type { ChartSeries } from './types'

export interface BarChartProps<T extends Record<string, unknown>> {
  data: T[]
  xKey: string
  series: ChartSeries[]
  /** Stacks every series into one bar per category instead of grouping
   * them side by side -- covers "stacked bar" without a separate
   * component (the spec lists it as a variant of bar, not a distinct
   * chart type). */
  stacked?: boolean
  height?: number
  loading?: boolean
  error?: string
  emptyMessage?: string
  valueFormatter?: (value: number) => string
}

/** Comparisons across categories. */
export function BarChart<T extends Record<string, unknown>>({
  data,
  xKey,
  series,
  stacked = false,
  height = 300,
  loading,
  error,
  emptyMessage,
  valueFormatter = formatNumber,
}: BarChartProps<T>) {
  return (
    <ChartState loading={loading} error={error} empty={data.length === 0} emptyMessage={emptyMessage} height={height}>
      <RBarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--color-ink-700)" strokeDasharray="3 3" />
        <XAxis dataKey={xKey} stroke="var(--color-ink-600)" tick={{ fill: 'var(--color-gold-100)', fontSize: 12 }} />
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
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            stackId={stacked ? 'stack' : undefined}
            fill={s.color ?? CHART_COLORS[index % CHART_COLORS.length]}
            radius={stacked ? undefined : [4, 4, 0, 0]}
          />
        ))}
      </RBarChart>
    </ChartState>
  )
}
