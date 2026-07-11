<script setup>
// 行勾选单元格（系统级复用）：内部封装 useShiftSelect 需要的 (event, idx, id)
// 三参签名——审计曾发现两个页面因手抄参数错位导致多选整体失效，同一段模板
// 在 6 个页面抄了 6 遍。统一从此组件走，签名只写一次。
//
// 用法：<SelCell :idx="idx" :id="r.id" :checked="selectedIds.has(r.id)" :on-sel="onRowSelClick" />
// class（如 sticky-col）会透传合并到 td 上；统一输出 sel-col 类，
// 自动获得全局整格热区（useInteractionFeel）与勾选列双击抑制。
defineProps({
  idx:      { type: Number, required: true },
  id:       { required: true },
  checked:  { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  onSel:    { type: Function, required: true },   // useShiftSelect 的 onRowSelClick
})
</script>

<template>
  <td class="sel-col">
    <input type="checkbox" :checked="checked" :disabled="disabled"
           title="按住 Shift 点击可区间勾选"
           @click="onSel($event, idx, id)" @change.prevent />
  </td>
</template>
