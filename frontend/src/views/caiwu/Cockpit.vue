<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import AiAnalysisModal from '../../components/caiwu/AiAnalysisModal.vue'
import api from '../../api/caiwu.js'
import { fmtCompact } from '../../utils/format.js'
import { valueAxis, catAxis, gridFor, bottomLegend, axisMoney } from '../../utils/chartTheme.js'
import { streamAiAnalysis } from '../../utils/aiStream.js'
import { renderMarkdown } from '../../utils/markdown.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const router = useRouter()

// 默认展示上月：当月财务数据通常尚未导入/发布
const year = ref(lastMonthCST().year)
const month = ref(lastMonthCST().month)
const selectedBu = ref('')

const loading = ref(false)
const loadErr = ref('')
const data = ref(null)

// ── AI 全局分析 ───────────────────────────────────────────
const aiText = ref('')
const aiReasoning = ref('')
const aiLoading = ref(false)
const aiErr = ref('')
const aiVisible = ref(false)

const years = Array.from({ length: 5 }, (_, i) => yearCST() - 2 + i)
const months = Array.from({ length: 12 }, (_, i) => i + 1)

const accessibleBus = computed(() => {
  if (auth.isAdmin) return BUSINESS_UNITS
  return (auth.user?.departments || []).filter(d => BUSINESS_UNITS.includes(d))
})

const fmtMoney = (v) => fmtCompact(v, { space: true })
const wan = (v) => (v == null ? '—' : (v / 10000).toFixed(0) + '万')

async function load() {
  loading.value = true
  loadErr.value = ''
  aiText.value = ''
  aiReasoning.value = ''
  aiVisible.value = false
  try {
    const params = { year: year.value, month: month.value }
    if (selectedBu.value) params.bu = selectedBu.value
    const res = await api.get('/cockpit', { params })
    data.value = res.data
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}

const aiScopeLabel = computed(() =>
  `${selectedBu.value || '全集团'} · ${year.value}年${month.value}月`
)
const hasAnalysis = computed(() => !!aiText.value && !aiErr.value)

function viewAnalysis() { aiVisible.value = true }

async function runAiAnalysis() {
  aiLoading.value = true
  aiErr.value = ''
  aiText.value = ''
  aiReasoning.value = ''
  aiVisible.value = true
  try {
    const body = { year: year.value, month: month.value }
    if (selectedBu.value) body.bu = selectedBu.value
    await streamAiAnalysis('/cockpit/ai-analysis/stream', body, {
      onReasoning: d => { aiReasoning.value += d },
      onAnswer: d => { aiText.value += d },
      onError: m => { aiErr.value = m },
    })
  } catch (e) {
    if (!aiErr.value) aiErr.value = e?.message || 'AI 分析失败'
  } finally {
    aiLoading.value = false
  }
}

// ── 业财融合 经营问答 Agent（驾驶舱内置对话）──────────────────────────────────
const chatOpen = ref(false)
const chatInput = ref('')
const chatMessages = ref([])      // {role:'user'|'assistant', content, reasoning?}
const chatStreaming = ref(false)
const chatErr = ref('')
const chatBodyRef = ref(null)
const SUGGESTIONS = [
  '哪个事业部在拖累集团利润？为什么？',
  '本月回款和收入是否匹配？应收风险在哪？',
  '按当前节奏，全年目标能否达成？缺口多大？',
  '给出下月经营改善的 3 条具体建议',
]

function scrollChatSoon() {
  nextTick(() => { const el = chatBodyRef.value; if (el) el.scrollTop = el.scrollHeight })
}

async function sendChat(text) {
  const q = (text ?? chatInput.value).trim()
  if (!q || chatStreaming.value) return
  chatInput.value = ''
  chatErr.value = ''
  chatMessages.value.push({ role: 'user', content: q })
  chatMessages.value.push({ role: 'assistant', content: '', reasoning: '' })
  const asst = chatMessages.value[chatMessages.value.length - 1]   // reactive proxy
  chatStreaming.value = true
  scrollChatSoon()
  try {
    const body = {
      year: year.value, month: month.value,
      messages: chatMessages.value
        .filter(m => m.role === 'user' || (m.role === 'assistant' && m.content))
        .map(m => ({ role: m.role, content: m.content })),
    }
    if (selectedBu.value) body.bu = selectedBu.value
    await streamAiAnalysis('/cockpit/ai-chat/stream', body, {
      onReasoning: d => { asst.reasoning += d; scrollChatSoon() },
      onAnswer: d => { asst.content += d; scrollChatSoon() },
      onError: m => { chatErr.value = m },
    })
  } catch (e) {
    if (!chatErr.value) chatErr.value = e?.message || 'AI 助手暂时不可用'
  } finally {
    chatStreaming.value = false
    if (!asst.content) asst.content = chatErr.value ? `⚠ ${chatErr.value}` : '（未返回内容）'
    scrollChatSoon()
  }
}

function resetChat() { chatMessages.value = []; chatErr.value = '' }

// ── 经营知识库（越用越聪明：长期记忆 + 自我提炼）──────────────────────────────
const panelTab = ref('chat')          // 'chat' | 'kb'
const kbItems = ref([])
const kbLoading = ref(false)
const kbInput = ref('')
const kbScope = ref('')                // '' = 全集团
const kbKind = ref('background')
const toast = ref('')
let toastTimer = null
function showToast(msg) {
  toast.value = msg
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 2200)
}

