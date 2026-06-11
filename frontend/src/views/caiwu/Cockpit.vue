<script setup>
import { ref, computed, onMounted, nextTick, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { useAuthStore } from '../../stores/auth.js'
import { BUSINESS_UNITS, yearCST, lastMonthCST } from '../../constants.js'
import BaseChart from '../../components/caiwu/charts/BaseChart.vue'
import AiAnalysisModal from '../../components/caiwu/AiAnalysisModal.vue'
import api from '../../api/caiwu.js'
import ar from '../../api/ar.js'
import { fmtCompact } from '../../utils/format.js'
import { valueAxis, catAxis, gridFor, bottomLegend, axisMoney, topLabel, endLabel, HIDE_OVERLAP, TOOLTIP } from '../../utils/chartTheme.js'
import { streamAiAnalysis } from '../../utils/aiStream.js'
import { renderMarkdown } from '../../utils/markdown.js'
import EmptyState from '../../components/EmptyState.vue'

// 驾驶舱内嵌分析面板（懒加载，首次切到对应 Tab 才载入）
const ChartsPanel = defineAsyncComponent(() => import('./Charts.vue'))
const ARAnalyticsPanel = defineAsyncComponent(() => import('../ar/ARAnalytics.vue'))
const CashflowPanel = defineAsyncComponent(() => import('../ar/Cashflow.vue'))
const BusinessFinancePanel = defineAsyncComponent(() => import('./BusinessFinance.vue'))
const ForecastPanel = defineAsyncComponent(() => import('./Forecast.vue'))
const ActionPanel = defineAsyncComponent(() => import('./ActionPanel.vue'))
const TargetDecompPanel = defineAsyncComponent(() => import('./TargetDecomp.vue'))
const CashPoolPanel = defineAsyncComponent(() => import('./CashPoolPanel.vue'))
const BuDrilldown = defineAsyncComponent(() => import('./BuDrilldown.vue'))
const ProjectPnlCard = defineAsyncComponent(() => import('./ProjectPnlCard.vue'))

const auth = useCaiwuAuth()
const pkAuth = useAuthStore()
const router = useRouter()

// ── 顶部主 Tab ───────────────────────────────────────────────────────────────
const mainTab = ref('overview')
const MAIN_TABS = computed(() => {
  const t = [{ key: 'overview', label: '经营总览' }]
  if (pkAuth.canPage('caiwu_charts')) t.push({ key: 'charts', label: '报表分析' })
  if (pkAuth.canPage('ar_analytics')) t.push({ key: 'bf', label: '业财损益' })
  if (pkAuth.canPage('ar_analytics')) t.push({ key: 'forecast', label: '判未来' })
  if (pkAuth.canPage('ar_analytics')) t.push({ key: 'ar', label: '应收分析' })
  if (pkAuth.canPage('ar_cashflow')) t.push({ key: 'cashflow', label: '现金流分析' })
  if (pkAuth.canPage('ar_cashflow')) t.push({ key: 'pool', label: '资金池' })
  t.push({ key: 'target', label: '目标分解' })
  t.push({ key: 'actions', label: '决策行动' + (actionCounts.value.open ? ` (${actionCounts.value.open})` : '') })
  return t
})
const panelComp = computed(() => ({
  charts: ChartsPanel, bf: BusinessFinancePanel, forecast: ForecastPanel,
  ar: ARAnalyticsPanel, cashflow: CashflowPanel,
  target: TargetDecompPanel, actions: ActionPanel, pool: CashPoolPanel,
}[mainTab.value] || null))

// ── P4 行动项计数（驱动 Tab 角标）────────────────────────────────────────────
const actionCounts = ref({ open: 0, in_progress: 0, done: 0, dismissed: 0 })

// ── P4 复盘大屏模式 ─────────────────────────────────────────────────────────
const presentMode = ref(false)
const presentPage = ref(0)
const PRESENT_PAGES = ['规模', '盈利', '业财', '预测', '目标', '行动']
function nextPresentPage() { presentPage.value = (presentPage.value + 1) % PRESENT_PAGES.length }
function prevPresentPage() { presentPage.value = (presentPage.value - 1 + PRESENT_PAGES.length) % PRESENT_PAGES.length }
function openPresent() { presentPage.value = 0; presentMode.value = true }

// ── P4 信号转行动项 ──────────────────────────────────────────────────────────
const alertToast = ref('')
let alertToastTimer = null
function showAlertToast(msg) {
  alertToast.value = msg
  clearTimeout(alertToastTimer)
  alertToastTimer = setTimeout(() => { alertToast.value = '' }, 2200)
}
async function createActionFromSignal(a) {
  try {
    const signal = { type: a.level === 'high' ? 'critical' : (a.level === 'mid' ? 'warning' : 'info'),
      bu: a.bu || '', title: a.text, desc: a.text, level: a.level }
    const res = await ar.actionFromSignal({ signal })
    if (res.data?.created) showAlertToast('✓ 已创建行动项')
    else showAlertToast('提示：' + (res.data?.msg || '已有同类行动项'))
    const cnt = actionCounts.value
    cnt.open = (cnt.open || 0) + (res.data?.created ? 1 : 0)
  } catch (e) { showAlertToast(e?.error || '创建失败') }
}

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
    const bfParams = { year: year.value, month: month.value, group_by: 'project' }
    if (selectedBu.value) bfParams.dept = selectedBu.value
    const fcParams = { year: year.value }
    if (selectedBu.value) fcParams.dept = selectedBu.value
    // 主看板与业财融合/预测摘要并行拉取；摘要失败不影响主看板
    const [res, bf, fc] = await Promise.allSettled([
      api.get('/cockpit', { params }),
      ar.businessFinance(bfParams),
      ar.forecast(fcParams),
    ])
    if (res.status === 'fulfilled') data.value = res.value.data
    else throw (res.reason || new Error('加载失败'))
    bfSummary.value = bf.status === 'fulfilled' ? (bf.value.data?.summary || null) : null
    fcSummary.value = fc.status === 'fulfilled' ? (fc.value.data?.summary || null) : null
  } catch (e) {
    loadErr.value = e?.error || '加载失败'
  } finally {
    loading.value = false
  }
}
const bfSummary = ref(null)   // 业财融合摘要（驱动今日信号）
const fcSummary = ref(null)   // 预测摘要（驱动今日信号）

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
  '生成本月集团经营分析报告',
  '生成今年的年度经营分析报告',
  '哪个事业部在拖累集团利润？为什么？',
  '本月回款和收入是否匹配？应收风险在哪？',
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
  chatMessages.value.push({ role: 'assistant', content: '', reasoning: '', tool: '' })
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
      onAnswer: d => { asst.content += d; asst.tool = ''; scrollChatSoon() },
      onTool: e => { asst.tool = `🛠 正在${e.label || '调用技能'}…`; scrollChatSoon() },
      onError: m => { chatErr.value = m },
    })
  } catch (e) {
    if (!chatErr.value) chatErr.value = e?.message || 'AI 助手暂时不可用'
  } finally {
    chatStreaming.value = false
    if (!asst.content) asst.content = chatErr.value ? `⚠ ${chatErr.value}` : '（未返回内容）'
    scrollChatSoon()
    if (autoDistill.value && !chatErr.value && asst.content && asst.content.length > 40) {
      silentDistill(asst.content)
    }
  }
}

function resetChat() { chatMessages.value = []; chatErr.value = '' }

// ── 主动洞察闭环：信号/项目 一键带上下文追问 AI ──────────────────────────────
async function askAi(question) {
  if (chatStreaming.value) return
  chatOpen.value = true
  panelTab.value = 'chat'
  await nextTick()
  sendChat(question)
}
function askAboutSignal(a) {
  askAi(`针对这条经营信号，请结合业财融合数据做归因分析并给出可执行建议：「${a.text}」`)
}
function onAskProject(p) {
  const tag = p.tag_label ? `（当前评级：${p.tag_label}）` : ''
  askAi(`请分析「${p.name}」这个项目${tag}：盈利质量与回款状况如何、问题根因是什么、有哪些改善建议？`)
}

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

// ── 下钻导航（从对话跳到明细页，带上当前事业部+期间）────────────────────────
function drillTo(path) {
  chatOpen.value = false
  const query = {}
  if (path.startsWith('/ar/')) {
    if (selectedBu.value) query.dept = selectedBu.value
  } else {
    query.year = year.value; query.month = month.value
    if (selectedBu.value) query.bu = selectedBu.value
  }
  router.push({ path, query })
}
const KIND_LABEL = { insight: '洞察', background: '背景', rule: '口径' }

