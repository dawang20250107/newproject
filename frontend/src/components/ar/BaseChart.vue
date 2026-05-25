<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, MarkAreaComponent, DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, LineChart, PieChart,
  GridComponent, TooltipComponent, LegendComponent,
  MarkLineComponent, MarkAreaComponent, DataZoomComponent,
  CanvasRenderer])

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: String, default: '320px' },
})
const emit = defineEmits(['click'])

const el = ref(null)
let chart = null
let ro = null

function init() {
  if (!el.value) return
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.on('click', p => emit('click', p))
  if (props.option) chart.setOption(props.option)
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  init()
  ro = new ResizeObserver(resize)
  if (el.value) ro.observe(el.value)
})

onUnmounted(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})

watch(() => props.option, opt => {
  if (!opt || !chart) return
  chart.setOption(opt, { notMerge: false, replaceMerge: ['series'] })
}, { deep: true })
</script>

<template>
  <div ref="el" :style="`width:100%;height:${height}`"></div>
</template>
