<script setup>
import { ref } from 'vue'
import {
  DIM_FIELDS, DATE_FIELDS, AMT_FIELDS,
} from '../../composables/arConditions.js'
import FilterLeaf from './FilterLeaf.vue'

// Power BI 式筛选面板：顶部 且/或（组间连接）+ 顶层条件 / 条件组（括号）列表。
// 条件对象：叶子(t=dim/date/amt) 或 条件组(t=group,{match,conditions:[叶子]})。
// 组内自带 且/或，组间用顶层 match 连接，即可表达「(A 且 B) 或 C」这类带括号筛选。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },   // conditions（含叶子与组）
  match: { type: String, default: 'all' },           // 'all'(且) | 'any'(或)：组间/顶层连接
  accessibleDepts: { type: Array, default: () => [] },
  years: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'update:match', 'change', 'close'])

// 添加菜单：addTarget = 'top'（追加到顶层）或某个 group 对象（追加到组内）
const addMenuOpen = ref(false)
const addTarget = ref('top')
const addMenuPos = ref({ top: 0, left: 0 })

function commit(list) { emit('update:modelValue', list); emit('change') }
function setMatch(m) { emit('update:match', m); emit('change') }
function patch() { commit(props.modelValue.slice()) }       // 叶子就地编辑后整体回传
function removeTop(i) { const l = props.modelValue.slice(); l.splice(i, 1); commit(l) }
function setGroupMatch(g, m) { g.match = m; patch() }
function removeFromGroup(g, j) {
  g.conditions.splice(j, 1)
  // 组被删空 → 顺带把空组从顶层移除，避免遗留空括号
  if (!g.conditions.length) {
    const i = props.modelValue.indexOf(g)
    if (i >= 0) return removeTop(i)
  }
  patch()
}

// ── 叶子工厂：按字段类型给默认值（与各编辑器一致）────────────────────────────
function makeLeaf(kind, field) {
  if (kind === 'dim') {
    const f = DIM_FIELDS.find(x => x.field === field)
    let value = ''
    const leaf = { t: 'dim', field }
    if (f.kind === 'dept') value = props.accessibleDepts[0] || ''
    else if (f.kind === 'year') value = props.years[0] || ''
    else if (f.kind === 'month') value = 1
    else if (f.kind === 'ym') {
      const d = new Date()
      value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      leaf.end = ''; leaf.exclude = false
    }
    else if (f.kind === 'select') value = f.opts[0].v
    leaf.value = value
    return leaf
  }
  if (kind === 'date') return { t: 'date', field, range: 'this_month', exclude: false, start: '', end: '' }
  return { t: 'amt', field, op: 'ne0', value: '', min: '', max: '' }
}

function openAddMenu(target, event) {
  addTarget.value = target; addMenuOpen.value = true
  if (event?.currentTarget) {
    const r = event.currentTarget.getBoundingClientRect()
    const menuH = 320
    const y = window.innerHeight - r.bottom >= menuH
      ? r.bottom + 6
      : Math.max(8, r.top - menuH - 6)
    addMenuPos.value = { top: y, left: Math.min(r.left, window.innerWidth - 260) }
  }
}
function addLeaf(kind, field) {
  const leaf = makeLeaf(kind, field)
  if (addTarget.value === 'top') {
    commit([...props.modelValue, leaf])
  } else {
    addTarget.value.conditions.push(leaf)
    patch()
  }
  addMenuOpen.value = false
}
function addGroup() {
  // 新组默认带一个维度叶子，避免空括号
  const g = { t: 'group', match: 'all', conditions: [makeLeaf('dim', DIM_FIELDS[0].field)] }
  commit([...props.modelValue, g])
}
</script>

