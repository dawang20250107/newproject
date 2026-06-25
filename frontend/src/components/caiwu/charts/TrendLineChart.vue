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
    const color = COLORS[idx % COLORS.length]
    const driver = !!cat?.is_profit_driver  // 利润驱动科目加粗强调
    return {
      name: cat?.name || `科目${l1Id}`,
      type: 'line',
      smooth: true,
      symbol: 'circle', symbolSize: driver ? 8 : 5,
      color,
      lineStyle: { width: driver ? 3.5 : 2, shadowColor: 'rgba(0,0,0,0.12)', shadowBlur: 4, shadowOffsetY: 2 },
      // 渐变面积带：线色 → 透明，给折线以"水位"层次感
      areaStyle: { opacity: 1, color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: color + '33' }, { offset: 1, color: color + '03' }] } },
      data: props.months.map(m => {
        if (!m.has_data) return null
        return m.by_l1[l1Id] ?? 0
      }),
      connectNulls: false,
      // 仅给利润驱动科目标注峰值，避免多线杂乱
      markPoint: driver ? { symbol: 'pin', symbolSize: 40,
        itemStyle: { color },
        label: { fontSize: 9, color: '#fff', formatter: p => axisMoney(p.value) },
        data: [{ type: 'max', name: '峰值' }] } : undefined,
      endLabel: endLabel(p => p.value == null ? '' : axisMoney(p.value), { color }),
      labelLayout: HIDE_OVERLAP,
    }
  })

  // 零基线（成本/费用类科目为负，零线帮助快速判正负）
  if (series.length) {
    series[0] = { ...series[0], markLine: { silent: true, symbol: 'none',
      lineStyle: { color: 'rgba(0,0,0,0.18)', type: 'dashed' }, data: [{ yAxis: 0 }] } }
  }
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
