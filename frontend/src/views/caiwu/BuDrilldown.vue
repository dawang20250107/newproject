<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../../api/caiwu.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const props = defineProps({
  bu: { type: String, required: true },
  year: { type: Number, required: true },
  month: { type: Number, required: true },
})
const emit = defineEmits(['close', 'open-project'])

const loading = ref(true)
const err = ref('')
const subjectRows = ref([])      // L1 科目
const projectRows = ref([])      // 项目损益
const bfSummary = ref(null)

const fmtWan = (v) => fmtCompact(v, { decimals: 1, smallRound: true, dash: '0' })
const fmtPct = (v) => (v == null ? '—' : `${v.toFixed(1)}%`)

// 融合标签配色（与 BusinessFinance 对齐）
const TAG_COLOR = {
  healthy: '#2e7d32', low_margin: '#f9a825', cash_risk: '#fb8c00', critical: '#e53935', idle: '#9e9e9e',
}
const tagColor = (k) => TAG_COLOR[k] || '#9b8070'

// 关键科目高亮：负值红、计算行（毛利/净利）加粗
const subjectClass = (r) => ({
  calc: r.is_calculated,
  neg: (r.amount ?? 0) < 0,
})

const netProfit = computed(() => {
  const r = subjectRows.value.find(x => x.l1_name === '经营净利')
  return r ? r.amount : null
})
const topProjects = computed(() =>
  [...projectRows.value].sort((a, b) => (b.revenue || 0) - (a.revenue || 0)).slice(0, 10))

async function load() {
  loading.value = true; err.value = ''
  try {
    const [rep, bf] = await Promise.allSettled([
      api.get('/report', { params: { bu: props.bu, year: props.year, month: props.month, level: 1 } }),
      ar.businessFinance({ year: props.year, month: props.month, dept: props.bu, group_by: 'project' }),
    ])
    if (rep.status === 'fulfilled') subjectRows.value = rep.value.data?.rows || []
    if (bf.status === 'fulfilled') {
      projectRows.value = bf.value.data?.rows || []
      bfSummary.value = bf.value.data?.summary || null
    }
    if (rep.status === 'rejected' && bf.status === 'rejected') err.value = '加载失败'
  } catch (e) {
    err.value = e?.msg || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div class="dd-mask" @click.self="emit('close')">
    <div class="dd-card">
      <div class="dd-head">
        <div>
          <div class="dd-title">{{ bu }}<span class="dd-period">{{ year }}年{{ month }}月 · 经营下钻</span></div>
          <div v-if="netProfit != null" class="dd-sub">
            经营净利 <b :style="{ color: netProfit < 0 ? '#c62828' : '#2e7d32' }">{{ fmtWan(netProfit) }}</b>
            <template v-if="bfSummary"> · 应收未收 {{ fmtWan(bfSummary.outstanding) }} · 逾期率 {{ fmtPct(bfSummary.overdue_rate) }}</template>
          </div>
        </div>
        <button class="dd-x" @click="emit('close')">✕</button>
      </div>

      <EmptyState v-if="loading" loading />
      <EmptyState v-else-if="err" :error="err" />
      <template v-else>
        <div class="dd-grid">
          <!-- 科目结构 -->
          <div class="dd-block">
            <div class="dd-block-title">科目结构<span class="tip">L1 · 谁在拖累净利</span></div>
            <table class="dd-table">
              <tbody>
                <tr v-for="r in subjectRows" :key="r.l1_id" :class="subjectClass(r)">
                  <td class="l">{{ r.l1_name }}</td>
                  <td class="num">{{ fmtWan(r.amount) }}</td>
                  <td class="mom" :class="{ up: r.mom > 0, down: r.mom < 0 }">
                    <template v-if="r.mom != null">{{ r.mom > 0 ? '+' : '' }}{{ (r.mom * 100).toFixed(0) }}%</template>
                  </td>
                </tr>
                <tr v-if="!subjectRows.length"><td colspan="3" class="empty">暂无已发布科目数据</td></tr>
              </tbody>
            </table>
          </div>

          <!-- 项目损益 -->
          <div class="dd-block">
            <div class="dd-block-title">项目损益<span class="tip">收入 Top · 点击看损益卡</span></div>
            <table class="dd-table">
              <thead>
                <tr><th class="l">项目</th><th>收入</th><th>毛利率</th><th>逾期率</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in topProjects" :key="r.key" class="clickable" @click="emit('open-project', r)">
                  <td class="l" :title="r.label">
                    <span class="tdot" :style="{ background: tagColor(r.tag) }"></span>{{ r.label }}
                  </td>
                  <td class="num">{{ fmtWan(r.revenue) }}</td>
                  <td class="num" :style="{ color: (r.margin_rate ?? 99) < 5 ? '#e65100' : '#2e7d32' }">{{ fmtPct(r.margin_rate) }}</td>
                  <td class="num" :style="{ color: (r.overdue_rate ?? 0) > 30 ? '#c62828' : '#6b5a4a' }">{{ fmtPct(r.overdue_rate) }}</td>
                </tr>
                <tr v-if="!topProjects.length"><td colspan="4" class="empty">暂无项目损益数据</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dd-mask {
  position: fixed; inset: 0; z-index: 1150; background: rgba(60,40,30,.42);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.dd-card {
  width: min(860px, 96vw); max-height: 88vh; overflow-y: auto;
  background: #fdfaf6; border-radius: 16px; padding: 18px 20px;
  box-shadow: 0 18px 50px rgba(60,40,30,.3);
}
.dd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.dd-title { font-size: 18px; font-weight: 800; color: #5f4d3d; }
.dd-period { font-size: 12px; font-weight: 400; color: #9b8070; margin-left: 10px; }
.dd-sub { font-size: 12.5px; color: #8a7665; margin-top: 4px; }
.dd-x { border: none; background: none; font-size: 18px; color: #b3a08f; cursor: pointer; line-height: 1; }
.dd-x:hover { color: #5f4d3d; }
.dd-grid { display: grid; grid-template-columns: 1fr 1.1fr; gap: 16px; }
@media (max-width: 720px) { .dd-grid { grid-template-columns: 1fr; } }
.dd-block-title { font-size: 13.5px; font-weight: 700; color: #5f4d3d; margin-bottom: 6px; }
.dd-block-title .tip { font-size: 11px; font-weight: 400; color: #9b8070; margin-left: 8px; }
.dd-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.dd-table th {
  text-align: right; color: #9b8070; font-weight: 600; padding: 6px 8px;
  border-bottom: 1px solid rgba(180,140,110,.2); white-space: nowrap;
}
.dd-table th.l { text-align: left; }
.dd-table td { padding: 6px 8px; border-bottom: 1px solid rgba(180,140,110,.1); color: #5f4d3d; }
.dd-table td.l { text-align: left; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dd-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.dd-table tr.calc td { font-weight: 700; background: rgba(180,140,110,.05); }
.dd-table tr.neg td.num { color: #c62828; }
.dd-table td.mom { text-align: right; font-size: 11px; color: #b3a08f; }
.dd-table td.mom.up { color: #2e7d32; }
.dd-table td.mom.down { color: #c62828; }
.dd-table tr.clickable { cursor: pointer; }
.dd-table tr.clickable:hover td { background: rgba(201,99,66,.06); }
.tdot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.empty { text-align: center; color: #b3a08f; padding: 16px; }
</style>