<template>
  <div class="fp">
    <div class="fp-head">
      <div class="fp-match">
        满足
        <button class="seg" :class="{ on: match === 'all' }" @click="setMatch('all')">全部（且）</button>
        <button class="seg" :class="{ on: match === 'any' }" @click="setMatch('any')">任一（或）</button>
        条件
      </div>
      <button class="fp-close" title="关闭" @click="emit('close')">✕</button>
    </div>

    <div class="fp-body">
      <div v-if="!modelValue.length" class="fp-empty">尚无筛选条件，点下方「＋ 添加条件」或「＋ 条件组」。</div>

      <template v-for="(c, i) in modelValue" :key="i">
        <!-- 顶层连接词 -->
        <div class="fp-line">
          <span class="fp-conn" v-if="i > 0">{{ match === 'any' ? '或' : '且' }}</span>
          <span class="fp-conn ghost" v-else>　</span>

          <!-- 条件组（括号）-->
          <div v-if="c.t === 'group'" class="fp-group">
            <div class="fp-group-head">
              <span class="fp-paren">(</span>
              <span class="fp-group-lbl">组内满足</span>
              <button class="seg seg-sm" :class="{ on: (c.match || 'all') === 'all' }" @click="setGroupMatch(c, 'all')">且</button>
              <button class="seg seg-sm" :class="{ on: c.match === 'any' }" @click="setGroupMatch(c, 'any')">或</button>
              <button class="fp-x" title="删除整组" @click="removeTop(i)">✕ 删组</button>
            </div>
            <div class="fp-group-body">
              <div v-for="(sub, j) in c.conditions" :key="j" class="fp-sub" :class="sub.t">
                <span class="fp-conn sm" v-if="j > 0">{{ c.match === 'any' ? '或' : '且' }}</span>
                <span class="fp-conn sm ghost" v-else>　</span>
                <FilterLeaf :cond="sub" :accessible-depts="accessibleDepts" :years="years"
                  @change="patch()" @remove="removeFromGroup(c, j)" />
              </div>
              <button class="fp-add-sm" @click="openAddMenu(c, $event)">＋ 组内条件</button>
            </div>
            <span class="fp-paren close">)</span>
          </div>

          <!-- 顶层叶子 -->
          <div v-else class="fp-leaf" :class="c.t">
            <FilterLeaf :cond="c" :accessible-depts="accessibleDepts" :years="years"
              @change="patch()" @remove="removeTop(i)" />
          </div>
        </div>
      </template>
    </div>

    <div class="fp-foot">
      <div class="fp-add-wrap">
        <button class="fp-add" :class="{ on: addMenuOpen && addTarget === 'top' }" @click="openAddMenu('top', $event)">＋ 添加条件</button>
        <button class="fp-add ghost" @click="addGroup">＋ 条件组</button>
        <div v-if="addMenuOpen" class="fp-backdrop" @click="addMenuOpen = false"></div>
        <div v-if="addMenuOpen" class="fp-menu" :style="{ top: addMenuPos.top + 'px', left: addMenuPos.left + 'px' }">
          <div class="fp-menu-grp">维度</div>
          <button v-for="f in DIM_FIELDS" :key="f.field" class="fp-menu-item" @click="addLeaf('dim', f.field)">{{ f.label }}</button>
          <div class="fp-menu-grp">日期</div>
          <button v-for="f in DATE_FIELDS" :key="f.field" class="fp-menu-item" @click="addLeaf('date', f.field)">{{ f.label }}</button>
          <div class="fp-menu-grp">金额</div>
          <button v-for="f in AMT_FIELDS" :key="f.field" class="fp-menu-item" @click="addLeaf('amt', f.field)">{{ f.label }}</button>
        </div>
      </div>
      <button v-if="modelValue.length" class="fp-clear" @click="commit([])">清空全部</button>
    </div>
  </div>
</template>

<style scoped>
.fp { width: 100%; display: flex; flex-direction: column; max-height: 72vh; }
.fp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; border-bottom: 1px solid var(--border);
}
.fp-match { font-size: 13px; color: var(--text); display: flex; align-items: center; gap: 6px; }
.seg {
  border: 1px solid var(--border); background: #fff; cursor: pointer;
  font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 7px; color: var(--muted);
}
.seg.on { border-color: var(--primary); background: rgba(201,99,66,0.08); color: var(--primary); }
.seg-sm { padding: 2px 8px; font-size: 11px; }
.fp-close { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 14px; }