async function loadKb() {
  kbLoading.value = true
  try {
    const res = await api.get('/cockpit/knowledge', { params: selectedBu.value ? { bu: selectedBu.value } : {} })
    kbItems.value = res.data.items
  } catch (e) { /* silent */ } finally { kbLoading.value = false }
}
async function addKb() {
  const content = kbInput.value.trim()
  if (!content) return
  try {
    await api.post('/cockpit/knowledge', {
      content, scope: kbScope.value || '全集团', kind: kbKind.value, source: 'user',
    })
    kbInput.value = ''
    await loadKb()
    showToast('已加入知识库')
  } catch (e) { showToast(e?.msg || '添加失败') }
}
async function delKb(id) {
  try { await api.delete(`/cockpit/knowledge/${id}`); kbItems.value = kbItems.value.filter(k => k.id !== id) }
  catch (e) { showToast(e?.msg || '删除失败') }
}
async function togglePin(k) {
  try { const res = await api.put(`/cockpit/knowledge/${k.id}`, { pinned: !k.pinned }); Object.assign(k, res.data); await loadKb() }
  catch (e) { showToast(e?.msg || '操作失败') }
}
const distillingIdx = ref(-1)
async function distillToKb(content, idx) {
  if (distillingIdx.value >= 0) return
  distillingIdx.value = idx
  try {
    await api.post('/cockpit/knowledge/distill', { text: content, scope: selectedBu.value || '全集团' })
    showToast('✓ 已提炼并存入知识库')
    if (panelTab.value === 'kb') await loadKb()
  } catch (e) { showToast(e?.msg || '提炼失败') }
  finally { distillingIdx.value = -1 }
}
function openKb() { panelTab.value = 'kb'; loadKb() }

// ── 下钻导航（从对话跳到明细页）──────────────────────────────────────────────
function drillTo(path) { chatOpen.value = false; router.push(path) }
const KIND_LABEL = { insight: '洞察', background: '背景', rule: '口径' }

// ── headline KPI cards ───────────────────────────────────────────────────────
const cards = computed(() => {
  const o = data.value?.overview
  if (!o) return []
  const m = o.month, y = o.ytd
  return [
    { label: '本月收入', value: fmtMoney(m.actual_revenue), color: '#2e7d32',
      mom: m.revenue_mom, yoy: m.revenue_yoy },
    { label: '本月利润', value: fmtMoney(m.actual_profit), color: '#e65100',
      mom: m.profit_mom, yoy: m.profit_yoy, neg: (m.actual_profit ?? 0) < 0 },
    { label: '本月收入达成', value: fmtRate(m.revenue_rate), rate: m.revenue_rate, isRate: true },
    { label: '本月利润达成', value: fmtRate(m.profit_rate), rate: m.profit_rate, isRate: true },
    { label: 'YTD收入达成', value: fmtRate(y.revenue_rate), rate: y.revenue_rate, isRate: true },
    { label: 'YTD利润达成', value: fmtRate(y.profit_rate), rate: y.profit_rate, isRate: true },
  ]
})