// ── 自动沉淀：每轮回答完自动提炼要点入库（开关，默认关）──────────────────────
const autoDistill = ref(false)
async function silentDistill(content) {
  try {
    await api.post('/cockpit/knowledge/distill', { text: content, scope: selectedBu.value || '全集团' })
    showToast('💡 已自动沉淀要点入库')
  } catch (e) { /* silent */ }
}

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

const grad = (c1, c2, horiz = false) => ({ type: 'linear', x: 0, y: 0, x2: horiz ? 1 : 0, y2: horiz ? 0 : 1,
  colorStops: [{ offset: 0, color: c1 }, { offset: 1, color: c2 }] })

// ── 经营趋势全景：收入规模柱 + 目标线 + 毛利率/净利率双色区域线
// 正值段绿/蓝渐变填充，负值段红色区域 + 警告标记 + 盈亏平衡参考线
const panoramaOption = computed(() => {
  const t = data.value?.trend || []
  if (!t.length) return null
  const x = t.map(m => `${m.month}月`)
  const rev = t.map(m => m.actual_revenue)
  const tgt = t.map(m => m.target_revenue)
  const gm  = t.map(m => m.actual_revenue ? +(m.actual_gross_profit / m.actual_revenue * 100).toFixed(1) : null)
  const nm  = t.map(m => m.actual_revenue ? +(m.actual_profit    / m.actual_revenue * 100).toFixed(1) : null)

  // Split at zero: positive keeps area fill, negative gets red alarm treatment
  const gmPos = gm.map(v => (v != null && v >= 0) ? v : null)
  const gmNeg = gm.map(v => (v != null && v  < 0) ? v : null)
  const nmPos = nm.map(v => (v != null && v >= 0) ? v : null)
  const nmNeg = nm.map(v => (v != null && v  < 0) ? v : null)

  const allM = [...gm, ...nm].filter(v => v != null)
  const hasNeg = allM.some(v => v < 0)
  const minY = allM.length ? (hasNeg ? Math.min(...allM) - 6 : -4) : -10
  const maxY = allM.length ? Math.max(14, ...allM) + 6 : 20

  const lineBase = { type: 'line', yAxisIndex: 1, smooth: true, symbolSize: 5, connectNulls: false }

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, ...TOOLTIP,
      formatter(params) {
        let s = `<b>${params[0]?.axisValue}</b><br/>`
        const seen = new Map()
        params.forEach(p => {
          if (p.value == null) return
          // strip trailing "−" to merge pos+neg into one tooltip row
          const base = p.seriesName.endsWith('−') ? p.seriesName.slice(0, -1) : p.seriesName
          if (!seen.has(base)) seen.set(base, { marker: p.marker, value: p.value })
        })
        seen.forEach(({ marker, value }, name) => {
          const isPct = name.includes('率')
          s += `${marker}${name}：<b>${isPct ? value.toFixed(1) + '%' : axisMoney(value)}</b><br/>`
        })
        return s
      } },
    legend: bottomLegend({ data: ['实际收入', '目标收入', '经营毛利率', '经营净利率'] }),
    grid: { ...gridFor(x, { threshold: 12, right: 64 }), top: 36 },
    xAxis: catAxis(x, { threshold: 12 }),
    yAxis: [
      valueAxis({ formatter: axisMoney }),
      { type: 'value', name: '利润率%', position: 'right', min: minY, max: maxY,
        axisLabel: { color: '#9b8070', formatter: '{value}%' },
        splitLine: { show: false },
        axisLine: { show: true, lineStyle: { color: '#ddc9b6' } } },
    ],
    series: [
      // ── 收入规模 ──────────────────────────────────────────────
      { name: '实际收入', type: 'bar', yAxisIndex: 0, data: rev, barMaxWidth: 28,
        itemStyle: { color: grad('#c8e6c9', '#388e3c'), borderRadius: [4, 4, 0, 0] },
        label: topLabel(p => axisMoney(p.value)), labelLayout: HIDE_OVERLAP },
      { name: '目标收入', type: 'line', yAxisIndex: 0, data: tgt, smooth: true,
        symbol: 'none', lineStyle: { type: 'dashed', width: 2, color: '#9b8070' } },

      // ── 经营毛利率：正段（青绿渐变区域） ─────────────────────
      { ...lineBase, name: '经营毛利率', data: gmPos, symbol: 'circle',
        lineStyle: { color: '#00897b', width: 2.5 }, itemStyle: { color: '#00897b' },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(0,137,123,.28)' }, { offset: 1, color: 'rgba(0,137,123,.03)' }] } },
        endLabel: endLabel(p => p.value != null ? p.value.toFixed(1) + '%' : '', { color: '#00897b' }),
        labelLayout: HIDE_OVERLAP },
      // ── 经营毛利率：负段（红色区域 + 下三角警告标记） ────────
      { ...lineBase, name: '经营毛利率−', data: gmNeg, symbol: 'triangle', symbolSize: 8, symbolRotate: 180,
        lineStyle: { color: '#e53935', width: 2.5 }, itemStyle: { color: '#e53935' },
        areaStyle: { color: 'rgba(229,57,53,.20)' },
        endLabel: endLabel(p => p.value != null ? `▼ ${p.value.toFixed(1)}%` : '', { color: '#e53935', fontWeight: 'bold' }),
        labelLayout: HIDE_OVERLAP },

      // ── 经营净利率：正段（蓝色渐变区域） ─────────────────────
      { ...lineBase, name: '经营净利率', data: nmPos, symbol: 'circle',
        lineStyle: { color: '#1565c0', width: 2.5 }, itemStyle: { color: '#1565c0' },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(21,101,192,.24)' }, { offset: 1, color: 'rgba(21,101,192,.03)' }] } },
        endLabel: endLabel(p => p.value != null ? p.value.toFixed(1) + '%' : '', { color: '#1565c0' }),
        labelLayout: HIDE_OVERLAP },
      // ── 经营净利率：负段（深红 + 危险区底色 + 盈亏平衡线） ──
      { ...lineBase, name: '经营净利率−', data: nmNeg, symbol: 'triangle', symbolSize: 10, symbolRotate: 180,
        lineStyle: { color: '#b71c1c', width: 3 }, itemStyle: { color: '#b71c1c' },
        areaStyle: { color: 'rgba(183,28,28,.24)' },
        markArea: { silent: true, z: 0,
          data: [[{ yAxis: minY, itemStyle: { color: 'rgba(229,57,53,.06)' } }, { yAxis: 0 }]] },
        markLine: { silent: true, symbol: 'none', data: [{
          yAxis: 0,
          lineStyle: { color: 'rgba(198,40,40,.55)', width: 1.5, type: 'solid' },
          label: { formatter: '盈亏平衡', position: 'insideStartTop', color: '#c62828', fontSize: 9, padding: [2, 4] } }] },
        endLabel: endLabel(p => p.value != null ? `⚠ ${p.value.toFixed(1)}%` : '', { color: '#b71c1c', fontWeight: 'bold' }),
        labelLayout: HIDE_OVERLAP },
    ],
  }
})

