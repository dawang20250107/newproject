<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import api from '../../api/caiwu.js'
import { useCaiwuAuth } from '../../composables/useCaiwuAuth.js'
import { useToast } from '../../composables/useToast.js'
import { confirmDlg } from '../../composables/confirm.js'
import { fmtMoney } from '../../utils/format.js'
import EmptyState from '../../components/EmptyState.vue'

const auth = useCaiwuAuth()
const toast = useToast()

// ── 期间 ────────────────────────────────────────────────────────────────────
const now = new Date()
const year = ref(now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear())
const month = ref(now.getMonth() === 0 ? 12 : now.getMonth())   // 默认上一个已结账月
const YEARS = Array.from({ length: 6 }, (_, i) => now.getFullYear() - 4 + i)

// ── 数据 ────────────────────────────────────────────────────────────────────
const loading = ref(false)
const matrix = ref(null)       // { units, uploaded, cells, pairs, kpi }
const batches = ref([])        // 与 units 对齐的批次数组（null=未上传）
const units = computed(() => matrix.value?.units || [])
const activeTab = ref('matrix')   // matrix | pair

async function load() {
  loading.value = true
  try {
    const [m, b] = await Promise.all([
      api.get('/internal/matrix', { params: { year: year.value, month: month.value } }),
      api.get('/internal/batches', { params: { year: year.value, month: month.value } }),
    ])
    matrix.value = m.data
    batches.value = b.data.batches
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败')
  } finally { loading.value = false }
}
watch([year, month], () => { load(); if (pairA.value && pairB.value) loadPair() })
onMounted(load)

const kpi = computed(() => matrix.value?.kpi || {})
const uploadedSet = computed(() => new Set(matrix.value?.uploaded || []))
const hasAnyData = computed(() => (matrix.value?.uploaded || []).length > 0)

// 矩阵格颜色：按该无序对差异强度着色
const pairDiffMap = computed(() => {
  const m = {}
  for (const p of matrix.value?.pairs || []) {
    m[`${p.a}|${p.b}`] = p; m[`${p.b}|${p.a}`] = p
  }
  return m
})
function cellPair(a, b) { return pairDiffMap.value[`${a}|${b}`] || null }
function cellCls(a, b) {
  const p = cellPair(a, b)
  if (!p) return ''
  if (!p.both_uploaded) return 'c-partial'
  return Math.abs(p.diff) < 0.005 ? 'c-ok' : 'c-diff'
}
const shortName = (u) => u.replace('事业部', '').replace('集团', '')

// ── 两两比对 ────────────────────────────────────────────────────────────────
const pairA = ref('')
const pairB = ref('')
const pairData = ref(null)
const pairLoading = ref(false)
const onlyUnmatched = ref(false)
const pairKw = ref('')

async function loadPair() {
  if (!pairA.value || !pairB.value || pairA.value === pairB.value) return
  pairLoading.value = true
  try {
    const res = await api.get('/internal/pair', {
      params: { year: year.value, month: month.value, a: pairA.value, b: pairB.value } })
    pairData.value = res.data
  } catch (e) { toast.error(e?.msg || e?.error || '加载失败')
  } finally { pairLoading.value = false }
}
function openPair(a, b) {
  pairA.value = a; pairB.value = b
  activeTab.value = 'pair'
  loadPair()
}
function swapPair() {
  const t = pairA.value; pairA.value = pairB.value; pairB.value = t
  loadPair()
}
function filterRows(rows) {
  let r = rows || []
  if (onlyUnmatched.value) r = r.filter(x => !x.match)
  const kw = pairKw.value.trim()
  if (kw) r = r.filter(x => (x.summary || '').includes(kw) || (x.voucher_no || '').includes(kw) || (x.subject_name || '').includes(kw))
  return r
}
const aShown = computed(() => filterRows(pairData.value?.a_rows))
const bShown = computed(() => filterRows(pairData.value?.b_rows))

