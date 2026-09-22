import { Cell, Legend, Pie, PieChart as RPieChart, Tooltip as RTooltip } from 'recharts'
import { formatNumber } from '@/lib/format'
import { ChartState } from './ChartState'
import { CHART_COLORS } from './palette'

export interface PieChartProps<T extends Record<string, unknown>> {
  data: T[]
  nameKey: string
  valueKey: string
  /** Renders as a donut (a hole in the middle) instead of a filled pie
   * -- the spec's "pie/donut" is one chart type with a variant, not two
   * separate components. */
  donut?: boolean
  height?: number
  loading?: boolean
  error?: string
  emptyMessage?: string
  valueFormatter?: (value: number) => string
  colors?: string[]
}

/** Simple part-to-whole. */
export function PieChart<T extends Record<string, unknown>>({
  data,
  nameKey,
  valueKey,
  donut = false,
  height = 300,
  loading,
  error,
  emptyMessage,
  valueFormatter = formatNumber,
  colors = CHART_COLORS,
}: PieChartProps<T>) {
  return (
    <ChartState loading={loading} error={error} empty={data.length === 0} emptyMessage={emptyMessage} height={height}>
      <RPieChart>
        <Pie
          data={data}
          dataKey={valueKey}
          nameKey={nameKey}
          innerRadius={donut ? '55%' : 0}
          outerRadius="80%"
          paddingAngle={donut ? 2 : 0}
        >
          {data.map((_, index) => (
            <Cell key={index} fill={colors[index % colors.length]} />
          ))}
        </Pie>
        <RTooltip
          formatter={(value) => valueFormatter(Number(value))}
          contentStyle={{ background: 'var(--color-ink-800)', border: '1px solid var(--color-ink-600)', borderRadius: 8 }}
          labelStyle={{ color: 'var(--color-gold-100)' }}
        />
        <Legend wrapperStyle={{ color: 'var(--color-gold-100)', fontSize: 12 }} />
      </RPieChart>
    </ChartState>
  )
}