// ── 目标达成子弹图组：收入/毛利/净利 YTD达成率 vs 目标(100%) vs 时间进度 ──────────
const bulletOption = computed(() => {
  const y = data.value?.overview?.ytd
  if (!y) return null
  const tp = timeProgressPct.value
  const rows = [
    { name: '收入', a: y.actual_revenue, t: y.target_revenue },
    { name: '经营毛利', a: y.actual_gross_profit, t: y.target_gross_profit },
    { name: '经营净利', a: y.actual_profit, t: y.target_profit },
  ].map(r => ({ ...r, ach: r.t ? +(r.a / r.t * 100).toFixed(1) : null }))
  const cats = rows.map(r => r.name).reverse()
  // 目标缺失/极端时夹紧轴范围，避免达成率爆表把基准线挤到角落
  const maxX = Math.min(Math.max(120, ...rows.map(r => r.ach || 0)) * 1.05, 200)
  const minX = Math.min(0, ...rows.map(r => r.ach || 0))
  const barColor = ach => (ach == null ? '#bdbdbd' : ach >= 100 ? '#2e7d32' : ach >= tp ? '#f9a825' : '#e53935')
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
      formatter: ps => {
        const r = rows[rows.length - 1 - ps[0].dataIndex]
        return `<b>${r.name}</b><br/>YTD实际：${axisMoney(r.a)}<br/>年度目标：${axisMoney(r.t)}<br/>达成率：<b>${r.ach == null ? '—' : r.ach + '%'}</b><br/>时间进度：${tp.toFixed(0)}%`
      } },
    grid: { top: 30, right: 24, bottom: 16, left: 16, containLabel: true },
    xAxis: { type: 'value', max: maxX, min: minX, axisLabel: { color: '#9b8070', formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.12)' } } },
    yAxis: { type: 'category', data: cats, axisLabel: { color: '#5f4d3d', fontSize: 12, fontWeight: 600 } },
    series: [{
      type: 'bar', barWidth: 16,
      data: rows.map(r => ({ value: r.ach || 0, itemStyle: { color: barColor(r.ach), borderRadius: 8 } })).reverse(),
      label: { show: true, position: 'right', fontSize: 11, fontWeight: 700, color: '#5f4d3d',
        formatter: p => (p.value).toFixed(0) + '%' },
      markArea: { silent: true, data: [
        [{ xAxis: 0, itemStyle: { color: 'rgba(229,57,53,0.05)' } }, { xAxis: 60 }],
        [{ xAxis: 60, itemStyle: { color: 'rgba(249,168,37,0.05)' } }, { xAxis: 90 }],
        [{ xAxis: 90, itemStyle: { color: 'rgba(46,125,50,0.05)' } }, { xAxis: maxX }],
      ] },
      markLine: { silent: true, symbol: 'none', data: [
        { xAxis: 100, lineStyle: { color: '#2e7d32', type: 'solid', width: 1.5 },
          label: { formatter: '目标 100%', color: '#2e7d32', fontSize: 10, position: 'insideEndTop' } },
        { xAxis: tp, lineStyle: { color: '#c96342', type: 'dashed', width: 1.5 },
          label: { formatter: `时间 ${tp.toFixed(0)}%`, color: '#c96342', fontSize: 10, position: 'insideEndBottom' } },
      ] },
    }],
  }
})

// ── per-BU current-month actual (revenue & profit) ───────────────────────────
const buActualOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
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
      { name: '收入', type: 'bar', data: bus.map(b => b.month.actual_revenue), itemStyle: { color: '#2e7d32', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        label: topLabel(p => axisMoney(p.value)), labelLayout: HIDE_OVERLAP },
      { name: '利润', type: 'bar', data: bus.map(b => b.month.actual_profit), itemStyle: { color: '#1565c0', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        label: topLabel(p => axisMoney(p.value)), labelLayout: HIDE_OVERLAP },
    ],
  }
})

// ── per-BU YTD achievement rate (revenue & profit) ───────────────────────────
const buRateOption = computed(() => {
  const bus = data.value?.bus || []
  const names = bus.map(b => b.business_unit)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
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
        label: topLabel(p => p.value == null ? '' : p.value.toFixed(0) + '%'), labelLayout: HIDE_OVERLAP,
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#c96342', type: 'dashed' }, data: [{ yAxis: 100, label: { formatter: '100%', color: '#c96342', fontSize: 10 } }] } },
      { name: 'YTD利润达成', type: 'bar', data: bus.map(b => b.ytd.profit_rate), itemStyle: { color: '#42a5f5', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 26,
        label: topLabel(p => p.value == null ? '' : p.value.toFixed(0) + '%'), labelLayout: HIDE_OVERLAP },
    ],
  }
})

const hasData = computed(() => (data.value?.bus || []).some(b => b.month.actual_revenue != null || b.month.actual_profit != null))

// ── 经营命脉派生指标（全部源自 /cockpit 已返回字段，无需后端改动）─────────────
const pct = (a, b) => (a == null || !b ? null : (a / b) * 100)
const fmtPctVal = (v) => (v == null ? '—' : v.toFixed(1) + '%')

const groupMonth = computed(() => data.value?.overview?.month || null)
const groupYtd = computed(() => data.value?.overview?.ytd || null)

// 当月集团：成本=收入−经营毛利；期间费用≈经营毛利−经营净利；各项利润率
const derived = computed(() => {
  const m = groupMonth.value
  if (!m) return null
  const rev = m.actual_revenue, gross = m.actual_gross_profit, prof = m.actual_profit
  const cost = (rev != null && gross != null) ? rev - gross : null
  const expense = (gross != null && prof != null) ? gross - prof : null
  return {
    revenue: rev, gross, profit: prof, cost, expense,
    grossMargin: pct(gross, rev), netMargin: pct(prof, rev),
    costRatio: pct(cost, rev), expenseRatio: pct(expense, rev),
  }
})

// 核心指标带：收入 / 经营毛利 / 经营净利（期间费用并入比率条，不再单列卡片）
const heroCards = computed(() => {
  const m = groupMonth.value
  if (!m) return []
  const d = derived.value
  return [
    { key: 'rev', label: '本月收入', value: m.actual_revenue, color: '#2e7d32',
      rate: m.revenue_rate, mom: m.revenue_mom, yoy: m.revenue_yoy },
    { key: 'gross', label: '本月经营毛利', value: m.actual_gross_profit, color: '#00897b',
      rate: m.gross_profit_rate, mom: m.gross_profit_mom, yoy: m.gross_profit_yoy,
      sub: `毛利率 ${fmtPctVal(d?.grossMargin)}` },
    { key: 'prof', label: '本月经营净利', value: m.actual_profit, color: '#1565c0',
      rate: m.profit_rate, mom: m.profit_mom, yoy: m.profit_yoy, neg: (m.actual_profit ?? 0) < 0,
      sub: `净利率 ${fmtPctVal(d?.netMargin)}` },
  ]
})

// 次级比率药丸条（当月集团）
const ratioPills = computed(() => {
  const d = derived.value, y = groupYtd.value
  if (!d) return []
  return [
    { label: '毛利率', value: fmtPctVal(d.grossMargin) },
    { label: '净利率', value: fmtPctVal(d.netMargin) },
    { label: '成本率', value: fmtPctVal(d.costRatio) },
    { label: '费用率', value: fmtPctVal(d.expenseRatio) },
    { label: 'YTD收入', value: wan(y?.actual_revenue) },
    { label: 'YTD净利', value: wan(y?.actual_profit) },
  ]
})

// 年度目标进度（YTD 达成 vs 时间进度）
const timeProgressPct = computed(() => (data.value ? (data.value.month / 12) * 100 : 0))
const progressBars = computed(() => {
  const y = groupYtd.value
  if (!y) return []
  const mk = (label, actual, target, rate, color) => ({
    label, actual, target, rate, color,
    fillPct: target ? Math.max(0, Math.min(115, (actual / target) * 100)) : null,
  })
  return [
    mk('收入', y.actual_revenue, y.target_revenue, y.revenue_rate, '#2e7d32'),
    mk('经营毛利', y.actual_gross_profit, y.target_gross_profit, y.gross_profit_rate, '#00897b'),
    mk('经营净利', y.actual_profit, y.target_profit, y.profit_rate, '#1565c0'),
  ]
})

// ── 三级下钻：集团 → 事业部(科目+项目) → 项目(损益卡)──────────────────────────
const drillBu = ref('')          // 当前下钻的事业部
const drillProjectName = ref('') // 从下钻打开的项目损益卡
function openDrill(bu) { if (bu) drillBu.value = bu }
function onDrillProject(row) { drillProjectName.value = row.project_name }

// 事业部经营矩阵（核心大表）
const buMatrix = computed(() => {
  const bus = data.value?.bus || []
  const groupRev = (bus.reduce((s, b) => s + (b.month.actual_revenue || 0), 0)) || 0
  const rows = bus.map(b => {
    const m = b.month, y = b.ytd
    const rev = m.actual_revenue, gross = m.actual_gross_profit, prof = m.actual_profit
    return {
      bu: b.business_unit, rev, gross, prof,
      grossMargin: pct(gross, rev), netMargin: pct(prof, rev),
      revRate: m.revenue_rate, profRate: m.profit_rate,
      revMom: m.revenue_mom, revYoy: m.revenue_yoy,
      ytdRev: y.actual_revenue, ytdRate: y.revenue_rate, ytdProf: y.actual_profit,
      share: groupRev ? pct(rev, groupRev) : null,
      loss: (prof ?? 0) < 0,
      hasData: rev != null || prof != null,
    }
  }).filter(r => r.hasData)
  rows.sort((a, b) => (b.rev ?? -Infinity) - (a.rev ?? -Infinity))
  return rows
})