function fmtRate(r) { return r == null ? '—' : r.toFixed(1) + '%' }
function rateColor(r) {
  if (r == null) return 'var(--muted)'
  if (r >= 100) return '#2e7d32'
  if (r >= 80) return '#e65100'
  return '#c62828'
}
function chgLabel(v) {
  if (v == null) return '— '
  return (v >= 0 ? '▲ +' : '▼ ') + v.toFixed(1) + '%'
}
function chgClass(v) { return v == null ? 'mom-neutral' : (v >= 0 ? 'mom-up' : 'mom-down') }

// ── 12-month trend (actual bar + target line) ────────────────────────────────
function trendOption(actualKey, targetKey, label, color) {
  const t = data.value?.trend || []
  const x = t.map(m => `${m.month}月`)
  return {
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          const v = p.value == null ? '—' : (Math.abs(p.value) >= 10000 ? (p.value / 10000).toFixed(1) + '万' : p.value.toFixed(0))
          s += `${p.marker}${p.seriesName}：${v}<br/>`
        })
        return s
      },
    },
    legend: bottomLegend(),
    grid: gridFor(x, { threshold: 12 }),
    xAxis: catAxis(x, { threshold: 12 }),
    yAxis: valueAxis({ formatter: axisMoney }),
    series: [
      { name: '实际' + label, type: 'bar', data: t.map(m => m[actualKey]), itemStyle: { color, borderRadius: [4, 4, 0, 0] }, barMaxWidth: 30 },
      { name: '目标' + label, type: 'line', data: t.map(m => m[targetKey]), smooth: true, symbol: 'circle', symbolSize: 6, color: '#c96342', lineStyle: { type: 'dashed', width: 2 } },
    ],
  }
}
const revenueTrend = computed(() => trendOption('actual_revenue', 'target_revenue', '收入', '#2e7d32'))
const profitTrend = computed(() => trendOption('actual_profit', 'target_profit', '利润', '#1565c0'))

// ── per-BU current-month actual (revenue & profit) ───────────────────────────
const buActualOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => {
          const v = p.value == null ? '—' : (Math.abs(p.value) >= 10000 ? (p.value / 10000).toFixed(1) + '万' : p.value.toFixed(0))
          s += `${p.marker}${p.seriesName}：${v}<br/>`
        })
        return s
      },
    },
    legend: bottomLegend(),
    grid: gridFor(names),
    xAxis: catAxis(names),
    yAxis: valueAxis({ formatter: axisMoney }),
    series: [
      { name: '收入', type: 'bar', data: bus.map(b => b.month.actual_revenue), itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
      { name: '利润', type: 'bar', data: bus.map(b => b.month.actual_profit), itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
    ],
  }
})

// ── per-BU YTD achievement rate (revenue & profit) ───────────────────────────
const buRateOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        params.forEach(p => { s += `${p.marker}${p.seriesName}：${p.value == null ? '—' : p.value.toFixed(1) + '%'}<br/>` })
        return s
      },
    },
    legend: bottomLegend(),
    grid: gridFor(names, { nameTop: true }),
    xAxis: catAxis(names),
    yAxis: valueAxis({ name: '达成率%', formatter: '{value}%' }),
    series: [
      { name: 'YTD收入达成', type: 'bar', data: bus.map(b => b.ytd.revenue_rate), itemStyle: { color: '#66bb6a', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#c96342', type: 'dashed' }, data: [{ yAxis: 100, label: { formatter: '100%', color: '#c96342', fontSize: 10 } }] } },
      { name: 'YTD利润达成', type: 'bar', data: bus.map(b => b.ytd.profit_rate), itemStyle: { color: '#42a5f5', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26 },
    ],
  }
})

