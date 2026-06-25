<script setup>
// 导入预检弹窗（通用）：只展示「需关注」的行（规则错误/疑似重复/AI 疑点），通过的行不渲染、
// 确认时一并导入 —— 即便上万行也只渲染少量问题行，不卡。字段列由后端 columns 驱动，
// 因此可被各模块复用。报告由 /import/precheck 生成。
import { ref, watch, computed } from 'vue'

const props = defineProps({
  report: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  // readonly=true：AR 模式。字段只读、无「采纳」按钮；
  // 有规则错误时只能关闭修Excel；仅AI疑点时可「继续导入」（重提原文件）。
  readonly: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'apply'])

const DISPLAY_CAP = 300
const rows = ref([])
watch(() => props.report, (r) => {
  rows.value = r ? JSON.parse(JSON.stringify(r.rows || [])) : []
}, { immediate: true })

const columns = computed(() => props.report?.columns || [])
const shown = computed(() => rows.value.slice(0, DISPLAY_CAP))
const overflow = computed(() => Math.max(0, rows.value.length - DISPLAY_CAP))

const hasRuleErrors = computed(() => (props.report?.ruleErrors || 0) > 0)

function fieldKey(f) {
  if (columns.value.some(c => c.key === f)) return f
  const hit = columns.value.find(c => c.label === f)
  return hit ? hit.key : null
}
function adopt(r, a) { const k = fieldKey(a.field); if (k && a.suggestion) r.data[k] = a.suggestion }
function sevLabel(s) { return s === 'high' ? '高' : s === 'low' ? '低' : '中' }
function tagText(r) {
  if (r.ruleIssue) return '规则错误：' + r.ruleIssue
  if (r.warn) return r.warn
  return 'AI 疑点'
}
function apply(mode) {
  // paikuan 模式：发送编辑后的行数据给后端 apply 端点
  // readonly(AR)模式：直接通知父组件，父组件重提原文件到 import 端点
  emit('apply', { mode, rows: rows.value, okRows: props.report?.okRows || [] })
}
</script>