const COMP_COLORS = ['#2e7d32', '#1565c0', '#00897b', '#f57f17', '#6a1b9a', '#c96342', '#5c6bc0', '#26a69a']

// 收入构成（环形）
const revStructOption = computed(() => {
  const rows = buMatrix.value.filter(r => (r.rev ?? 0) > 0)
  if (!rows.length) return null
  const pie = rows.map((r, i) => ({ name: r.bu, value: r.rev, itemStyle: { color: COMP_COLORS[i % COMP_COLORS.length] } }))
  return {
    tooltip: { trigger: 'item', ...TOOLTIP, formatter: p => `${p.name}<br/>${wan(p.value)} 元 (${p.percent.toFixed(1)}%)` },
    legend: { bottom: 0, type: 'scroll', textStyle: { fontSize: 11, color: '#6b5a4a' } },
    series: [{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'], data: pie,
      label: { formatter: p => `${p.name}\n${p.percent.toFixed(0)}%`, fontSize: 11, lineHeight: 14, color: '#5f4d3d' },
      labelLine: { length: 8, length2: 8 }, labelLayout: HIDE_OVERLAP,
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.25)' } },
    }],
  }
})

// 利润贡献（横向分歧条：正绿负红，直观看谁在拖累）
const profitContribOption = computed(() => {
  const rows = [...buMatrix.value].filter(r => r.prof != null).sort((a, b) => a.prof - b.prof)
  if (!rows.length) return null
  const names = rows.map(r => r.bu)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
      formatter: p => `${p[0].name}<br/>经营净利：${wan(p[0].value)} 元` },
    grid: { top: 8, right: 64, bottom: 8, left: 16, containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: '#9b8070', formatter: v => axisMoney(v) },
      splitLine: { lineStyle: { color: 'rgba(180,140,110,.15)' } } },
    yAxis: { type: 'category', data: names, axisLabel: { color: '#6b5a4a', width: 96, overflow: 'truncate' } },
    series: [{
      type: 'bar', barMaxWidth: 22,
      data: rows.map(r => ({ value: r.prof,
        itemStyle: { color: r.prof >= 0 ? '#2e7d32' : '#c62828', borderRadius: r.prof >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] },
        label: { position: r.prof >= 0 ? 'right' : 'left' } })),
      label: { show: true, fontSize: 10.5, fontWeight: 600, color: '#6b5a4a', formatter: p => axisMoney(p.value) },
      labelLayout: HIDE_OVERLAP,
    }],
  }
})

// 今日信号（主动洞察）：融合 BU 经营风险 + 业财融合洞察，带可下钻动作
const alerts = computed(() => {
  const rows = buMatrix.value
  const list = []
  const d = derived.value
  // ── 集团级 ────────────────────────────────────────────────
  if (d?.netMargin != null && d.netMargin < 0) list.push({ level: 'high', text: `集团整体净利率为负（${d.netMargin.toFixed(1)}%），盈利承压` })
  // ── 业财融合：薄利 / 回款风险（来自业财损益摘要）──────────
  const bf = bfSummary.value
  if (bf) {
    const t = bf.by_tag || {}
    const critical = t.critical?.count || 0
    const lowM = t.low_margin?.count || 0
    if (critical > 0) list.push({ level: 'high', tab: 'bf',
      text: `${critical} 个项目「又薄又难收」（低毛利+回款差），吞噬利润` })
    if (bf.overdue > 0 && bf.overdue_rate != null && bf.overdue_rate >= 20) list.push({ level: 'high', tab: 'bf',
      text: `逾期未收 ${wan(bf.overdue)}，逾期率 ${bf.overdue_rate.toFixed(0)}%，回款承压` })
    if (lowM > 0) list.push({ level: 'mid', tab: 'bf',
      text: `${lowM} 个项目「赚收入不赚钱」，规模大但毛利薄` })
  }
  // ── 判未来：全年落地预测 / 坏账（来自预测摘要）──────────────
  const fc = fcSummary.value
  if (fc) {
    if (fc.profit_gap != null && fc.profit_gap < 0) list.push({ level: 'high', tab: 'forecast',
      text: `按当前节奏，全年净利预测 ${wan(fc.proj_profit)}，缺口 ${wan(fc.profit_gap)}（预测达成 ${fc.profit_rate != null ? fc.profit_rate.toFixed(0) + '%' : '—'}）` })
    if (fc.baddebt_risk > 0) list.push({ level: 'mid', tab: 'forecast',
      text: `坏账风险 ${wan(fc.baddebt_risk)}（逾期90天+未收），需重点催收` })
  }
  // ── 事业部级（可点击下钻）────────────────────────────────
  rows.filter(r => r.loss).forEach(r => list.push({ level: 'high', bu: r.bu, text: `${r.bu} 当月经营净利为负（${wan(r.prof)}）` }))
  rows.filter(r => !r.loss && r.profRate != null && r.profRate < 80).forEach(r => list.push({ level: 'mid', bu: r.bu, text: `${r.bu} 净利达成偏低（${r.profRate.toFixed(0)}%）` }))
  rows.filter(r => r.revMom != null && r.revMom <= -10).forEach(r => list.push({ level: 'mid', bu: r.bu, text: `${r.bu} 收入环比下滑 ${Math.abs(r.revMom).toFixed(0)}%` }))
  const top = rows[0]
  if (top && top.share != null && top.share > 50) list.push({ level: 'mid', bu: top.bu, text: `收入高度集中：${top.bu} 占集团 ${top.share.toFixed(0)}%，依赖单一事业部` })
  if (!list.length) list.push({ level: 'ok', text: '未发现显著经营风险，各事业部运行平稳' })
  return list.slice(0, 9)
})
// 信号点击：BU 信号→下钻该事业部；业财信号→切到业财损益 Tab
function onSignal(a) {
  if (a.bu) openDrill(a.bu)
  else if (a.tab) mainTab.value = a.tab
}

// 增长引擎 / 主要拖累（用于结论提示）
const engineLine = computed(() => {
  const rows = buMatrix.value.filter(r => r.prof != null)
  if (!rows.length) return null
  const eng = [...rows].sort((a, b) => (b.prof) - (a.prof))[0]
  const drag = [...rows].sort((a, b) => (a.prof) - (b.prof))[0]
  return { eng, drag, sameOne: eng === drag }
})

onMounted(load)
</script>