// ── 上传 ────────────────────────────────────────────────────────────────────
const showUpload = ref(false)
const upBu = ref('')
const upFile = ref(null)
const upDropping = ref(false)
const uploading = ref(false)
const upResult = ref(null)
function openUpload(bu) {
  upBu.value = bu || ''
  upFile.value = null; upResult.value = null
  showUpload.value = true
}
function onUpPick(e) { upFile.value = e.target.files[0] || null }
function onUpDrop(e) {
  upDropping.value = false
  const f = Array.from(e.dataTransfer?.files || [])[0]
  if (!f) return
  if (!/\.xlsx?$/i.test(f.name)) { toast.error(`不支持的文件类型：${f.name}（请拖入 .xlsx/.xls）`); return }
  upFile.value = f
}
async function doUpload() {
  if (!upFile.value) { toast.error('请选择金蝶导出的文件'); return }
  uploading.value = true
  upResult.value = null
  try {
    const fd = new FormData()
    fd.append('bu', upBu.value)
    fd.append('year', year.value)
    fd.append('month', month.value)
    fd.append('file', upFile.value)
    const res = await api.post('/internal/upload', fd)
    upResult.value = res.data
    toast.success(`已导入 ${res.data.rows} 行`)
    upFile.value = null
    load()
    if (pairData.value) loadPair()
  } catch (e) { toast.error(e?.msg || e?.error || '上传失败')
  } finally { uploading.value = false }
}
async function delBatch(b) {
  if (!b) return
  if (!(await confirmDlg(`删除「${b.business_unit}」${b.year}年${b.month}月的内往数据（${b.row_count} 行）？删除后矩阵与比对将不含该主体。`))) return
  try {
    await api.delete(`/internal/batches/${b.id}`)
    toast.success('已删除')
    load()
    if (pairData.value) loadPair()
  } catch (e) { toast.error(e?.msg || e?.error || '删除失败') }
}

const fmt = (v) => fmtMoney(v, '0.00')
const fmtDiff = (v) => (Math.abs(v) < 0.005 ? '0.00' : fmtMoney(v))
</script>