const hasData = computed(() => (data.value?.bus || []).some(b => b.month.actual_revenue != null || b.month.actual_profit != null))

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <h1>财务驾驶舱</h1>
      <div class="ctrl-row" style="justify-content:flex-end">
        <select v-model="year" class="sel-yr" @change="load">
          <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
        </select>
        <select v-model="month" class="sel-mo" @change="load">
          <option v-for="m in months" :key="m" :value="m">{{ m }} 月</option>
        </select>
        <select v-if="accessibleBus.length > 1" v-model="selectedBu" class="sel-bu" @change="load">
          <option value="">全集团</option>
          <option v-for="bu in accessibleBus" :key="bu" :value="bu">{{ bu }}</option>
        </select>
      </div>
    </div>

    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="data">
      <div :class="{ 'data-reloading': loading }">

      <div v-if="!hasData" class="nodata-banner">
        📭 {{ data.year }}年{{ data.month }}月 · {{ selectedBu || '全集团' }} 暂无已发布数据
      </div>

      <!-- ── headline KPI cards ─────────────────────────────────────────────── -->
      <div class="kpi-grid kpi-6">
        <div v-for="c in cards" :key="c.label" class="kpi-card">
          <div class="label">{{ c.label }}</div>
          <div class="value" :style="`color:${c.isRate ? rateColor(c.rate) : (c.neg ? '#c62828' : c.color)}`">{{ c.value }}</div>
          <div v-if="!c.isRate" class="mom-line">
            <span class="mom-badge" :class="chgClass(c.mom)">{{ chgLabel(c.mom) }} 环比</span>
            <span class="mom-badge" :class="chgClass(c.yoy)">{{ chgLabel(c.yoy) }} 同比</span>
          </div>
          <div v-else class="sub">{{ data.year }}年{{ data.month }}月</div>
        </div>
      </div>

      <!-- ── AI 全局分析 ─────────────────────────────────────────────────────── -->
      <div class="card ai-bar">
        <div class="ai-bar-left">
          <span class="ai-bar-orb">🧭</span>
          <div>
            <div class="ai-bar-title">AI 全局经营分析 <span class="ai-pro-tag">PRO</span></div>
            <div class="ai-bar-scope">站在全集团高度的综合诊断 · {{ aiScopeLabel }} · <span class="ai-time-hint">约需 1–2 分钟</span></div>
          </div>
        </div>
        <div class="ai-bar-actions">
          <button v-if="hasAnalysis" class="btn btn-ghost btn-sm" @click="viewAnalysis">📄 查看分析</button>
          <button class="btn btn-primary btn-sm" :disabled="aiLoading || !hasData" @click="runAiAnalysis">
            {{ aiLoading ? '深度分析中…' : (hasAnalysis ? '↻ 重新分析' : '✨ 生成全局分析') }}
          </button>
        </div>
      </div>

      <!-- ── trend charts ───────────────────────────────────────────────────── -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">收入 · 目标 vs 实际（{{ data.year }}年）</div>
          <BaseChart :option="revenueTrend" height="300px" />
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">利润 · 目标 vs 实际（{{ data.year }}年）</div>
          <BaseChart :option="profitTrend" height="300px" />
        </div>
      </div>

      <!-- ── per-BU charts ──────────────────────────────────────────────────── -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部当月收入 / 利润</div>
          <BaseChart :option="buActualOption" height="320px" />
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部 YTD 达成率</div>
          <BaseChart :option="buRateOption" height="320px" />
        </div>
      </div>
      </div>
    </template>

    <AiAnalysisModal
      :visible="aiVisible"
      :loading="aiLoading"
      :text="aiText"
      :reasoning="aiReasoning"
      :error="aiErr"
      title="AI 全局经营分析"
      :subtitle="aiScopeLabel"
      loading-hint="正在连接更强推理模型，马上开始逐字生成…"
      :estimate-seconds="90"
      @close="aiVisible = false"
      @reanalyze="runAiAnalysis"
    />

    <!-- ── 业财融合 经营问答 Agent（浮窗对话）────────────────────────────────── -->
    <Teleport to="body">
      <button v-if="!chatOpen" class="cfa-launcher" @click="chatOpen = true" title="业财融合 AI 助手">
        <span class="cfa-orb">🤖</span>
        <span class="cfa-launch-text">业财 AI</span>
      </button>

      <Transition name="cfa-slide">
        <div v-if="chatOpen" class="cfa-panel">
          <div class="cfa-glow"></div>
          <div class="cfa-head">
            <div class="cfa-head-l">
              <span class="cfa-head-orb">🤖</span>
              <div>
                <div class="cfa-title">业财融合 · 经营问答<span class="ai-pro-tag">PRO</span></div>
                <div class="cfa-scope">{{ aiScopeLabel }} · 全事业部财务+业务数据</div>
              </div>
            </div>
            <div class="cfa-head-acts">
              <button v-if="panelTab === 'chat' && chatMessages.length" class="cfa-mini" title="清空对话" @click="resetChat">清空</button>
              <button class="cfa-x" title="收起" @click="chatOpen = false">×</button>
            </div>
          </div>

          <!-- 对话 / 知识库 切换 -->
          <div class="cfa-tabs">
            <button :class="['cfa-tab', panelTab === 'chat' ? 'on' : '']" @click="panelTab = 'chat'">💬 对话</button>
            <button :class="['cfa-tab', panelTab === 'kb' ? 'on' : '']" @click="openKb">📚 知识库</button>
            <span class="cfa-tab-hint">{{ panelTab === 'kb' ? '助手会记住这些、越用越懂业务' : '答案可一键提炼入库' }}</span>
          </div>

          <!-- ══ 对话 ══ -->
          <div v-show="panelTab === 'chat'" ref="chatBodyRef" class="cfa-body">
            <div v-if="!chatMessages.length" class="cfa-empty">
              <div class="cfa-empty-orb">🤖</div>
              <div class="cfa-empty-title">我是你的业财融合经营助手</div>
              <div class="cfa-empty-sub">已掌握全集团各事业部的财务与业务数据，并会延续知识库里的历史判断。问我任何经营问题：</div>
              <div class="cfa-sugs">
                <button v-for="s in SUGGESTIONS" :key="s" class="cfa-sug" @click="sendChat(s)">{{ s }}</button>
              </div>
            </div>
            <template v-else>
              <div v-for="(m, i) in chatMessages" :key="i" :class="['cfa-msg', m.role]">
                <div v-if="m.role === 'user'" class="cfa-bubble cfa-user">{{ m.content }}</div>
                <div v-else class="cfa-asst-wrap">
                  <div class="cfa-bubble cfa-asst">
                    <div v-if="m.reasoning && !m.content" class="cfa-reasoning">💭 {{ m.reasoning }}</div>
                    <div v-if="m.content" class="cfa-md" v-html="renderMarkdown(m.content)"></div>
                    <span v-else-if="chatStreaming && i === chatMessages.length - 1 && !m.reasoning" class="cfa-typing">思考中<i>.</i><i>.</i><i>.</i></span>
                  </div>
                  <!-- 答案动作：提炼入库 + 下钻 -->
                  <div v-if="m.content && !(chatStreaming && i === chatMessages.length - 1)" class="cfa-actions">
                    <button class="cfa-act" :disabled="distillingIdx === i" @click="distillToKb(m.content, i)">
                      {{ distillingIdx === i ? '提炼中…' : '📌 提炼入库' }}
                    </button>
                    <span class="cfa-drill-lbl">下钻 →</span>
                    <button class="cfa-drill" @click="drillTo('/caiwu/report')">报表</button>
                    <button class="cfa-drill" @click="drillTo('/caiwu/project-margin')">项目毛利</button>
                    <button class="cfa-drill" @click="drillTo('/ar/records')">应收明细</button>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <!-- ══ 知识库 ══ -->
          <div v-show="panelTab === 'kb'" class="cfa-body">
            <div class="cfa-kb-add">
              <textarea v-model="kbInput" class="cfa-input" rows="2"
                placeholder="补充一条经营背景/口径/规则（如：阔展事业部Q2大客户流失，收入下滑属预期）…"></textarea>
              <div class="cfa-kb-add-row">
                <select v-model="kbScope" class="cfa-kb-sel">
                  <option value="">全集团</option>
                  <option v-for="b in accessibleBus" :key="b" :value="b">{{ b }}</option>
                </select>
                <select v-model="kbKind" class="cfa-kb-sel">
                  <option value="background">背景</option>
                  <option value="rule">口径/规则</option>
                  <option value="insight">洞察</option>
                </select>
                <button class="cfa-send" :disabled="!kbInput.trim()" @click="addKb">添加</button>
              </div>
            </div>
            <div v-if="kbLoading" class="cfa-kb-empty">加载中…</div>
            <div v-else-if="!kbItems.length" class="cfa-kb-empty">
              知识库还是空的。在对话里点「📌 提炼入库」，或在上方手动补充经营背景，<br>助手就会记住、越用越懂你的业务。
            </div>
            <div v-for="k in kbItems" :key="k.id" class="cfa-kb-item" :class="{ pinned: k.pinned }">
              <div class="cfa-kb-meta">
                <span class="cfa-kb-kind" :class="k.kind">{{ KIND_LABEL[k.kind] || k.kind }}</span>
                <span class="cfa-kb-scope">{{ k.scope }}</span>
                <span v-if="k.source === 'ai'" class="cfa-kb-ai">AI提炼</span>
                <span class="cfa-kb-spacer"></span>
                <button class="cfa-kb-btn" :title="k.pinned ? '取消置顶' : '置顶'" @click="togglePin(k)">{{ k.pinned ? '📌' : '📍' }}</button>
                <button class="cfa-kb-btn" title="删除" @click="delKb(k.id)">🗑</button>
              </div>
              <div v-if="k.title" class="cfa-kb-title">{{ k.title }}</div>
              <div class="cfa-kb-content">{{ k.content }}</div>
            </div>
          </div>

          <div v-show="panelTab === 'chat'" class="cfa-input-row">
            <textarea v-model="chatInput" class="cfa-input" rows="1"
              placeholder="问问经营情况…（Enter 发送，Shift+Enter 换行）"
              :disabled="chatStreaming"
              @keydown.enter.exact.prevent="sendChat()"></textarea>
            <button class="cfa-send" :disabled="chatStreaming || !chatInput.trim()" @click="sendChat()">
              {{ chatStreaming ? '…' : '发送' }}
            </button>
          </div>

          <Transition name="cfa-toast">
            <div v-if="toast" class="cfa-toast">{{ toast }}</div>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.kpi-6 { grid-template-columns: repeat(6, 1fr) !important; }
