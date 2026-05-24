<script setup>
import { computed } from 'vue'
import BaseChart from './BaseChart.vue'

const props = defineProps({
  waterfall: { type: Array, default: () => [] }, // [{name, value, type}]
  height: { type: String, default: '380px' },
})

const option = computed(() => {
  const items = props.waterfall
  if (!items.length) return {}

  const names = items.map(i => i.name)
  let running = 0

  // For custom bar chart simulation of waterfall:
  // base (invisible) + actual bar
  const baseData = []
  const barData  = []

  items.forEach(item => {
    if (item.type === 'base' || item.type === 'total') {
      baseData.push(0)
      barData.push({
        value: item.value,
        itemStyle: { color: item.type === 'total' ? '#a84e32' : '#d4946a' },
      })
      if (item.type === 'base') running = item.value
      else running = item.value
    } else {
      const base = running
      const delta = item.value
      if (delta >= 0) {
        baseData.push(base)
        barData.push({ value: delta, itemStyle: { color: '#2e7d32' } })
      } else {
        baseData.push(base + delta)
        barData.push({ value: Math.abs(delta), itemStyle: { color: '#c62828' } })
      }
      running += delta
    }
  })

  const fmtAmt = v => {
    const abs = Math.abs(v)
    if (abs >= 100000000) return (v / 100000000).toFixed(2) + '亿'
    if (abs >= 10000) return (v / 10000).toFixed(2) + '万'
    return v.toFixed(0)
  }

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter(params) {
        const bar = params.find(p => p.seriesName === '变动')
        if (!bar) return ''
        const item = items[bar.dataIndex]
        const sign = item.type === 'increase' ? '+' : (item.type === 'decrease' ? '' : '')
        return `<b>${item.name}</b><br/>${sign}${fmtAmt(item.value)}`
      },
    },
    grid: { top: 20, right: 20, bottom: 60, left: 20, containLabel: true },
    xAxis: {
      type: 'category', data: names,
      axisLabel: { color: '#9b8070', fontSize: 11, rotate: names.length > 6 ? 30 : 0 },
      axisLine: { lineStyle: { color: '#d4c4b4' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#9b8070', fontSize: 10, formatter: v => fmtAmt(v) },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } },
    },
    series: [
      {
        name: '基数',
        type: 'bar',
        stack: 'waterfall',
        itemStyle: { color: 'transparent', borderColor: 'transparent' },
        data: baseData,
      },
      {
        name: '变动',
        type: 'bar',
        stack: 'waterfall',
        label: {
          show: true, position: 'top', fontSize: 11, color: '#1a1208',
          formatter: p => {
            const item = items[p.dataIndex]
            if (item.type === 'base' || item.type === 'total') return fmtAmt(item.value)
            const sign = item.type === 'increase' ? '+' : '-'
            return sign + fmtAmt(Math.abs(item.value))
          },
        },
        data: barData,
        barMaxWidth: 48,
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" :height="height" />
</template>