.fp-body { padding: 10px 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
.fp-empty { color: var(--muted); font-size: 13px; padding: 8px 0; }
.fp-line { display: flex; align-items: flex-start; gap: 6px; }
.fp-conn { font-size: 11px; font-weight: 800; color: var(--primary); width: 18px; text-align: center; flex-shrink: 0; padding-top: 9px; }
.fp-conn.sm { padding-top: 7px; }
.fp-conn.ghost { color: transparent; }

.fp-leaf {
  display: flex; align-items: center; flex: 1; gap: 6px;
  padding: 6px 8px; border-radius: 9px; border: 1px solid var(--border);
}
.fp-leaf.dim  { background: rgba(120,120,120,0.04); }
.fp-leaf.date { background: rgba(122,159,212,0.07); border-color: rgba(122,159,212,0.4); }
.fp-leaf.amt  { background: rgba(201,99,66,0.06); border-color: rgba(201,99,66,0.4); }

/* 条件组（括号）容器 */
.fp-group { flex: 1; border: 1.5px solid var(--primary); border-radius: 11px; background: rgba(201,99,66,0.03); position: relative; }
.fp-group-head { display: flex; align-items: center; gap: 6px; padding: 7px 10px 4px; }
.fp-group-lbl { font-size: 11px; color: var(--muted); font-weight: 700; }
.fp-paren { font-size: 18px; font-weight: 800; color: var(--primary); line-height: 1; }
.fp-paren.close { position: absolute; right: 10px; bottom: 6px; }
.fp-group-body { padding: 2px 10px 10px; display: flex; flex-direction: column; gap: 6px; }
.fp-sub {
  display: flex; align-items: center; gap: 6px;
  padding: 5px 8px; border-radius: 8px; border: 1px solid var(--border); background: #fff;
}
.fp-sub.date { background: rgba(122,159,212,0.06); border-color: rgba(122,159,212,0.35); }
.fp-sub.amt  { background: rgba(201,99,66,0.05); border-color: rgba(201,99,66,0.35); }

.fp-x { margin-left: auto; border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 11px; font-weight: 700; }
.fp-x:hover { color: #c62828; }
.fp-add-sm {
  align-self: flex-start; margin-top: 2px;
  border: 1px dashed var(--primary); border-radius: 7px; padding: 3px 10px;
  font-size: 12px; font-weight: 700; cursor: pointer; background: transparent; color: var(--primary);
}
.fp-add-sm:hover { background: rgba(201,99,66,0.07); }

.fp-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 10px 14px; border-top: 1px solid var(--border);
}
.fp-add-wrap { position: relative; display: flex; gap: 8px; }
.fp-add {
  border: 1px dashed var(--primary); border-radius: 8px; padding: 5px 12px;
  font-size: 13px; font-weight: 700; cursor: pointer; background: transparent; color: var(--primary);
}
.fp-add.ghost { border-color: var(--border); color: var(--muted); }
.fp-add.on, .fp-add:hover { background: rgba(201,99,66,0.07); }
.fp-add.ghost:hover { background: rgba(120,120,120,0.06); color: var(--text); }
.fp-clear { border: none; background: transparent; cursor: pointer; color: var(--muted); font-size: 12px; }
.fp-clear:hover { color: #c62828; }
.fp-backdrop { position: fixed; inset: 0; z-index: 60; }
.fp-menu {
  position: fixed; z-index: 61;
  min-width: 240px; max-height: 320px; overflow-y: auto; padding: 8px;
  border-radius: 12px; background: #fff; border: 1px solid var(--border); box-shadow: 0 12px 32px rgba(0,0,0,0.16);
  display: grid; grid-template-columns: 1fr 1fr; gap: 2px 6px;
}
.fp-menu-grp { grid-column: 1 / -1; font-size: 11px; color: var(--muted); font-weight: 700; padding: 7px 8px 3px; }
.fp-menu-item {
  display: block; width: 100%; text-align: left; border: none; background: transparent;
  padding: 8px 10px; border-radius: 7px; font-size: 13.5px; cursor: pointer; color: var(--text); white-space: nowrap;
}
.fp-menu-item:hover { background: rgba(201,99,66,0.08); color: var(--primary); }
</style>
