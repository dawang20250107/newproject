<script setup>
// 导入预检弹窗：展示「规则预检 + AI 智能复核」逐行报告，支持就地修正、采纳 AI 建议，
// 再「确认导入」或「下载修正版」。报告由后端 /import/precheck 生成。
import { ref, watch, computed } from 'vue'

const props = defineProps({ report: { type: Object, default: null }, busy: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'apply'])

const rows = ref([])
watch(() => props.report, (r) => {
  rows.value = r ? JSON.parse(JSON.stringify(r.rows || [])) : []
}, { immediate: true })

const FIELD_KEYS = ['department', 'payee', 'total_amount', 'planned_date', 'approval_number', 'project_desc']
const LABEL2KEY = {
  部门: 'department', 收款方: 'payee', 计划金额: 'total_amount', 计划总金额: 'total_amount',
  计划日期: 'planned_date', 计划付款日期: 'planned_date', 审批单号: 'approval_number',
  审批编号: 'approval_number', 付款事项: 'project_desc',
}
function fieldKey(f) { return FIELD_KEYS.includes(f) ? f : LABEL2KEY[f] }
function adopt(r, a) { const k = fieldKey(a.field); if (k && a.suggestion) r.data[k] = a.suggestion }
function sevLabel(s) { return s === 'high' ? '高' : s === 'low' ? '低' : '中' }

const okCount = computed(() => rows.value.filter(r => !r.ruleIssue).length)
</script>

<template>
  <div v-if="report" class="overlay" @click.self="$emit('close')">
    <div class="modal pc-modal">
      <div class="modal-header">
        <h3>导入预检 <span class="pc-sub">规则校验 + AI 智能复核</span></h3>
        <button class="modal-close" @click="$emit('close')">×</button>
      </div>

      <div class="pc-summary">
        <span class="pc-stat">共 <b>{{ report.total }}</b> 行</span>
        <span class="pc-stat" :class="{ bad: report.ruleErrors }">规则错误 <b>{{ report.ruleErrors }}</b></span>
        <span class="pc-stat" :class="{ ai: report.aiFindings }">AI 疑点 <b>{{ report.aiFindings }}</b></span>
        <span v-if="!report.aiEnabled" class="pc-ai-off">AI 未配置 · 仅规则预检</span>
      </div>

      <div class="pc-body">
        <div v-for="(r, i) in rows" :key="i" class="pc-row" :class="{ err: r.ruleIssue }">
          <div class="pc-row-head">
            <span class="pc-rn">第 {{ r.row }} 行</span>
            <span v-if="r.ruleIssue" class="pc-tag pc-tag-err">规则错误：{{ r.ruleIssue }}</span>
            <span v-else-if="r.warn" class="pc-tag pc-tag-warn">{{ r.warn }}</span>
            <span v-else class="pc-tag pc-tag-ok">✓ 校验通过</span>
          </div>
          <div class="pc-fields">
            <label>部门<input v-model="r.data.department" /></label>
            <label>收款方<input v-model="r.data.payee" /></label>
            <label>计划金额<input v-model="r.data.total_amount" /></label>
            <label>计划日期<input v-model="r.data.planned_date" /></label>
            <label>审批单号<input v-model="r.data.approval_number" /></label>
            <label class="wide">付款事项<input v-model="r.data.project_desc" /></label>
          </div>
          <div v-if="r.ai && r.ai.length" class="pc-ai-list">
            <div v-for="(a, j) in r.ai" :key="j" class="pc-ai" :class="a.severity">
              <span class="pc-ai-sev">AI·{{ sevLabel(a.severity) }}</span>
              <span class="pc-ai-txt"><b>{{ a.field }}</b>：{{ a.issue }}<i v-if="a.suggestion"> · 建议：{{ a.suggestion }}</i></span>
              <button v-if="a.suggestion && fieldKey(a.field)" class="pc-adopt" @click="adopt(r, a)">采纳</button>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-footer pc-footer">
        <span class="pc-foot-hint">就地修正后再导入；导入会再次校验，仅写入通过的行（当前 {{ okCount }} 行通过）</span>
        <button class="btn btn-ghost" :disabled="busy" @click="$emit('apply', { mode: 'download', rows })">⬇ 下载修正版</button>
        <button class="btn btn-primary" :disabled="busy" @click="$emit('apply', { mode: 'import', rows })">
          {{ busy ? '处理中…' : `确认导入（${rows.length} 行）` }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pc-modal { width: min(860px, 96vw); max-height: 88vh; display: flex; flex-direction: column; }
.pc-sub { font-size: 12px; font-weight: 500; color: var(--muted); margin-left: 8px; }
.pc-summary { display: flex; gap: 16px; align-items: center; padding: 10px 2px 14px; flex-wrap: wrap; }
.pc-stat { font-size: 13px; color: var(--muted); }
.pc-stat b { font-size: 18px; color: var(--text); margin: 0 2px; }
.pc-stat.bad b { color: #e65100; }
.pc-stat.ai b { color: #1565c0; }
.pc-ai-off { font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,.05); padding: 3px 9px; border-radius: 8px; }
.pc-body { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 2px; }
.pc-row { border: 1px solid var(--border); border-radius: 12px; padding: 11px 13px; background: rgba(255,253,250,.6); }
.pc-row.err { border-color: rgba(230,81,0,.4); background: rgba(245,127,23,.05); }
.pc-row-head { display: flex; align-items: center; gap: 9px; margin-bottom: 9px; flex-wrap: wrap; }
.pc-rn { font-size: 12px; font-weight: 700; color: var(--muted); }
.pc-tag { font-size: 11.5px; font-weight: 600; padding: 2px 9px; border-radius: 8px; }
.pc-tag-err { color: #c62828; background: rgba(198,40,40,.1); }
.pc-tag-warn { color: #e65100; background: rgba(245,127,23,.12); }
.pc-tag-ok { color: #2e7d32; background: rgba(46,125,50,.1); }
.pc-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 12px; }
.pc-fields label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--muted); }
.pc-fields label.wide { grid-column: 1 / -1; }
.pc-fields input { border: 1px solid var(--border); border-radius: 7px; padding: 6px 9px; font-size: 13px; color: var(--text); background: #fff; }
.pc-fields input:focus { border-color: var(--primary); outline: none; }
.pc-ai-list { margin-top: 9px; display: flex; flex-direction: column; gap: 5px; }
.pc-ai { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 6px 9px; border-radius: 8px; background: rgba(21,101,192,.06); }
.pc-ai.high { background: rgba(198,40,40,.08); }
.pc-ai-sev { flex-shrink: 0; font-size: 10.5px; font-weight: 700; color: #1565c0; background: rgba(21,101,192,.12); padding: 1px 7px; border-radius: 7px; }
.pc-ai.high .pc-ai-sev { color: #c62828; background: rgba(198,40,40,.14); }
.pc-ai-txt { flex: 1; color: #4a4030; line-height: 1.5; }
.pc-ai-txt i { color: var(--muted); font-style: normal; }
.pc-adopt { flex-shrink: 0; border: 1px solid var(--primary); background: #fff; color: var(--primary); border-radius: 7px; font-size: 11.5px; font-weight: 600; padding: 3px 11px; cursor: pointer; }
.pc-adopt:hover { background: rgba(201,99,66,.08); }
.pc-footer { display: flex; align-items: center; gap: 10px; }
.pc-foot-hint { flex: 1; font-size: 11.5px; color: var(--muted); }
</style>
