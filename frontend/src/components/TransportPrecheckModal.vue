<script setup>
// 运输对账单导入预检弹窗：导入前逐类详列「将导入 / 各类跳过 / 列漂移」，让用户确认后再落库。
// report 形如后端 transport_import_precheck 返回的 data。
import { ref, computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm', 'cancel'])

// 各跳过类别（统一渲染）
const groups = computed(() => {
  const r = props.report
  if (!r) return []
  return [
    { key: 'settled', level: 'danger', icon: '🔴', label: '源已结算（防重复付款）',
      tip: '这些对账单在运输系统已结算，再导入会重复付款，已自动排除',
      items: r.settled || [], cols: ['bill_no', 'src_status'] },
    { key: 'voided', level: 'danger', icon: '🚫', label: '源已作废 / 取消',
      tip: '这些单据已失效，不应付款，已自动排除',
      items: r.voided || [], cols: ['bill_no', 'src_status'] },
    { key: 'dup_in_system', level: 'warn', icon: '♻️', label: '系统内已存在（去重）',
      tip: '对账单号已在审批管理中，避免重复建单',
      items: r.dup_in_system || [], cols: ['bill_no'] },
    { key: 'dup_in_file', level: 'warn', icon: '♻️', label: '文件内重复（去重）',
      tip: '同一文件内出现多次，仅保留首条',
      items: r.dup_in_file || [], cols: ['bill_no'] },
    { key: 'summary_rows', level: 'warn', icon: '∑', label: '合计 / 汇总行',
      tip: '原表末尾的「合计」行（对账单号形如「681 条」、金额为全表总额），非真实对账单，已自动排除',
      items: r.summary_rows || [], cols: ['bill_no'] },
    { key: 'bad', level: 'warn', icon: '⚠️', label: '数据异常',
      tip: '缺对账单号 / 金额无法解析 / 金额为 0，无法导入',
      items: r.bad || [], cols: ['bill_no', 'reason'] },
  ].filter(g => g.items.length)
})

const totalSkip = computed(() => groups.value.reduce((s, g) => s + g.items.length, 0))
const hasDrift = computed(() => props.report &&
  ((props.report.extra_columns || []).length || (props.report.missing_standard || []).length))

const expanded = ref(new Set(['settled', 'voided'])) // 默认展开高危类
function toggle(k) {
  const s = new Set(expanded.value)
  s.has(k) ? s.delete(k) : s.add(k)
  expanded.value = s
}
const okExpanded = ref(false)

const COL_LABEL = { bill_no: '对账单号', src_status: '源状态', reason: '原因', payee: '收款方', amount: '金额' }
</script>

<template>
  <div v-if="report" class="overlay" @click.self="emit('cancel')">
    <div class="modal tp-modal">
      <div class="modal-header">
        <h3>运输对账单导入预检</h3>
        <button class="modal-close" @click="emit('cancel')">×</button>
      </div>

      <div class="tp-body">
        <!-- 概览 -->
        <div class="tp-hero">
          <div class="tp-hero-item">
            <div class="tp-hero-num">{{ report.total }}</div>
            <div class="tp-hero-lbl">文件数据行</div>
          </div>
          <div class="tp-hero-arrow">→</div>
          <div class="tp-hero-item ok">
            <div class="tp-hero-num">{{ report.will_import }}</div>
            <div class="tp-hero-lbl">将导入</div>
          </div>
          <div class="tp-hero-item" :class="totalSkip ? 'skip' : ''">
            <div class="tp-hero-num">{{ totalSkip }}</div>
            <div class="tp-hero-lbl">将跳过</div>
          </div>
        </div>

        <!-- 列漂移提醒 -->
        <div v-if="hasDrift" class="tp-drift">
          <div class="tp-drift-title">⚠ 检测到原表列与标准模板不一致（已自动适配，导出时按并集还原，不丢列）</div>
          <div v-if="report.extra_columns?.length" class="tp-drift-line">
            新增列（标准模板外）：<b>{{ report.extra_columns.join('、') }}</b>
          </div>
          <div v-if="report.missing_standard?.length" class="tp-drift-line">
            缺失标准列：<b>{{ report.missing_standard.join('、') }}</b>
            <span class="tp-drift-note">（若含「对账单号 / 实际对账金额」会直接报错，其余列缺失仅导出留空）</span>
          </div>
        </div>

        <!-- 将导入清单（可展开抽样） -->
        <div class="tp-group ok-group">
          <div class="tp-group-head" @click="okExpanded = !okExpanded">
            <span class="tp-g-icon">✅</span>
            <span class="tp-g-label">将导入 {{ report.will_import }} 条</span>
            <span class="tp-g-tip">建为「审批通过」记录，请随后在审批管理排款</span>
            <svg v-if="report.ok_sample?.length" class="tp-chev" :class="{ rot: okExpanded }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
          </div>
          <div v-if="okExpanded && report.ok_sample?.length" class="tp-table-wrap">
            <table class="tp-table">
              <thead><tr><th>行</th><th>对账单号</th><th>收款方</th><th>金额</th></tr></thead>
              <tbody>
                <tr v-for="it in report.ok_sample" :key="it.row">
                  <td class="tp-rn">{{ it.row }}</td><td>{{ it.bill_no }}</td>
                  <td class="tp-clip" :title="it.payee">{{ it.payee }}</td>
                  <td class="tp-amt">{{ it.amount }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="report.will_import > report.ok_sample.length" class="tp-more">
              仅预览前 {{ report.ok_sample.length }} 条，确认后将导入全部 {{ report.will_import }} 条
            </div>
          </div>
        </div>

        <!-- 各跳过类别 -->
        <div v-for="g in groups" :key="g.key" class="tp-group" :class="`lv-${g.level}`">
          <div class="tp-group-head" @click="toggle(g.key)">
            <span class="tp-g-icon">{{ g.icon }}</span>
            <span class="tp-g-label">{{ g.label }} {{ g.items.length }} 条</span>
            <span class="tp-g-tip">{{ g.tip }}</span>
            <svg class="tp-chev" :class="{ rot: expanded.has(g.key) }" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
          </div>
          <div v-if="expanded.has(g.key)" class="tp-table-wrap">
            <table class="tp-table">
              <thead><tr><th>行</th><th v-for="c in g.cols" :key="c">{{ COL_LABEL[c] || c }}</th></tr></thead>
              <tbody>
                <tr v-for="(it, i) in g.items" :key="i">
                  <td class="tp-rn">{{ it.row }}</td>
                  <td v-for="c in g.cols" :key="c" :class="{ 'tp-clip': c !== 'bill_no' }" :title="it[c]">
                    {{ it[c] || (c === 'bill_no' ? '(空)' : '') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="!totalSkip && !hasDrift" class="tp-allok">🎉 全部 {{ report.total }} 行均可导入，无跳过、无列异常。</div>
      </div>

      <div class="modal-footer">
        <button class="btn btn-ghost" :disabled="busy" @click="emit('cancel')">取消</button>
        <button class="btn btn-primary" :disabled="busy || !report.will_import" @click="emit('confirm')">
          {{ busy ? '导入中…' : (report.will_import ? `确认导入 ${report.will_import} 条` : '无可导入数据') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tp-modal { width: 620px; max-width: 94vw; }
.tp-body { max-height: 64vh; overflow-y: auto; padding: 2px; }

.tp-hero { display: flex; align-items: center; gap: 14px; padding: 14px 16px; margin-bottom: 12px;
  background: rgba(201,99,66,0.04); border: 1px solid var(--border-soft); border-radius: 12px; }
.tp-hero-item { text-align: center; min-width: 64px; }
.tp-hero-num { font-size: 26px; font-weight: 800; color: var(--text); font-variant-numeric: tabular-nums; }
.tp-hero-item.ok .tp-hero-num { color: var(--c-success); }
.tp-hero-item.skip .tp-hero-num { color: var(--c-warn); }
.tp-hero-lbl { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.tp-hero-arrow { font-size: 20px; color: var(--muted-light); }

.tp-drift { background: var(--c-warn-bg); border: 1px solid var(--c-warn-bdr); border-radius: 10px;
  padding: 10px 13px; margin-bottom: 12px; font-size: 12.5px; color: var(--c-warn); line-height: 1.7; }
.tp-drift-title { font-weight: 700; margin-bottom: 2px; }
.tp-drift-line b { color: #b45309; }
.tp-drift-note { color: var(--muted); font-size: 11px; }

.tp-group { border: 1px solid var(--border-soft); border-radius: 10px; margin-bottom: 8px; overflow: hidden; }
.tp-group.lv-danger { border-color: var(--c-danger-bdr); }
.tp-group.lv-warn { border-color: var(--c-warn-bdr); }
.tp-group-head { display: flex; align-items: center; gap: 8px; padding: 9px 12px; cursor: pointer;
  background: rgba(0,0,0,0.015); transition: background 0.13s; }
.tp-group-head:hover { background: rgba(0,0,0,0.03); }
.tp-g-icon { font-size: 14px; }
.tp-g-label { font-weight: 700; font-size: 13px; color: var(--text); white-space: nowrap; }
.lv-danger .tp-g-label { color: var(--c-danger); }
.tp-g-tip { flex: 1; min-width: 0; font-size: 11.5px; color: var(--muted); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.tp-chev { color: var(--muted); transition: transform 0.18s; flex-shrink: 0; }
.tp-chev.rot { transform: rotate(180deg); }

.tp-table-wrap { max-height: 200px; overflow-y: auto; border-top: 1px solid var(--border-soft); }
.tp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.tp-table th { position: sticky; top: 0; background: #f4f1ef; text-align: left; padding: 5px 10px;
  font-weight: 600; color: var(--text-2); font-size: 11px; white-space: nowrap; }
.tp-table td { padding: 5px 10px; border-bottom: 1px solid var(--border-soft); }
.tp-table tr:last-child td { border-bottom: none; }
.tp-rn { color: var(--muted); width: 40px; font-variant-numeric: tabular-nums; }
.tp-amt { text-align: right; font-variant-numeric: tabular-nums; }
.tp-clip { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tp-more { padding: 6px 10px; font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,0.012); }

.tp-allok { text-align: center; padding: 20px; color: var(--c-success); font-size: 14px; font-weight: 600; }
.ok-group { border-color: var(--c-success-bdr); }
</style>
