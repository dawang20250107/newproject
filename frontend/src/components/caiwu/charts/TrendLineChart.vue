<script setup>
import { computed } from 'vue'
import BaseChart from './BaseChart.vue'
import { valueAxis, catAxis, gridFor, bottomLegend, axisMoney, endLabel, HIDE_OVERLAP, TOOLTIP } from '../../../utils/chartTheme.js'

const props = defineProps({
  months: { type: Array, default: () => [] },       // array of { month, has_data, by_l1 }
  l1Categories: { type: Array, default: () => [] }, // [{id, name, is_profit_driver}]
  selectedL1Ids: { type: Array, default: () => [] }, // which L1 to show
  height: { type: String, default: '340px' },
})

const COLORS = ['#c96342', '#2e7d32', '#1565c0', '#f57f17', '#6a1b9a', '#00695c']

const option = computed(() => {
  const xLabels = props.months.map(m => `${m.month}月`)
  const series = props.selectedL1Ids.map((l1Id, idx) => {
    const cat = props.l1Categories.find(c => c.id === l1Id)
    return {
      name: cat?.name || `科目${l1Id}`,
      type: 'line',
      smooth: true,
      symbol: 'circle', symbolSize: 6,
      color: COLORS[idx % COLORS.length],
      data: props.months.map(m => {
        if (!m.has_data) return null
        return m.by_l1[l1Id] ?? 0
      }),
      connectNulls: false,
      endLabel: endLabel(p => p.value == null ? '' : axisMoney(p.value),
        { color: COLORS[idx % COLORS.length] }),
      labelLayout: HIDE_OVERLAP,
    }
  })

  return {
    tooltip: {
      trigger: 'axis', ...TOOLTIP,
      formatter(params) {
        let str = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          if (p.value != null) {
            const v = Math.abs(p.value) >= 10000
              ? (p.value / 10000).toFixed(2) + ' 万'
              : p.value.toFixed(2)
            str += `${p.marker}${p.seriesName}：${v}<br/>`
          }
        })
        return str
      },
    },
    legend: bottomLegend(),
    grid: { ...gridFor(xLabels, { threshold: 12 }), right: 56 },
    xAxis: catAxis(xLabels, { threshold: 12 }),
    yAxis: valueAxis({ formatter: axisMoney }),
    series,
  }
})
</script>

<template>
  <BaseChart :option="option" :height="height" />
</template>