<template>
  <div>
    <div class="topbar" style="align-items:flex-start">
      <div class="cockpit-title-wrap">
        <h1>财务驾驶舱</h1>
        <button class="cfa-title-btn" :class="{ on: chatOpen }" @click="chatOpen = true" title="业财融合 AI 助手">
          <span class="cfa-title-orb">🤖</span> 业财 AI 助手 <span class="ai-pro-tag">PRO</span>
        </button>
        <button class="present-btn" @click="openPresent" title="大屏复盘模式">🖥 大屏复盘</button>
      </div>
      <div v-show="mainTab === 'overview'" class="ctrl-row" style="justify-content:flex-end">
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

    <!-- ── 主 Tab 切换 ─────────────────────────────────────────────────────────── -->
    <div class="cockpit-tabs">
      <button v-for="t in MAIN_TABS" :key="t.key"
        :class="['ck-tab', mainTab === t.key ? 'on' : '']" @click="mainTab = t.key">{{ t.label }}</button>
    </div>

    <!-- ════ 经营总览 ════════════════════════════════════════════════════════════ -->
    <template v-if="mainTab === 'overview'">
    <EmptyState v-if="loading && !data" loading />
    <EmptyState v-else-if="loadErr" :error="loadErr" />
    <template v-else-if="data">
      <div :class="{ 'data-reloading': loading }">

      <div v-if="!hasData" class="nodata-banner">
        📭 {{ data.year }}年{{ data.month }}月 · {{ selectedBu || '全集团' }} 暂无已发布数据
      </div>

      <!-- ════ ZONE 1 · 核心指标带（收入 · 经营毛利 · 经营净利）════════════════════ -->
      <div class="kpi-grid kpi-3">
        <div v-for="c in heroCards" :key="c.key" class="kpi-card" :class="{ 'kpi-muted': c.muted }">
          <div class="label">{{ c.label }}<span v-if="c.hint" class="lbl-hint" :title="c.hint">ⓘ</span></div>
          <div class="value" :style="`color:${c.neg ? '#c62828' : c.color}`">{{ fmtMoney(c.value) }}</div>
          <div class="kpi-meta">
            <span v-if="c.rate != null" class="rate-chip" :style="`color:${rateColor(c.rate)};border-color:${rateColor(c.rate)}55`">达成 {{ fmtRate(c.rate) }}</span>
            <span v-if="c.sub" class="kpi-sub-tag">{{ c.sub }}</span>
          </div>
          <div v-if="c.mom != null || c.yoy != null" class="mom-line">
            <span class="mom-badge" :class="chgClass(c.mom)">{{ chgLabel(c.mom) }} 环比</span>
            <span class="mom-badge" :class="chgClass(c.yoy)">{{ chgLabel(c.yoy) }} 同比</span>
          </div>
        </div>
      </div>

      <!-- 次级比率条 -->
      <div class="ratio-strip">
        <div v-for="p in ratioPills" :key="p.label" class="ratio-pill">
          <span class="rp-label">{{ p.label }}</span>
          <span class="rp-value">{{ p.value }}</span>
        </div>
      </div>

      <!-- ════ ZONE 2 · 年度目标进度 + 风险预警 ═══════════════════════════════════ -->
      <div class="zone-2col">
        <div class="card progress-card">
          <div class="section-title">年度目标进度 · 截至 {{ data.month }} 月</div>
          <div v-for="b in progressBars" :key="b.label" class="prog-row">
            <div class="prog-head">
              <span class="prog-name">{{ b.label }}</span>
              <span class="prog-nums">{{ wan(b.actual) }} / 目标 {{ wan(b.target) }}</span>
              <span class="prog-rate" :style="`color:${rateColor(b.rate)}`">{{ fmtRate(b.rate) }}</span>
            </div>
            <div class="prog-track">
              <div class="prog-fill" :style="`width:${b.fillPct == null ? 0 : Math.min(100, b.fillPct)}%;background:${b.color}`"></div>
              <div class="prog-time" :style="`left:${timeProgressPct}%`"></div>
            </div>
          </div>
          <div class="prog-legend">实线=达成进度，竖虚线=时间进度（{{ timeProgressPct.toFixed(0) }}%）；条超过虚线即「跑赢时间」</div>
        </div>

        <div class="card alert-card">
          <div class="section-title signal-title">
            <span>📡 今日信号 <span class="tip">主动洞察 · 点击可下钻</span></span>
            <button class="signal-ai-btn" :disabled="aiLoading" @click="runAiAnalysis">
              🤖 {{ aiLoading ? '解读中…' : 'AI 解读' }}
            </button>
          </div>
          <ul class="alert-list">
            <li v-for="(a, i) in alerts" :key="i" class="alert-item" :class="[`al-${a.level}`, { actionable: a.bu || a.tab }]" @click="onSignal(a)">
              <span class="al-dot"></span>
              <span class="al-text">{{ a.text }}</span>
              <button v-if="a.level !== 'ok'" class="al-ask" title="问 AI 这条信号" @click.stop="askAboutSignal(a)">🤖问</button>
              <button v-if="a.level !== 'ok'" class="al-action" title="转为行动项" @click.stop="createActionFromSignal(a)">→行动</button>
              <span v-if="a.bu || a.tab" class="al-go">›</span>
            </li>
          </ul>
          <div v-if="engineLine" class="engine-line">
            🚀 增长引擎 <b>{{ engineLine.eng.bu }}</b>（净利 {{ wan(engineLine.eng.prof) }}）
            <template v-if="!engineLine.sameOne">　🪨 主要拖累 <b>{{ engineLine.drag.bu }}</b>（净利 {{ wan(engineLine.drag.prof) }}）</template>
          </div>
        </div>
      </div>

      <!-- ════ ZONE 3 · 经营趋势全景 + 目标达成子弹图组 ══════════════════════════ -->
      <div class="zone-2col zone-pano">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">经营趋势全景（{{ data.year }}年）
            <span class="tip">收入柱 · 正值绿/蓝渐变 · 负值红区预警</span>
          </div>
          <BaseChart v-if="panoramaOption" :option="panoramaOption" height="320px" />
          <div v-else class="mini-empty">暂无趋势数据</div>
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">目标达成子弹图
            <span class="tip">YTD达成 vs 目标100% vs 时间进度</span>
          </div>
          <BaseChart v-if="bulletOption" :option="bulletOption" height="320px" />
          <div v-else class="mini-empty">暂无目标数据</div>
        </div>
      </div>

      <!-- ════ ZONE 4 · 事业部经营矩阵（核心大表）════════════════════════════════ -->
      <div class="card matrix-card">
        <div class="section-title">事业部经营矩阵 · {{ data.year }}年{{ data.month }}月（按当月收入排序）</div>
        <div class="matrix-wrap">
          <table class="matrix-table">
            <thead>
              <tr>
                <th class="l">事业部</th>
                <th>当月收入</th><th>收入达成</th><th>环比</th>
                <th>经营毛利</th><th>毛利率</th>
                <th>经营净利</th><th>净利率</th><th>净利达成</th>
                <th>YTD收入</th><th class="share-th">收入占比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!buMatrix.length"><td colspan="11" class="mtx-empty">暂无已发布的事业部数据</td></tr>
              <tr v-for="r in buMatrix" :key="r.bu" :class="{ 'row-loss': r.loss }" class="drillable" @click="openDrill(r.bu)">
                <td class="l bu">{{ r.bu }}<span class="drill-hint">下钻 ›</span></td>
                <td class="strong">{{ wan(r.rev) }}</td>
                <td><span :style="`color:${rateColor(r.revRate)}`">{{ fmtRate(r.revRate) }}</span></td>
                <td :class="chgClass(r.revMom)">{{ chgLabel(r.revMom) }}</td>
                <td>{{ wan(r.gross) }}</td>
                <td class="muted">{{ fmtPctVal(r.grossMargin) }}</td>
                <td class="strong" :class="{ neg: r.loss }">{{ wan(r.prof) }}</td>
                <td class="muted">{{ fmtPctVal(r.netMargin) }}</td>
                <td><span :style="`color:${rateColor(r.profRate)}`">{{ fmtRate(r.profRate) }}</span></td>
                <td>{{ wan(r.ytdRev) }}</td>
                <td class="share-td">
                  <div class="share-cell">
                    <span class="share-bar" :style="`width:${r.share || 0}%`"></span>
                    <span class="share-num">{{ r.share == null ? '—' : r.share.toFixed(0) + '%' }}</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ════ ZONE 5 · 收入构成 + 利润贡献 ══════════════════════════════════════ -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">收入构成 · 各事业部占比</div>
          <BaseChart v-if="revStructOption" :option="revStructOption" height="300px" />
          <div v-else class="mini-empty">暂无收入数据</div>
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">利润贡献 · 谁在贡献 / 拖累</div>
          <BaseChart v-if="profitContribOption" :option="profitContribOption" height="300px" />
          <div v-else class="mini-empty">暂无利润数据</div>
        </div>
      </div>

      <!-- ════ ZONE 6 · 各事业部当月收入利润 + YTD 达成率 ════════════════════════ -->
      <div class="chart-grid">
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部当月收入 / 利润</div>
          <BaseChart :option="buActualOption" height="300px" />
        </div>
        <div class="card">
          <div class="section-title" style="margin-bottom:8px">各事业部 YTD 达成率</div>
          <BaseChart :option="buRateOption" height="300px" />
        </div>
      </div>
      </div>
    </template>
    </template>

    <!-- ════ 内嵌分析面板（报表分析 / 应收分析 / 现金流 / P4）懒加载 + 缓存 ════════ -->
    <KeepAlive>
      <component v-if="mainTab !== 'overview' && panelComp" :is="panelComp" embedded :key="mainTab"
        :selected-bu="selectedBu"
        @ask-ai="onAskProject"
        @count-change="c => { actionCounts.value = c }" />
    </KeepAlive>

    <!-- 三级下钻：事业部科目+项目 → 项目损益卡 -->
    <BuDrilldown v-if="drillBu" :bu="drillBu" :year="year" :month="month"
      @close="drillBu = ''" @open-project="onDrillProject" />
    <ProjectPnlCard v-if="drillProjectName" :name="drillProjectName" :year="year" askable
      @close="drillProjectName = ''" @ask="p => { drillProjectName = ''; drillBu = ''; onAskProject(p) }" />

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

    <!-- ── 业财融合 经营问答 Agent（标题旁入口 + 滑出对话）─────────────────────── -->
    <Teleport to="body">
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

          <!-- 一键全局经营分析（深度报告）—— 醒目入口，并入 AI 助手 -->
          <div v-show="panelTab === 'chat'" class="cfa-global">
            <div class="cfa-global-l">
              <span class="cfa-global-orb">🧭</span>
              <div>
                <div class="cfa-global-title">全局经营分析<span class="ai-pro-tag">PRO</span></div>
                <div class="cfa-global-sub">{{ aiScopeLabel }} · CFO 视角深度诊断</div>
              </div>
            </div>
            <div class="cfa-global-acts">
              <button v-if="hasAnalysis" class="cfa-global-ghost" @click="viewAnalysis">查看</button>
              <button class="cfa-global-btn" :disabled="aiLoading || !hasData" @click="runAiAnalysis">
                {{ aiLoading ? '分析中…' : (hasAnalysis ? '↻ 重新生成' : '✨ 一键生成') }}
              </button>
            </div>
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
                    <div v-if="m.tool && !m.content" class="cfa-tool">{{ m.tool }}</div>
                    <div v-if="m.reasoning && !m.content" class="cfa-reasoning">💭 {{ m.reasoning }}</div>
                    <div v-if="m.content" class="cfa-md" v-html="renderMarkdown(m.content)"></div>
                    <span v-else-if="chatStreaming && i === chatMessages.length - 1 && !m.reasoning && !m.tool" class="cfa-typing">思考中<i>.</i><i>.</i><i>.</i></span>
                  </div>
                  <!-- 答案动作：提炼入库 + 下钻 -->
                  <div v-if="m.content && !(chatStreaming && i === chatMessages.length - 1)" class="cfa-actions">
                    <button class="cfa-act" :disabled="distillingIdx === i" @click="distillToKb(m.content, i)">
                      {{ distillingIdx === i ? '提炼中…' : '📌 提炼入库' }}
                    </button>
                    <span class="cfa-drill-lbl">下钻 →</span>
                    <button class="cfa-drill" @click="drillTo('/caiwu/report')">报表</button>
                    <button class="cfa-drill" @click="drillTo('/caiwu/project-margin')">项目毛利</button>
                    <button class="cfa-drill" @click="drillTo('/ar/records')">应收账款</button>
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

          <label v-show="panelTab === 'chat'" class="cfa-auto">
            <input type="checkbox" v-model="autoDistill" />
            <span>自动把回答要点沉淀进知识库（越用越聪明）</span>
          </label>
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

    <!-- ── P4 大屏复盘模式 ─────────────────────────────────────────────────────── -->
    <Teleport to="body">
      <Transition name="present-fade">
        <div v-if="presentMode" class="present-overlay" @keydown.esc="presentMode = false" tabindex="0">
          <div class="present-header">
            <div class="present-logo">📊 财务驾驶舱 · 经营复盘</div>
            <div class="present-scope">{{ selectedBu || '全集团' }} · {{ year }}年{{ month }}月</div>
            <div class="present-pages">
              <span v-for="(p, i) in PRESENT_PAGES" :key="p"
                :class="['pp', presentPage === i ? 'active' : '']"
                @click="presentPage = i">{{ p }}</span>
            </div>
            <button class="present-close" @click="presentMode = false">✕ 退出</button>
          </div>
          <div class="present-body">
            <!-- 规模 -->
            <template v-if="presentPage === 0">
              <div class="pp-title">📈 规模 — 收入全景</div>
              <div class="pp-kpis">
                <div v-for="c in heroCards" :key="c.key" class="pp-kpi">
                  <div class="pp-kpi-label">{{ c.label }}</div>
                  <div class="pp-kpi-val" :style="`color:${c.neg?'#ff7043':c.color}`">{{ fmtMoney(c.value) }}</div>
                  <div class="pp-kpi-rate" :style="`color:${rateColor(c.rate)}`">{{ fmtRate(c.rate) }}</div>
                </div>
              </div>
              <div class="pp-chart-wrap">
                <BaseChart v-if="panoramaOption" :option="panoramaOption" height="340px" />
              </div>
            </template>
            <!-- 盈利 -->
            <template v-else-if="presentPage === 1">
              <div class="pp-title">💰 盈利 — 事业部贡献</div>
              <div class="pp-chart-grid">
                <BaseChart v-if="profitContribOption" :option="profitContribOption" height="380px" />
                <BaseChart v-if="revStructOption" :option="revStructOption" height="380px" />
              </div>
            </template>
            <!-- 业财 -->
            <template v-else-if="presentPage === 2">
              <div class="pp-title">🔗 业财融合 — 项目质量分布</div>
              <div v-if="bfSummary" class="pp-bf">
                <div v-for="(t, key) in (bfSummary.by_tag || {})" :key="key" class="pp-bf-tag">
                  <div class="ppbt-count">{{ t.count }}</div>
                  <div class="ppbt-label">{{ t.label }}</div>
                  <div class="ppbt-amt">{{ wan(t.outstanding) }}</div>
                </div>
              </div>
              <div v-else class="pp-empty">暂无业财融合数据</div>
            </template>
            <!-- 预测 -->
            <template v-else-if="presentPage === 3">
              <div class="pp-title">🔭 判未来 — 全年落地预测</div>
              <div v-if="fcSummary" class="pp-fc-rows">
                <div class="pp-fc-row">
                  <span class="ppfr-label">全年收入预测</span>
                  <span class="ppfr-val">{{ wan(fcSummary.proj_revenue) }}</span>
                  <span class="ppfr-rate" :style="`color:${rateColor(fcSummary.revenue_rate)}`">{{ fmtRate(fcSummary.revenue_rate) }}</span>
                </div>
                <div class="pp-fc-row">
                  <span class="ppfr-label">全年净利预测</span>
                  <span class="ppfr-val">{{ wan(fcSummary.proj_profit) }}</span>
                  <span class="ppfr-rate" :style="`color:${rateColor(fcSummary.profit_rate)}`">{{ fmtRate(fcSummary.profit_rate) }}</span>
                </div>
                <div class="pp-fc-row" v-if="fcSummary.baddebt_risk > 0">
                  <span class="ppfr-label" style="color:#ff7043">⚠ 坏账风险</span>
                  <span class="ppfr-val" style="color:#ff7043">{{ wan(fcSummary.baddebt_risk) }}</span>
                </div>
              </div>
              <div v-else class="pp-empty">暂无预测数据</div>
            </template>
            <!-- 目标 -->
            <template v-else-if="presentPage === 4">
              <div class="pp-title">🎯 目标达成 — 年度进度</div>
              <div class="pp-progress">
                <div v-for="b in progressBars" :key="b.label" class="pp-prog-row">
                  <span class="ppr-label">{{ b.label }}</span>
                  <div class="ppr-track">
                    <div class="ppr-fill" :style="`width:${Math.min(100,b.fillPct||0)}%;background:${b.color}`"></div>
                  </div>
                  <span class="ppr-rate" :style="`color:${rateColor(b.rate)}`">{{ fmtRate(b.rate) }}</span>
                </div>
              </div>
              <div v-if="engineLine" class="pp-engine">
                🚀 增长引擎：{{ engineLine.eng.bu }}（净利 {{ wan(engineLine.eng.prof) }}）
                <template v-if="!engineLine.sameOne">　🪨 主要拖累：{{ engineLine.drag.bu }}（净利 {{ wan(engineLine.drag.prof) }}）</template>
              </div>
            </template>
            <!-- 行动 -->
            <template v-else-if="presentPage === 5">
              <div class="pp-title">📋 行动项 — 决策待办</div>
              <div class="pp-alerts">
                <div v-for="(a, i) in alerts.filter(a => a.level !== 'ok')" :key="i" class="pp-alert" :class="`pp-al-${a.level}`">
                  <span class="pp-al-dot"></span>
                  <span>{{ a.text }}</span>
                </div>
                <div v-if="actionCounts.open" class="pp-action-count">
                  ⬥ 待处理行动项 <b>{{ actionCounts.open }}</b> 条 · 处理中 <b>{{ actionCounts.in_progress }}</b> 条
                </div>
              </div>
            </template>
          </div>
          <div class="present-nav">
            <button class="pnav-btn" :disabled="presentPage === 0" @click="prevPresentPage">← 上一页</button>
            <span class="pnav-cur">{{ presentPage + 1 }} / {{ PRESENT_PAGES.length }}</span>
            <button class="pnav-btn" :disabled="presentPage === PRESENT_PAGES.length - 1" @click="nextPresentPage">下一页 →</button>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- P4 信号转行动提示 toast -->
    <Transition name="cfa-toast">
      <div v-if="alertToast" class="p4-toast">{{ alertToast }}</div>
    </Transition>
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