@media (max-width: 1100px) { .kpi-6 { grid-template-columns: repeat(3, 1fr) !important; } }
@media (max-width: 560px) { .kpi-6 { grid-template-columns: repeat(2, 1fr) !important; } }

.nodata-banner {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 16px; margin-bottom: 16px;
  background: rgba(180,140,110,.08); border: 1px dashed var(--border);
  border-radius: 12px; font-size: 13px; color: var(--muted);
}

.mom-line { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.mom-badge {
  display: inline-block; font-size: 11px; font-weight: 600;
  padding: 2px 7px; border-radius: 10px;
}
.mom-up { background: rgba(46,125,50,.10); color: #2e7d32; }
.mom-down { background: rgba(198,40,40,.10); color: #c62828; }
.mom-neutral { background: rgba(120,120,120,.08); color: var(--muted); font-weight: 400; }

.chart-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px;
}
@media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }

/* ── AI bar ───────────────────────────────────────────────────────────────── */
.ai-bar {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 12px; padding: 14px 18px; margin-top: 16px;
  background: linear-gradient(120deg, rgba(201,99,66,0.06), rgba(122,159,212,0.06));
  border: 1px solid rgba(201,99,66,0.16);
}
.ai-bar-left { display: flex; align-items: center; gap: 12px; }
.ai-bar-orb {
  font-size: 22px; filter: drop-shadow(0 0 6px rgba(201,99,66,0.45));
}
.ai-bar-title { font-size: 14px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 6px; }
.ai-pro-tag {
  font-size: 10px; font-weight: 800; letter-spacing: .05em;
  padding: 1px 6px; border-radius: 6px; color: #fff;
  background: linear-gradient(135deg, #c96342, #e8855a);
}
.ai-bar-scope { font-size: 12px; color: var(--muted); margin-top: 1px; }
.ai-time-hint { color: var(--primary); font-weight: 600; }
.ai-bar-actions { display: flex; gap: 8px; }

/* ── 业财融合 经营问答 Agent ───────────────────────────────────────────────── */
.cfa-launcher {
  position: fixed; right: 24px; bottom: 24px; z-index: 1200;
  display: flex; align-items: center; gap: 8px;
  padding: 12px 18px; border: none; border-radius: 30px; cursor: pointer;
  background: linear-gradient(135deg, #c96342, #e8855a 60%, #e8a84a);
  color: #fff; font-size: 14px; font-weight: 700;
  box-shadow: 0 8px 26px rgba(201,99,66,0.45);
  transition: transform .16s, box-shadow .16s;
}
.cfa-launcher:hover { transform: translateY(-2px); box-shadow: 0 12px 32px rgba(201,99,66,0.55); }
.cfa-orb { font-size: 18px; }
.cfa-launch-text { letter-spacing: .02em; }

.cfa-panel {
  position: fixed; top: 0; right: 0; bottom: 0; z-index: 1201;
  width: min(440px, 96vw); display: flex; flex-direction: column;
  background: linear-gradient(180deg, #fffaf3, #fdf4ec);
  box-shadow: -12px 0 40px rgba(80,40,20,0.22);
  border-left: 1px solid rgba(201,99,66,0.18);
}
.cfa-glow {
  position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: linear-gradient(180deg, #c96342, #e8a05a, #7a9fd4);
  background-size: 100% 300%; animation: cfaGlow 6s ease infinite;
}
@keyframes cfaGlow { 0%,100% { background-position: 0 0; } 50% { background-position: 0 100%; } }

.cfa-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 18px 13px; border-bottom: 1px solid rgba(201,99,66,0.12);
}
.cfa-head-l { display: flex; align-items: center; gap: 11px; }
.cfa-head-orb { font-size: 24px; filter: drop-shadow(0 0 6px rgba(201,99,66,0.45)); }
.cfa-title { font-size: 15px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 6px; }
.cfa-scope { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.cfa-head-acts { display: flex; align-items: center; gap: 6px; }
.cfa-mini { background: none; border: 1px solid rgba(0,0,0,0.12); border-radius: 7px; font-size: 12px; color: var(--muted); padding: 3px 9px; cursor: pointer; }
.cfa-mini:hover { color: var(--primary); border-color: var(--primary); }
.cfa-x { background: none; border: none; font-size: 24px; line-height: 1; color: var(--muted); cursor: pointer; padding: 0 4px; }

.cfa-body { flex: 1; overflow-y: auto; padding: 16px 16px 8px; }

.cfa-empty { text-align: center; padding: 24px 8px; }
.cfa-empty-orb { font-size: 40px; margin-bottom: 8px; }
.cfa-empty-title { font-size: 15px; font-weight: 700; color: var(--text); }
.cfa-empty-sub { font-size: 12.5px; color: var(--muted); margin: 6px 0 16px; line-height: 1.6; }
.cfa-sugs { display: flex; flex-direction: column; gap: 8px; }
.cfa-sug {
  text-align: left; padding: 10px 13px; border-radius: 11px; cursor: pointer;
  border: 1px solid rgba(201,99,66,0.2); background: rgba(255,255,255,0.7);
  font-size: 12.5px; color: var(--text); transition: all .14s;
}
.cfa-sug:hover { border-color: var(--primary); background: rgba(201,99,66,0.07); color: var(--primary); }

.cfa-msg { margin-bottom: 14px; display: flex; }
.cfa-msg.user { justify-content: flex-end; }
.cfa-bubble { max-width: 88%; border-radius: 14px; padding: 10px 13px; font-size: 13px; line-height: 1.7; }
.cfa-user { background: linear-gradient(135deg, #c96342, #e8855a); color: #fff; border-bottom-right-radius: 4px; white-space: pre-wrap; }
.cfa-asst { background: rgba(255,255,255,0.92); border: 1px solid rgba(0,0,0,0.06); color: var(--text); border-bottom-left-radius: 4px; }
.cfa-reasoning { font-size: 12px; color: #6b7a8c; line-height: 1.6; white-space: pre-wrap; }
.cfa-typing i { animation: cfaBlink 1.2s infinite; opacity: .3; }
.cfa-typing i:nth-child(2) { animation-delay: .2s; }
.cfa-typing i:nth-child(3) { animation-delay: .4s; }
@keyframes cfaBlink { 0%,100% { opacity: .3; } 50% { opacity: 1; } }

/* markdown inside assistant bubble */
.cfa-md :deep(p) { margin: 0 0 8px; }
.cfa-md :deep(p:last-child) { margin-bottom: 0; }
.cfa-md :deep(strong) { color: var(--primary); font-weight: 700; }
.cfa-md :deep(.md-h) { font-weight: 800; margin: 10px 0 6px; }
.cfa-md :deep(.md-h1) { font-size: 15px; }
.cfa-md :deep(.md-h2) { font-size: 14px; color: var(--primary); }
.cfa-md :deep(.md-h3), .cfa-md :deep(.md-h4) { font-size: 13px; color: #8a4b34; }
.cfa-md :deep(.md-list) { margin: 4px 0 8px; padding-left: 19px; }
.cfa-md :deep(.md-list li) { margin: 3px 0; }
.cfa-md :deep(code) { background: rgba(201,99,66,0.1); color: #a8442a; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.cfa-md :deep(hr) { border: none; border-top: 1px solid rgba(0,0,0,0.08); margin: 10px 0; }

.cfa-input-row { display: flex; gap: 8px; align-items: flex-end; padding: 12px 16px 16px; border-top: 1px solid rgba(201,99,66,0.12); }
.cfa-input {
  flex: 1; resize: none; max-height: 120px; min-height: 38px;
  border: 1px solid rgba(0,0,0,0.12); border-radius: 11px; padding: 9px 12px;
  font-size: 13px; font-family: inherit; line-height: 1.5; outline: none; background: #fff;
}
.cfa-input:focus { border-color: var(--primary); }
.cfa-send {
  flex-shrink: 0; height: 38px; padding: 0 18px; border: none; border-radius: 11px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 13px; font-weight: 700;
}
.cfa-send:disabled { opacity: .5; cursor: not-allowed; }

.cfa-slide-enter-active, .cfa-slide-leave-active { transition: transform .28s cubic-bezier(0.2,0.8,0.3,1); }
.cfa-slide-enter-from, .cfa-slide-leave-to { transform: translateX(100%); }

/* tabs */
.cfa-tabs { display: flex; align-items: center; gap: 6px; padding: 8px 16px 0; }
.cfa-tab { border: none; background: rgba(0,0,0,0.05); border-radius: 8px 8px 0 0; padding: 6px 14px; font-size: 12.5px; color: var(--muted); cursor: pointer; }
.cfa-tab.on { background: rgba(201,99,66,0.1); color: var(--primary); font-weight: 700; }
.cfa-tab-hint { font-size: 10.5px; color: var(--muted); margin-left: auto; }

/* assistant answer actions */
.cfa-asst-wrap { width: 100%; }
.cfa-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 6px 0 0 2px; }
.cfa-act { border: 1px solid rgba(201,99,66,0.3); background: rgba(201,99,66,0.06); color: var(--primary); border-radius: 7px; font-size: 11.5px; padding: 3px 9px; cursor: pointer; font-weight: 600; }
.cfa-act:disabled { opacity: .5; cursor: default; }
.cfa-drill-lbl { font-size: 11px; color: var(--muted); margin-left: 4px; }
.cfa-drill { border: 1px solid rgba(0,0,0,0.12); background: #fff; color: var(--muted); border-radius: 7px; font-size: 11.5px; padding: 3px 9px; cursor: pointer; }
.cfa-drill:hover { color: var(--primary); border-color: var(--primary); }

/* knowledge base */
.cfa-kb-add { background: rgba(255,255,255,0.7); border: 1px solid rgba(0,0,0,0.08); border-radius: 12px; padding: 10px; margin-bottom: 14px; }
.cfa-kb-add-row { display: flex; gap: 6px; margin-top: 8px; }
.cfa-kb-sel { height: 34px; border: 1px solid rgba(0,0,0,0.12); border-radius: 9px; background: #fff; font-size: 12px; color: var(--text); padding: 0 8px; }
.cfa-kb-add-row .cfa-send { flex: 1; }
.cfa-kb-empty { text-align: center; color: var(--muted); font-size: 12.5px; line-height: 1.7; padding: 24px 8px; }
.cfa-kb-item { background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.07); border-radius: 11px; padding: 10px 12px; margin-bottom: 10px; }
.cfa-kb-item.pinned { border-color: rgba(201,99,66,0.35); background: rgba(201,99,66,0.04); }
.cfa-kb-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.cfa-kb-kind { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 6px; color: #fff; background: #7a9fd4; }
.cfa-kb-kind.insight { background: #2e7d32; }
.cfa-kb-kind.rule { background: #8a4b34; }
.cfa-kb-scope { font-size: 11px; color: var(--muted); }
.cfa-kb-ai { font-size: 10px; color: var(--primary); border: 1px solid rgba(201,99,66,0.3); border-radius: 5px; padding: 0 5px; }
.cfa-kb-spacer { flex: 1; }
.cfa-kb-btn { background: none; border: none; cursor: pointer; font-size: 13px; padding: 0 2px; opacity: .75; }
.cfa-kb-btn:hover { opacity: 1; }
.cfa-kb-title { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 2px; }
.cfa-kb-content { font-size: 12.5px; color: var(--text); line-height: 1.6; }

/* toast */
.cfa-toast { position: absolute; left: 50%; bottom: 80px; transform: translateX(-50%); background: rgba(30,18,10,0.9); color: #fff; font-size: 12.5px; padding: 8px 16px; border-radius: 20px; white-space: nowrap; z-index: 5; }
.cfa-toast-enter-active, .cfa-toast-leave-active { transition: opacity .2s, transform .2s; }
.cfa-toast-enter-from, .cfa-toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(6px); }
</style>
