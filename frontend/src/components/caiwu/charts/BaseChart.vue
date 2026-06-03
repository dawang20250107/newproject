<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart, CustomChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent,
} from 'echarts/components'

echarts.use([
  CanvasRenderer, LineChart, BarChart, CustomChart,
  GridComponent, TooltipComponent, LegendComponent,
  TitleComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent,
])

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '340px' },
})

const chartEl = ref(null)
let instance = null
let resizeObserver = null

function initChart() {
  if (!chartEl.value) return
  instance = echarts.init(chartEl.value, null, { renderer: 'canvas' })
  // 关闭入场动画：低配设备上图表渲染更轻快（非侵入，不改传入 option）
  instance.setOption({ ...props.option, animation: false })
  resizeObserver = new ResizeObserver(() => instance?.resize())
  resizeObserver.observe(chartEl.value)
}

watch(() => props.option, (val) => {
  if (instance) instance.setOption({ ...val, animation: false }, { notMerge: true })
}, { deep: true })

onMounted(initChart)

onUnmounted(() => {
  resizeObserver?.disconnect()
  instance?.dispose()
})
</script>

<template>
  <div ref="chartEl" :style="`width:100%;height:${height}`" />
</template>