/* ── 主 Tab 切换条 ──────────────────────────────────────────────────────────── */
.cockpit-tabs {
  display: flex; gap: 4px; margin: 4px 0 18px;
  border-bottom: 1px solid rgba(180,140,110,.2);
}
.ck-tab {
  position: relative; border: none; background: none; cursor: pointer;
  padding: 10px 20px; font-size: 14px; font-weight: 600; color: var(--muted);
  border-radius: 10px 10px 0 0; transition: color .15s, background .15s;
}
.ck-tab:hover { color: var(--primary); background: rgba(201,99,66,.05); }
.ck-tab.on { color: var(--primary); font-weight: 800; }
.ck-tab.on::after {
  content: ''; position: absolute; left: 14px; right: 14px; bottom: -1px; height: 3px;
  border-radius: 3px 3px 0 0; background: linear-gradient(90deg, #c96342, #e8a05a);
}

/* ── ZONE 1 · hero KPIs + ratio strip ───────────────────────────────────────── */
.kpi-3 { grid-template-columns: repeat(3, 1fr) !important; }
@media (max-width: 720px) { .kpi-3 { grid-template-columns: 1fr !important; } }
.zone-pano { grid-template-columns: 1.35fr 1fr; }
@media (max-width: 900px) { .zone-pano { grid-template-columns: 1fr; } }

/* 一键全局经营分析（AI 助手内醒目入口） */
.cfa-global {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  margin: 10px 16px 0; padding: 10px 12px; border-radius: 12px;
  background: linear-gradient(120deg, rgba(201,99,66,0.10), rgba(122,159,212,0.10));
  border: 1px solid rgba(201,99,66,0.22);
}
.cfa-global-l { display: flex; align-items: center; gap: 9px; }
.cfa-global-orb { font-size: 20px; filter: drop-shadow(0 0 5px rgba(201,99,66,0.4)); }
.cfa-global-title { font-size: 13px; font-weight: 800; color: var(--text); display: flex; align-items: center; gap: 5px; }
.cfa-global-sub { font-size: 11px; color: var(--muted); margin-top: 1px; }
.cfa-global-acts { display: flex; gap: 6px; flex-shrink: 0; }
.cfa-global-btn {
  border: none; border-radius: 9px; padding: 7px 13px; cursor: pointer; font-size: 12.5px; font-weight: 700;
  color: #fff; background: linear-gradient(135deg, #c96342, #e8855a); box-shadow: 0 3px 10px rgba(201,99,66,0.35);
}
.cfa-global-btn:disabled { opacity: .5; cursor: not-allowed; }
.cfa-global-ghost { border: 1px solid rgba(0,0,0,0.12); background: #fff; border-radius: 9px; padding: 7px 12px; cursor: pointer; font-size: 12.5px; color: var(--muted); }

.kpi-4 { grid-template-columns: repeat(4, 1fr) !important; }
@media (max-width: 960px) { .kpi-4 { grid-template-columns: repeat(2, 1fr) !important; } }
@media (max-width: 520px) { .kpi-4 { grid-template-columns: 1fr !important; } }
.kpi-card.kpi-muted { background: rgba(138,75,52,0.04); }
.lbl-hint { font-size: 10px; color: var(--muted); margin-left: 4px; cursor: help; }
.kpi-meta { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 5px; }
.rate-chip { font-size: 11px; font-weight: 700; padding: 1px 8px; border: 1px solid; border-radius: 10px; }
.kpi-sub-tag { font-size: 11.5px; color: var(--muted); font-weight: 600; }

.ratio-strip {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-top: 12px;
}
@media (max-width: 960px) { .ratio-strip { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 520px) { .ratio-strip { grid-template-columns: repeat(2, 1fr); } }
.ratio-pill {
  display: flex; flex-direction: column; gap: 2px; padding: 9px 12px;
  background: rgba(255,255,255,0.6); border: 1px solid rgba(180,140,110,.16);
  border-radius: 10px;
}
.rp-label { font-size: 11px; color: var(--muted); }
.rp-value { font-size: 16px; font-weight: 700; color: var(--text); }

/* ── ZONE 2 · progress + alerts ─────────────────────────────────────────────── */
.zone-2col { display: grid; grid-template-columns: 1.25fr 1fr; gap: 16px; margin-top: 16px; }
@media (max-width: 900px) { .zone-2col { grid-template-columns: 1fr; } }

.prog-row { margin: 12px 0; }
.prog-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 5px; }
.prog-name { font-size: 13px; font-weight: 700; color: var(--text); min-width: 56px; }
.prog-nums { font-size: 12px; color: var(--muted); flex: 1; }
.prog-rate { font-size: 14px; font-weight: 800; }
.prog-track {
  position: relative; height: 14px; border-radius: 8px;
  background: rgba(120,90,70,.10); overflow: visible;
}
.prog-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 8px; transition: width .5s ease; }
.prog-time {
  position: absolute; top: -3px; bottom: -3px; width: 0;
  border-left: 2px dashed rgba(60,45,35,.55);
}
.prog-legend { font-size: 11px; color: var(--muted); margin-top: 10px; line-height: 1.5; }

.alert-card { display: flex; flex-direction: column; }
.alert-list { list-style: none; margin: 8px 0 0; padding: 0; flex: 1; }
.alert-item {
  display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px;
  color: var(--text); padding: 6px 0; line-height: 1.5;
  border-bottom: 1px dashed rgba(0,0,0,0.05);
}
.alert-item:last-child { border-bottom: none; }
.signal-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.signal-ai-btn {
  border: 1px solid rgba(201,99,66,.3); background: linear-gradient(120deg, rgba(201,99,66,.1), rgba(122,159,212,.1));
  color: #b5532f; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 14px; cursor: pointer;
  white-space: nowrap; transition: filter .15s;
}
.signal-ai-btn:hover:not(:disabled) { filter: brightness(1.06); }
.signal-ai-btn:disabled { opacity: .6; cursor: default; }
.alert-item.actionable { cursor: pointer; border-radius: 7px; padding-left: 6px; margin-left: -6px; transition: background .15s; }
.alert-item.actionable:hover { background: rgba(201,99,66,.07); }
.al-text { flex: 1; }
.al-ask {
  flex-shrink: 0; border: 1px solid rgba(122,159,212,.35); background: rgba(122,159,212,.08);
  color: #4a6fa5; font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 10px;
  cursor: pointer; opacity: 0; transition: opacity .15s; white-space: nowrap;
}
.alert-item:hover .al-ask { opacity: 1; }
.al-ask:hover { background: rgba(122,159,212,.18); }
.al-action {
  flex-shrink: 0; border: 1px solid rgba(46,125,50,.35); background: rgba(46,125,50,.08);
  color: #2e7d32; font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 10px;
  cursor: pointer; opacity: 0; transition: opacity .15s; white-space: nowrap;
}
.alert-item:hover .al-action { opacity: 1; }
.al-action:hover { background: rgba(46,125,50,.18); }
.al-go { color: var(--muted); font-weight: 700; opacity: 0; transition: opacity .15s; flex-shrink: 0; }
.alert-item.actionable:hover .al-go { opacity: 1; }
.al-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
.al-high .al-dot { background: #c62828; box-shadow: 0 0 0 3px rgba(198,40,40,.14); }
.al-mid .al-dot { background: #e65100; box-shadow: 0 0 0 3px rgba(230,81,0,.12); }
.al-ok .al-dot { background: #2e7d32; box-shadow: 0 0 0 3px rgba(46,125,50,.12); }
.al-high { color: #b71c1c; font-weight: 600; }
.engine-line {
  margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.06);
  font-size: 12.5px; color: var(--text);
}
.engine-line b { color: var(--primary); }

/* ── ZONE 3 · 3-up chart grid ───────────────────────────────────────────────── */
.chart-grid-3 { grid-template-columns: repeat(3, 1fr); }
@media (max-width: 1100px) { .chart-grid-3 { grid-template-columns: 1fr; } }

/* ── ZONE 4 · BU matrix table ───────────────────────────────────────────────── */
.matrix-card { margin-top: 16px; }
.matrix-wrap { overflow-x: auto; margin-top: 6px; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 12.5px; white-space: nowrap; }
.matrix-table th {
  font-size: 11px; font-weight: 700; color: var(--muted); text-align: right;
  padding: 9px 12px; background: rgba(0,0,0,0.025); border-bottom: 1px solid rgba(0,0,0,0.07);
  position: sticky; top: 0;
}
.matrix-table th.l, .matrix-table td.l { text-align: left; }
.matrix-table td { text-align: right; padding: 9px 12px; border-bottom: 1px solid rgba(0,0,0,0.045); color: var(--text); }
.matrix-table tbody tr:hover { background: rgba(201,99,66,0.04); }
.matrix-table .bu { font-weight: 700; color: var(--text); }
.matrix-table .strong { font-weight: 700; }
.matrix-table .muted { color: var(--muted); }
.matrix-table .neg { color: #c62828; }
.matrix-table .mom-up { color: #2e7d32; }
.matrix-table .mom-down { color: #c62828; }
.matrix-table .mom-neutral { color: var(--muted); }
.row-loss { background: rgba(198,40,40,0.045); }
.row-loss:hover { background: rgba(198,40,40,0.075) !important; }
.mtx-empty { text-align: center !important; color: var(--muted); padding: 24px !important; }
.drillable { cursor: pointer; }
.drillable:hover { background: rgba(201,99,66,0.06); }
.drill-hint { font-size: 10px; color: var(--muted); margin-left: 6px; opacity: 0; transition: opacity .15s; }
.drillable:hover .drill-hint { opacity: 1; }
.share-th { min-width: 110px; }
.share-cell { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
.share-bar { height: 8px; border-radius: 4px; background: linear-gradient(90deg, #c96342, #e8a05a); min-width: 2px; }
.share-num { min-width: 32px; text-align: right; color: var(--muted); font-weight: 600; }

.mini-empty { display: flex; align-items: center; justify-content: center; height: 280px; color: var(--muted); font-size: 13px; }

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
.cockpit-title-wrap { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.cfa-title-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border: none; border-radius: 22px; cursor: pointer;
  background: linear-gradient(135deg, #c96342, #e8855a 60%, #e8a84a);
  color: #fff; font-size: 13px; font-weight: 700;
  box-shadow: 0 4px 16px rgba(201,99,66,0.4);
  transition: transform .15s, box-shadow .15s, filter .15s;
}
.cfa-title-btn:hover { transform: translateY(-1px); filter: brightness(1.05); box-shadow: 0 6px 20px rgba(201,99,66,0.5); }
.cfa-title-btn.on { opacity: .6; }
.cfa-title-btn .ai-pro-tag { background: rgba(255,255,255,0.25); }
.cfa-title-orb { font-size: 15px; }

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
.cfa-tool { font-size: 12px; color: var(--primary); font-weight: 600; background: rgba(201,99,66,0.08); border-radius: 8px; padding: 5px 9px; }
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

.cfa-auto { display: flex; align-items: center; gap: 6px; padding: 8px 16px 0; font-size: 11.5px; color: var(--muted); cursor: pointer; }
.cfa-auto input { cursor: pointer; }
.cfa-input-row { display: flex; gap: 8px; align-items: flex-end; padding: 8px 16px 16px; border-top: 1px solid rgba(201,99,66,0.12); }
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

/* ── P4 大屏复盘 ─────────────────────────────────────────────────────────────── */
.present-btn {
  border: 1px solid rgba(21,101,192,.35); background: rgba(21,101,192,.06);
  color: #1565c0; font-size: 12px; font-weight: 700; padding: 5px 12px;
  border-radius: 8px; cursor: pointer; margin-left: 8px;
}
.present-btn:hover { background: rgba(21,101,192,.14); }

.present-overlay {
  position: fixed; inset: 0; background: #0d1117; z-index: 9999;
  display: flex; flex-direction: column; color: #e6edf3; outline: none;
}
.present-header {
  display: flex; align-items: center; gap: 16px; padding: 14px 24px;
  background: #161b22; border-bottom: 1px solid #30363d;
}
.present-logo { font-size: 17px; font-weight: 800; color: #58a6ff; }
.present-scope { font-size: 13px; color: #8b949e; }
.present-pages { display: flex; gap: 6px; margin-left: auto; }
.pp { font-size: 13px; padding: 4px 12px; border-radius: 16px; cursor: pointer; color: #8b949e; transition: all .15s; }
.pp.active { background: #1f6feb; color: #fff; font-weight: 700; }
.pp:hover:not(.active) { background: #21262d; color: #e6edf3; }
.present-close { border: 1px solid #30363d; background: none; color: #8b949e; padding: 5px 14px; border-radius: 8px; cursor: pointer; font-size: 13px; }
.present-close:hover { color: #ff7b72; border-color: #ff7b72; }

.present-body { flex: 1; overflow-y: auto; padding: 32px 48px; }
.pp-title { font-size: 28px; font-weight: 800; color: #e6edf3; margin-bottom: 28px; letter-spacing: .5px; }

.pp-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 28px; }
.pp-kpi { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px 24px; }
.pp-kpi-label { font-size: 13px; color: #8b949e; margin-bottom: 6px; }
.pp-kpi-val { font-size: 32px; font-weight: 800; }
.pp-kpi-rate { font-size: 15px; font-weight: 700; margin-top: 4px; }
.pp-chart-wrap { background: #161b22; border-radius: 12px; padding: 16px; }
.pp-chart-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }

.pp-bf { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }
.pp-bf-tag { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 24px; text-align: center; }
.ppbt-count { font-size: 48px; font-weight: 900; color: #58a6ff; line-height: 1; }
.ppbt-label { font-size: 15px; color: #8b949e; margin: 8px 0 4px; }
.ppbt-amt { font-size: 20px; font-weight: 700; color: #e6edf3; }

.pp-fc-rows { display: flex; flex-direction: column; gap: 20px; }
.pp-fc-row { display: flex; align-items: center; gap: 24px; background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px 28px; }
.ppfr-label { font-size: 18px; color: #8b949e; flex: 1; }
.ppfr-val { font-size: 36px; font-weight: 800; color: #e6edf3; }
.ppfr-rate { font-size: 20px; font-weight: 800; }

.pp-progress { display: flex; flex-direction: column; gap: 20px; }
.pp-prog-row { display: flex; align-items: center; gap: 16px; }
.ppr-label { font-size: 16px; color: #8b949e; width: 80px; flex-shrink: 0; }
.ppr-track { flex: 1; height: 18px; background: #21262d; border-radius: 9px; overflow: hidden; }
.ppr-fill { height: 100%; border-radius: 9px; transition: width .5s; }
.ppr-rate { font-size: 20px; font-weight: 800; width: 70px; text-align: right; }
.pp-engine { margin-top: 28px; font-size: 18px; color: #8b949e; }

.pp-alerts { display: flex; flex-direction: column; gap: 12px; }
.pp-alert { display: flex; align-items: flex-start; gap: 12px; padding: 16px 20px; border-radius: 10px; font-size: 16px; font-weight: 500; }
.pp-al-high { background: rgba(248,81,73,.12); border: 1px solid rgba(248,81,73,.3); color: #ff7b72; }
.pp-al-mid { background: rgba(210,153,34,.12); border: 1px solid rgba(210,153,34,.3); color: #e3b341; }
.pp-al-dot { width: 10px; height: 10px; border-radius: 50%; background: currentColor; margin-top: 5px; flex-shrink: 0; }
.pp-action-count { margin-top: 16px; font-size: 18px; color: #8b949e; }
.pp-action-count b { color: #e6edf3; }

.pp-empty { font-size: 18px; color: #8b949e; text-align: center; padding: 60px; }

.present-nav {
  display: flex; align-items: center; justify-content: center; gap: 24px;
  padding: 16px; background: #161b22; border-top: 1px solid #30363d;
}
.pnav-btn { border: 1px solid #30363d; background: none; color: #8b949e; padding: 8px 24px; border-radius: 8px; cursor: pointer; font-size: 15px; font-weight: 600; transition: all .15s; }
.pnav-btn:disabled { opacity: .35; cursor: default; }
.pnav-btn:not(:disabled):hover { background: #21262d; color: #e6edf3; }
.pnav-cur { font-size: 14px; color: #8b949e; min-width: 60px; text-align: center; }

.present-fade-enter-active, .present-fade-leave-active { transition: opacity .25s; }
.present-fade-enter-from, .present-fade-leave-to { opacity: 0; }

/* P4 alert toast */
.p4-toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: #2e7d32; color: #fff; padding: 8px 20px; border-radius: 20px; font-size: 13px; z-index: 8000; pointer-events: none; }
</style>
