<script setup>
import { inject, computed } from 'vue'

// 可排序表头：点击循环 升/降/取消，激活时高亮并显示方向箭头。
// 通过 inject('arSort') 取排序状态机，避免逐列透传 props。
// 父用法：<SortTh col="estimated" label="预估金额" class="amt" />
//（amt/ctr 等对齐类会自动透传到根 <th>）
const props = defineProps({
  col: { type: String, required: true },
  label: { type: String, required: true },
})

const sorter = inject('arSort', null)
const dir = computed(() => (sorter ? sorter.dir(props.col) : ''))
function onClick() { sorter && sorter.toggle(props.col) }
</script>

<template>
  <th
    class="sort-th" :class="{ 'is-sorted': dir }" role="button"
    :aria-sort="dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'"
    :title="`按${label}排序`" @click="onClick"
  >
    <span class="sort-inner">
      <span>{{ label }}</span>
      <span class="caret" :class="dir" aria-hidden="true">
        <svg width="8" height="11" viewBox="0 0 8 11">
          <path class="c-up" d="M4 0.5L7 4.5H1z" />
          <path class="c-dn" d="M4 10.5L1 6.5H7z" />
        </svg>
      </span>
    </span>
  </th>
</template>

<style scoped>
.sort-th { cursor: pointer; user-select: none; white-space: nowrap; }
.sort-th:hover { background: rgba(201,99,66,.06); }
.sort-th.is-sorted { color: var(--primary); }
.sort-inner { display: inline-flex; align-items: center; gap: 3px; }
.caret svg { display: block; }
.caret path { fill: var(--muted); opacity: .32; transition: opacity .12s, fill .12s; }
.caret.asc .c-up { opacity: 1; fill: var(--primary); }
.caret.desc .c-dn { opacity: 1; fill: var(--primary); }
</style>