<template>
  <div class="ir-view">
    <!-- ── 页头：标题 + 期间 + 上传 ─────────────────────────────────────── -->
    <div class="ir-head">
      <div class="ir-title">
        <h1>内部往来核对</h1>
        <span class="ir-sub">金蝶明细分类账 / 核算维度余额表 · 镜像核对 · 差异定位</span>
      </div>
      <div class="ir-ctrl">
        <select v-model.number="year" class="ir-sel"><option v-for="y in YEARS" :key="y" :value="y">{{ y }} 年</option></select>
        <select v-model.number="month" class="ir-sel"><option v-for="m in 12" :key="m" :value="m">{{ m }} 月</option></select>
        <button v-if="auth.canUpload" class="btn btn-primary btn-sm" @click="openUpload('')">↑ 上传金蝶数据</button>
      </div>
    </div>

    <!-- ── 覆盖条：各主体上传状态（明细/余额两种数据分别标记）──────────────── -->
    <div class="ir-cover">
      <div v-for="(bu, i) in units" :key="bu"
        :class="['cov-chip', batches[i] ? 'on' : '']"
        :title="batches[i] ? '' : '未上传，点击上传'"
        @click="auth.canUpload && openUpload(bu)">
        <span class="cov-dot"></span>{{ shortName(bu) }}
        <template v-for="k in ['balance', 'detail']" :key="k">
          <span v-if="batches[i]?.[k]" class="cov-tag"
            :title="`${k === 'balance' ? '余额表' : '明细账'} ${batches[i][k].row_count} 行 · ${batches[i][k].uploaded_by || '—'} 上传`">
            {{ k === 'balance' ? '余' : '明' }}{{ batches[i][k].row_count }}
            <button v-if="auth.canDelete" class="cov-x" title="删除这份数据"
              @click.stop="delBatch(batches[i][k])">✕</button>
          </span>
        </template>
      </div>
    </div>

    <!-- ── KPI ─────────────────────────────────────────────────────────── -->
    <div class="ir-kpis">
      <div class="kpi"><div class="kpi-l">内往应收合计</div><div class="kpi-v">{{ fmt(kpi.total_ar) }}</div></div>
      <div class="kpi"><div class="kpi-l">内往应付合计</div><div class="kpi-v">{{ fmt(kpi.total_ap) }}</div></div>
      <div class="kpi" :class="kpi.total_diff > 0.005 ? 'warn' : 'ok'">
        <div class="kpi-l">镜像差异总额
          <span class="mode-badge" :title="matrix?.mode === 'balance' ? '按期末余额核对（含期初遗留差异）' : '按本期发生净额核对（上传余额表可切换为期末口径）'">
            {{ matrix?.mode === 'balance' ? '期末余额口径' : '本期发生口径' }}</span>
        </div><div class="kpi-v">{{ fmt(kpi.total_diff) }}</div>
      </div>
      <div class="kpi"><div class="kpi-l">核平 / 往来对</div>
        <div class="kpi-v">{{ kpi.pairs_ok ?? 0 }} <span class="kpi-dim">/ {{ kpi.pairs_total ?? 0 }}</span></div>
      </div>
      <div class="kpi" :class="kpi.unmatched_rows ? 'warn' : ''">
        <div class="kpi-l">未识别往来单位行</div><div class="kpi-v">{{ kpi.unmatched_rows ?? 0 }}</div>
      </div>
    </div>

    <!-- ── Tab ─────────────────────────────────────────────────────────── -->
    <div class="ir-tabs">
      <button :class="['ir-tab', activeTab === 'matrix' ? 'active' : '']" @click="activeTab = 'matrix'">差异矩阵</button>
      <button :class="['ir-tab', activeTab === 'pair' ? 'active' : '']" @click="activeTab = 'pair'">两两比对</button>
    </div>

    <!-- ── 矩阵 ────────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'matrix'" class="card ir-body">
      <EmptyState v-if="!loading && !hasAnyData" icon="⇄"
        text="本期间尚无内往数据 —— 上传金蝶「明细分类账」或「核算维度余额表」（支持全部账簿一次性导出）" />
      <template v-else>
        <div class="mx-scroll">
          <table class="mx-tbl">
            <thead>
              <tr>
                <th class="mx-corner">记账方 ＼ 对方</th>
                <th v-for="b in units" :key="b" :class="{ dim: !uploadedSet.has(b) }">{{ shortName(b) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(a, ai) in units" :key="a">
                <th :class="{ dim: !uploadedSet.has(a) }">{{ shortName(a) }}
                  <span v-if="!uploadedSet.has(a)" class="mx-miss">未上传</span>
                </th>
                <td v-for="(b, bi) in units" :key="b"
                  :class="['mx-cell', a === b ? 'diag' : cellCls(a, b)]"
                  :title="a === b ? '' : `${a} 账上对 ${b} 净头寸（应收+ / 应付−）；点击查看两两明细`"
                  @click="a !== b && openPair(a, b)">
                  <template v-if="a !== b">
                    <span v-if="matrix?.cells?.[ai]?.[bi]" class="mx-v">{{ fmt(matrix.cells[ai][bi]) }}</span>
                    <span v-else class="mx-zero">—</span>
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mx-legend">
          <span><i class="lg lg-ok"></i>已核平</span>
          <span><i class="lg lg-diff"></i>存在差异</span>
          <span><i class="lg lg-partial"></i>单边数据（对方未上传）</span>
          <span class="lg-note">格内数值 = 行主体账上对列主体的净头寸（应收为正、应付为负）</span>
        </div>

        <!-- 差异对排行 -->
        <div v-if="(matrix?.pairs || []).length" class="dp-list">
          <div class="dp-head">往来对差异排行<span class="dp-sub">按差异绝对值降序 · 点击行进入明细比对</span></div>
          <table class="dp-tbl">
            <thead><tr><th>往来对</th><th class="amt">A 方净额</th><th class="amt">B 方净额</th><th class="amt">镜像差异</th><th class="ctr">状态</th></tr></thead>
            <tbody>
              <tr v-for="p in matrix.pairs" :key="p.a + p.b" class="dp-row" @click="openPair(p.a, p.b)">
                <td><b>{{ shortName(p.a) }}</b> ⇄ <b>{{ shortName(p.b) }}</b></td>
                <td class="amt">{{ fmt(p.a_net) }}</td>
                <td class="amt">{{ fmt(p.b_net) }}</td>
                <td class="amt" :class="Math.abs(p.diff) < 0.005 ? 'ok-t' : 'diff-t'">{{ fmtDiff(p.diff) }}</td>
                <td class="ctr">
                  <span v-if="!p.both_uploaded" class="st st-partial">单边</span>
                  <span v-else-if="Math.abs(p.diff) < 0.005" class="st st-ok">✓ 核平</span>
                  <span v-else class="st st-diff">差异</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- ── 两两比对 ─────────────────────────────────────────────────────── -->
    <div v-else class="card ir-body">
      <div class="pr-bar">
        <select v-model="pairA" class="ir-sel"><option value="" disabled>选择 A 方</option>
          <option v-for="u in units" :key="u" :value="u" :disabled="u === pairB">{{ u }}</option></select>
        <button class="pr-swap" title="交换两侧" @click="swapPair">⇄</button>
        <select v-model="pairB" class="ir-sel"><option value="" disabled>选择 B 方</option>
          <option v-for="u in units" :key="u" :value="u" :disabled="u === pairA">{{ u }}</option></select>
        <button class="btn btn-primary btn-sm" :disabled="!pairA || !pairB || pairLoading" @click="loadPair">
          {{ pairLoading ? '比对中…' : '开始比对' }}</button>
        <label class="pr-flt"><input v-model="onlyUnmatched" type="checkbox" /> 只看未配对（差异项）</label>
        <input v-model="pairKw" class="pr-kw" placeholder="搜索摘要 / 凭证号 / 科目…" />
      </div>

      <EmptyState v-if="!pairData && !pairLoading" icon="⚖"
        text="选择两个主体开始比对 —— 金额相等且方向互镜的明细自动配对标记，剩余未配对行即差异来源" />

      <template v-if="pairData">
        <div class="pr-sum">
          <div class="prs"><div class="prs-l">{{ shortName(pairData.a) }} 方净额</div><div class="prs-v">{{ fmt(pairData.a_net) }}</div></div>
          <div class="prs"><div class="prs-l">{{ shortName(pairData.b) }} 方净额</div><div class="prs-v">{{ fmt(pairData.b_net) }}</div></div>
          <div class="prs" :class="Math.abs(pairData.diff) < 0.005 ? 'ok' : 'warn'">
            <div class="prs-l">镜像差异</div><div class="prs-v">{{ fmtDiff(pairData.diff) }}</div></div>
          <div class="prs"><div class="prs-l">自动配对</div>
            <div class="prs-v">{{ pairData.matched_pairs }} <span class="kpi-dim">对 · {{ fmt(pairData.matched_amount) }}</span></div></div>
          <div v-if="!pairData.a_uploaded || !pairData.b_uploaded" class="prs warn">
            <div class="prs-l">提示</div>
            <div class="prs-v prs-small">{{ !pairData.a_uploaded ? pairData.a : pairData.b }} 未上传本期数据</div></div>
        </div>

        <div v-if="pairData.balance" class="pr-bal">
          <span class="pr-bal-t">余额镜像（{{ shortName(pairData.a) }} ⇄ {{ shortName(pairData.b) }}）</span>
          <span>期初差异 <b :class="Math.abs(pairData.balance.opening_diff) < 0.005 ? 'ok-t' : 'diff-t'">{{ fmtDiff(pairData.balance.opening_diff) }}</b></span>
          <span>期末差异 <b :class="Math.abs(pairData.balance.closing_diff) < 0.005 ? 'ok-t' : 'diff-t'">{{ fmtDiff(pairData.balance.closing_diff) }}</b></span>
          <span class="pr-bal-d">{{ shortName(pairData.a) }} 期末 {{ fmt(pairData.balance.a.closing) }} ｜ {{ shortName(pairData.b) }} 期末 {{ fmt(pairData.balance.b.closing) }}</span>
          <span v-if="Math.abs(pairData.balance.opening_diff) > 0.005" class="pr-bal-hint">⚠ 期初已有差异：本期明细全配平也无法核平期末，需追溯以前期间</span>
        </div>
        <div class="pr-cols">
          <div v-for="side in ['a', 'b']" :key="side" class="pr-col">
            <div class="pr-col-head">
              <b>{{ side === 'a' ? pairData.a : pairData.b }}</b> 账上 · 对
              {{ side === 'a' ? shortName(pairData.b) : shortName(pairData.a) }}
              <span class="pr-cnt">{{ (side === 'a' ? aShown : bShown).length }} 行</span>
            </div>
            <div class="pr-scroll">
              <table class="pr-tbl">
                <thead><tr><th>日期</th><th>凭证</th><th>科目</th><th>摘要</th><th class="amt">借方</th><th class="amt">贷方</th><th class="ctr">配对</th></tr></thead>
                <tbody>
                  <tr v-for="r in (side === 'a' ? aShown : bShown)" :key="r.id"
                    :class="['pr-row', r.match ? 'matched' : 'unmatched']">
                    <td class="ctr nowrap">{{ r.date || '—' }}</td>
                    <td class="nowrap">{{ r.voucher_no || '—' }}</td>
                    <td class="nowrap" :title="r.subject_code">{{ r.subject_name || r.subject_code || '—' }}</td>
                    <td class="pr-summ" :title="r.summary">{{ r.summary || '—' }}</td>
                    <td class="amt">{{ r.debit ? fmt(r.debit) : '' }}</td>
                    <td class="amt">{{ r.credit ? fmt(r.credit) : '' }}</td>
                    <td class="ctr">
                      <span v-if="r.match" class="mk mk-ok" :title="`配对组 #${r.match}：两侧金额相等且方向互镜`">✓ #{{ r.match }}</span>
                      <span v-else class="mk mk-no" title="对方账上找不到金额相等、方向互镜的记录">无对应</span>
                    </td>
                  </tr>
                  <tr v-if="!(side === 'a' ? aShown : bShown).length">
                    <td colspan="7" class="pr-empty">{{ onlyUnmatched ? '🎉 无未配对差异项' : '本期无明细' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ── 上传弹窗 ─────────────────────────────────────────────────────── -->
    <div v-if="showUpload" class="modal-overlay" @click.self="showUpload = false">
      <div class="modal ir-up-modal">
        <h3>上传内部往来明细账</h3>
        <p class="ir-up-tip">支持两种金蝶导出（可勾选全部账簿一次性导出，系统按「账簿」列自动拆分主体）：<br/>
          ① <b>明细分类账</b>（总账→明细分类账，核算维度=组织机构）→ 两两明细比对；期间按记账日期自动拆分<br/>
          ② <b>核算维度余额表</b>（总账→核算维度余额表）→ 差异矩阵按期末余额口径（含期初遗留差异），期间取下方所选年月<br/>
          同主体同期间重复上传将整体替换。</p>
        <div class="ir-up-row">
          <select v-model="upBu" class="ir-sel">
            <option value="">记账主体：自动识别（推荐）</option>
            <option v-for="u in units" :key="u" :value="u">{{ u }}</option>
          </select>
          <span class="ir-up-period">{{ year }} 年 {{ month }} 月</span>
        </div>
        <label class="up-drop" :class="{ filled: upFile, dropping: upDropping }"
          @dragover.prevent="upDropping = true" @dragleave="upDropping = false" @drop.prevent="onUpDrop">
          <input type="file" accept=".xlsx,.xls" hidden @change="onUpPick" />
          <span v-if="upFile">{{ upFile.name }}</span>
          <span v-else>点击选择或拖入金蝶导出的明细账（.xlsx）</span>
        </label>
        <div v-if="upResult" class="ir-up-res">
          <div class="ir-up-ok">✓ 已识别为「{{ upResult.kind === 'balance' ? '核算维度余额表' : '明细分类账' }}」，
            导入 {{ upResult.rows }} 行（跳过小计/空行 {{ upResult.skipped }} 行）</div>
          <div v-if="upResult.batches?.length" class="ir-up-batches">
            <span v-for="bt in upResult.batches" :key="bt.id" class="ir-up-bt">{{ bt.business_unit }} · {{ bt.year }}-{{ String(bt.month).padStart(2, '0') }} · {{ bt.row_count }} 行</span>
          </div>
          <div v-if="upResult.unmatched?.length" class="ir-up-warn">
            <b>{{ upResult.unmatched.length }} 类往来单位未能识别为内部主体</b>（按外部往来处理，不参与核对）：
            <div class="ir-up-un"><span v-for="u in upResult.unmatched" :key="u.raw">{{ u.raw }} ×{{ u.count }}</span></div>
          </div>
        </div>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showUpload = false">关闭</button>
          <button class="btn btn-primary" :disabled="uploading" @click="doUpload">{{ uploading ? '解析导入中…' : '上传并解析' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ir-view { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 10px; }

/* 页头 */
.ir-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.ir-title h1 { margin: 0; font-size: 20px; }
.ir-sub { font-size: 11.5px; color: var(--muted); letter-spacing: 0.03em; }
.ir-ctrl { display: flex; align-items: center; gap: 8px; }
.ir-sel {
  padding: 5px 9px; font-size: 12.5px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--card, #fff); color: var(--text); cursor: pointer;
}

/* 覆盖条 */
.ir-cover { display: flex; gap: 7px; flex-wrap: wrap; }
.cov-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  font-size: 12px; border: 1px solid var(--border); border-radius: 999px;
  color: var(--muted); background: var(--card, #fff); cursor: pointer; transition: all .13s;
}
.cov-chip:hover { border-color: var(--primary); }
.cov-chip .cov-dot { width: 7px; height: 7px; border-radius: 50%; background: #cfc8c2; }
.cov-chip.on { color: var(--text); border-color: rgba(46, 125, 50, 0.35); background: rgba(76, 175, 80, 0.07); }
.cov-chip.on .cov-dot { background: #43a047; }
.cov-n { font-size: 10.5px; color: var(--muted); }
.cov-tag {
  display: inline-flex; align-items: center; gap: 3px; padding: 0 6px;
  font-size: 10px; border-radius: 999px; background: rgba(0, 0, 0, 0.05); color: var(--muted);
}
.mode-badge {
  margin-left: 6px; padding: 1px 7px; border-radius: 999px; font-size: 9.5px;
  background: rgba(201, 99, 66, 0.1); color: var(--primary); font-weight: 600; letter-spacing: 0.02em;
}
.pr-bal {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  margin-bottom: 12px; padding: 8px 14px; font-size: 12px;
  border: 1px dashed var(--border); border-radius: 10px; background: rgba(0, 0, 0, 0.015);
}
.pr-bal-t { font-weight: 700; }
.pr-bal-d { color: var(--muted); }
.pr-bal-hint { color: #9c6b00; }
.ir-up-batches { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.ir-up-bt { padding: 1px 8px; background: rgba(76, 175, 80, 0.1); color: #2e7d32; border-radius: 999px; font-size: 11px; }
.cov-x { border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 10px; padding: 0 1px; }
.cov-x:hover { color: #c62828; }

/* KPI */
.ir-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.kpi { padding: 10px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--card, #fff); }
.kpi-l { font-size: 11px; color: var(--muted); letter-spacing: 0.04em; }
.kpi-v { margin-top: 2px; font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
.kpi-dim { font-size: 12px; font-weight: 500; color: var(--muted); }
.kpi.warn { border-color: rgba(198, 40, 40, 0.35); background: rgba(198, 40, 40, 0.045); }
.kpi.warn .kpi-v { color: #c62828; }
.kpi.ok { border-color: rgba(46, 125, 50, 0.3); }
.kpi.ok .kpi-v { color: #2e7d32; }

.ir-tabs { flex-shrink: 0; display: flex; gap: 4px; padding: 3px; background: rgba(0, 0, 0, 0.04); border-radius: 10px; width: fit-content; }
.ir-tab {
  border: 0; background: none; padding: 6px 20px; font-size: 12.5px; font-weight: 600;
  color: var(--muted); border-radius: 8px; cursor: pointer; transition: all .15s;
}
.ir-tab.active { background: var(--card, #fff); color: var(--text); box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1); }
.ir-body { flex: 1; min-height: 0; overflow: auto; padding: 14px 16px; }

/* 矩阵 */
.mx-scroll { overflow-x: auto; }
.mx-tbl { border-collapse: collapse; width: 100%; font-size: 12px; }
.mx-tbl th, .mx-tbl td { border: 1px solid var(--border); padding: 7px 9px; text-align: right; }
.mx-tbl thead th { background: var(--thead-bg, #f4f1ef); text-align: center; font-size: 11.5px; white-space: nowrap; }
.mx-tbl tbody th { background: var(--thead-bg, #f4f1ef); text-align: left; font-size: 11.5px; white-space: nowrap; }
.mx-corner { font-size: 10.5px; color: var(--muted); font-weight: 500; }
.mx-tbl th.dim { color: #b5aca4; }
.mx-miss { margin-left: 4px; font-size: 9.5px; color: #b5aca4; font-weight: 400; }
.mx-cell { cursor: pointer; font-variant-numeric: tabular-nums; transition: box-shadow .1s; }
.mx-cell:hover { box-shadow: inset 0 0 0 2px var(--primary); }
.mx-cell.diag { background: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0,0,0,0.025) 4px, rgba(0,0,0,0.025) 8px); cursor: default; }
.mx-cell.c-ok { background: rgba(76, 175, 80, 0.09); }
.mx-cell.c-diff { background: rgba(198, 40, 40, 0.09); }
.mx-cell.c-partial { background: rgba(245, 166, 35, 0.10); }
.mx-zero { color: #c9c2bb; }
.mx-legend { display: flex; gap: 16px; align-items: center; margin-top: 8px; font-size: 11px; color: var(--muted); flex-wrap: wrap; }
.lg { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 4px; vertical-align: -1px; }
.lg-ok { background: rgba(76, 175, 80, 0.35); }
.lg-diff { background: rgba(198, 40, 40, 0.35); }
.lg-partial { background: rgba(245, 166, 35, 0.4); }
.lg-note { margin-left: auto; }

/* 差异对排行 */
.dp-list { margin-top: 18px; }
.dp-head { font-size: 13px; font-weight: 700; margin-bottom: 6px; }
.dp-sub { margin-left: 8px; font-size: 11px; color: var(--muted); font-weight: 400; }
.dp-tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.dp-tbl th { text-align: left; font-size: 11px; color: var(--muted); padding: 5px 9px; border-bottom: 1px solid var(--border); }
.dp-tbl td { padding: 7px 9px; border-bottom: 1px solid rgba(0,0,0,0.05); }
.dp-tbl .amt { text-align: right; font-variant-numeric: tabular-nums; }
.dp-tbl .ctr { text-align: center; }
.dp-row { cursor: pointer; }
.dp-row:hover td { background: rgba(201, 99, 66, 0.05); }
.ok-t { color: #2e7d32; }
.diff-t { color: #c62828; font-weight: 700; }
.st { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 11px; }
.st-ok { background: rgba(76, 175, 80, 0.12); color: #2e7d32; }
.st-diff { background: rgba(198, 40, 40, 0.1); color: #c62828; }
.st-partial { background: rgba(245, 166, 35, 0.14); color: #9c6b00; }

/* 两两比对 */
.pr-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.pr-swap { border: 1px solid var(--border); background: var(--card, #fff); border-radius: 8px; padding: 4px 9px; cursor: pointer; font-size: 14px; }
.pr-swap:hover { border-color: var(--primary); color: var(--primary); }
.pr-flt { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); cursor: pointer; }
.pr-kw { flex: 1; min-width: 160px; max-width: 260px; padding: 5px 10px; font-size: 12px; border: 1px solid var(--border); border-radius: 8px; }
.pr-sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; margin-bottom: 12px; }
.prs { padding: 8px 12px; border: 1px solid var(--border); border-radius: 10px; }
.prs-l { font-size: 10.5px; color: var(--muted); }
.prs-v { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
.prs-small { font-size: 12px; }
.prs.warn { border-color: rgba(198, 40, 40, 0.35); }
.prs.warn .prs-v { color: #c62828; }
.prs.ok .prs-v { color: #2e7d32; }
.pr-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
@media (max-width: 1100px) { .pr-cols { grid-template-columns: 1fr; } }
.pr-col { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.pr-col-head { padding: 8px 12px; font-size: 12.5px; background: var(--thead-bg, #f4f1ef); border-bottom: 1px solid var(--border); }
.pr-cnt { float: right; font-size: 11px; color: var(--muted); }
.pr-scroll { max-height: 520px; overflow: auto; }
.pr-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.pr-tbl th { position: sticky; top: 0; background: var(--card, #fff); font-size: 10.5px; color: var(--muted); text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); z-index: 2; }
.pr-tbl td { padding: 5px 8px; border-bottom: 1px solid rgba(0,0,0,0.045); }
.pr-tbl .amt { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pr-tbl .ctr { text-align: center; }
.nowrap { white-space: nowrap; }
.pr-summ { max-width: 210px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pr-row.matched { background: rgba(76, 175, 80, 0.05); }
.pr-row.matched td:first-child { box-shadow: inset 3px 0 0 rgba(76, 175, 80, 0.55); }
.pr-row.unmatched td:first-child { box-shadow: inset 3px 0 0 rgba(198, 40, 40, 0.5); }
.mk { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10.5px; white-space: nowrap; }
.mk-ok { background: rgba(76, 175, 80, 0.13); color: #2e7d32; }
.mk-no { background: rgba(198, 40, 40, 0.1); color: #c62828; }
.pr-empty { text-align: center; color: var(--muted); padding: 22px; }

/* 上传弹窗 */
.ir-up-modal { width: min(560px, 92vw); }
.ir-up-tip { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 6px 0 12px; }
.ir-up-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.ir-up-period { font-size: 12.5px; color: var(--muted); }
.up-drop {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 22px 16px; border-radius: 12px; cursor: pointer; font-size: 12.5px;
  border: 1.5px dashed rgba(201, 99, 66, 0.35); background: rgba(201, 99, 66, 0.03);
  color: var(--muted); transition: all .13s;
}
.up-drop:hover, .up-drop.dropping { border-color: var(--primary); color: var(--primary); background: rgba(201, 99, 66, 0.06); }
.up-drop.filled { border-style: solid; border-color: var(--primary); color: var(--text); }
.ir-up-res { margin-top: 10px; font-size: 12px; }
.ir-up-ok { color: #2e7d32; }
.ir-up-warn { margin-top: 6px; color: #9c6b00; line-height: 1.5; }
.ir-up-un { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
.ir-up-un span { padding: 1px 8px; background: rgba(245, 166, 35, 0.12); border-radius: 999px; font-size: 11px; }
</style>