<template>
  <div v-if="report" class="overlay" @click.self="$emit('close')">
    <div class="modal pc-modal">
      <div class="modal-header">
        <h3>发现需要确认的数据 <span class="pc-sub">AI 已介入 · 协助你修正后再导入</span></h3>
        <button class="modal-close" @click="$emit('close')">×</button>
      </div>

      <div class="pc-summary">
        <span class="pc-stat">共 <b>{{ report.total }}</b> 行</span>
        <span class="pc-stat ok">通过 <b>{{ report.okCount }}</b></span>
        <span class="pc-stat" :class="{ bad: report.ruleErrors }">规则错误 <b>{{ report.ruleErrors }}</b></span>
        <span class="pc-stat" :class="{ warn: report.warns }">疑似重复 <b>{{ report.warns }}</b></span>
        <span class="pc-stat" :class="{ ai: report.aiFindings }">AI 疑点 <b>{{ report.aiFindings }}</b></span>
        <span v-if="!report.aiEnabled" class="pc-ai-off">AI 未配置 · 仅规则预检</span>
      </div>

      <div class="pc-body">
        <div v-if="!rows.length" class="pc-allok">
          🎉 全部 {{ report.total }} 行均通过校验与复核，可直接确认导入。
        </div>
        <div v-for="(r, i) in shown" :key="i" class="pc-row" :class="r.status">
          <div class="pc-row-head">
            <span class="pc-rn">第 {{ r.row }} 行</span>
            <span class="pc-tag" :class="'pc-tag-' + r.status">{{ tagText(r) }}</span>
          </div>
          <div class="pc-fields">
            <label v-for="col in columns" :key="col.key" :class="{ wide: col.wide || col.key === 'project_desc' }">
              {{ col.label }}
              <input v-if="!readonly" v-model="r.data[col.key]" />
              <span v-else class="pc-ro-val">{{ r.data[col.key] || '—' }}</span>
            </label>
          </div>
          <div v-if="r.ai && r.ai.length" class="pc-ai-list">
            <div v-for="(a, j) in r.ai" :key="j" class="pc-ai" :class="a.severity">
              <span class="pc-ai-sev">AI·{{ sevLabel(a.severity) }}</span>
              <span class="pc-ai-txt"><b>{{ a.field }}</b>：{{ a.issue }}<i v-if="a.suggestion"> · 建议：{{ a.suggestion }}</i></span>
              <button v-if="!readonly && a.suggestion && fieldKey(a.field)" class="pc-adopt" @click="adopt(r, a)">采纳</button>
            </div>
          </div>
        </div>
        <div v-if="overflow" class="pc-overflow">
          还有 <b>{{ overflow }}</b> 条问题未展示（避免卡顿）。建议「下载修正版」在 Excel 中批量处理后再导入。
        </div>
      </div>

      <!-- paikuan 模式：可就地修正 + 下载修正版 + 确认导入 -->
      <div v-if="!readonly" class="modal-footer pc-footer">
        <span class="pc-foot-hint">确认导入会再次校验，仅写入通过的行（已通过 {{ report.okCount }} 行 + 修正后通过的行）</span>
        <button class="btn btn-ghost" :disabled="busy" @click="apply('download')">⬇ 下载修正版</button>
        <button class="btn btn-primary" :disabled="busy" @click="apply('import')">
          {{ busy ? '处理中…' : '确认导入' }}
        </button>
      </div>
      <!-- readonly(AR)模式：规则错误须修Excel；仅AI疑点时可继续导入 -->
      <div v-else class="modal-footer pc-footer">
        <span class="pc-foot-hint">
          <template v-if="hasRuleErrors">存在规则错误，请按提示修改Excel后重新导入。</template>
          <template v-else>上方为 AI 发现的疑点，供你参考。确认无误后可继续导入。</template>
        </span>
        <button class="btn btn-ghost" @click="$emit('close')">取消</button>
        <button v-if="!hasRuleErrors" class="btn btn-primary" :disabled="busy" @click="apply('import')">
          {{ busy ? '处理中…' : '继续导入' }}
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
.pc-stat.ok b { color: #2e7d32; }
.pc-stat.bad b { color: #c62828; }
.pc-stat.warn b { color: #e65100; }
.pc-stat.ai b { color: #1565c0; }
.pc-ai-off { font-size: 11.5px; color: var(--muted); background: rgba(0,0,0,.05); padding: 3px 9px; border-radius: 8px; }
.pc-body { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 2px; }
.pc-allok { text-align: center; color: #2e7d32; font-size: 14px; padding: 28px 8px; }
.pc-row { border: 1px solid var(--border); border-radius: 12px; padding: 11px 13px; background: rgba(255,253,250,.6); }
.pc-row.error { border-color: rgba(198,40,40,.35); background: rgba(198,40,40,.04); }
.pc-row.warn { border-color: rgba(230,81,0,.4); background: rgba(245,127,23,.05); }
.pc-row-head { display: flex; align-items: center; gap: 9px; margin-bottom: 9px; flex-wrap: wrap; }
.pc-rn { font-size: 12px; font-weight: 700; color: var(--muted); }
.pc-tag { font-size: 11.5px; font-weight: 600; padding: 2px 9px; border-radius: 8px; }
.pc-tag-error { color: #c62828; background: rgba(198,40,40,.1); }
.pc-tag-warn { color: #e65100; background: rgba(245,127,23,.12); }
.pc-tag-review { color: #1565c0; background: rgba(21,101,192,.1); }
.pc-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 12px; }
.pc-fields label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--muted); }
.pc-fields label.wide { grid-column: 1 / -1; }
.pc-fields input { border: 1px solid var(--border); border-radius: 7px; padding: 6px 9px; font-size: 13px; color: var(--text); background: #fff; }
.pc-fields input:focus { border-color: var(--primary); outline: none; }
.pc-ro-val { border: 1px solid var(--border); border-radius: 7px; padding: 6px 9px; font-size: 13px; color: var(--text); background: #f7f5f3; display: block; }
.pc-ai-list { margin-top: 9px; display: flex; flex-direction: column; gap: 5px; }
.pc-ai { display: flex; align-items: center; gap: 8px; font-size: 12px; padding: 6px 9px; border-radius: 8px; background: rgba(21,101,192,.06); }
.pc-ai.high { background: rgba(198,40,40,.08); }
.pc-ai-sev { flex-shrink: 0; font-size: 10.5px; font-weight: 700; color: #1565c0; background: rgba(21,101,192,.12); padding: 1px 7px; border-radius: 7px; }
.pc-ai.high .pc-ai-sev { color: #c62828; background: rgba(198,40,40,.14); }
.pc-ai-txt { flex: 1; color: #4a4030; line-height: 1.5; }
.pc-ai-txt i { color: var(--muted); font-style: normal; }
.pc-adopt { flex-shrink: 0; border: 1px solid var(--primary); background: #fff; color: var(--primary); border-radius: 7px; font-size: 11.5px; font-weight: 600; padding: 3px 11px; cursor: pointer; }
.pc-adopt:hover { background: rgba(201,99,66,.08); }
.pc-overflow { text-align: center; font-size: 12px; color: #b35309; background: rgba(245,127,23,.08); border: 1px dashed rgba(245,127,23,.4); border-radius: 10px; padding: 10px; }
.pc-footer { display: flex; align-items: center; gap: 10px; }
.pc-foot-hint { flex: 1; font-size: 11.5px; color: var(--muted); }
</style>
