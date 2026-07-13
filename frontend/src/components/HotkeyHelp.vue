<script setup>
// 快捷键速查面板：按「?」或导航 ⌨ 按钮呼出。系统已建的键鼠能力都藏在
// 双击/右键/组合键里，没有登记处就等于不存在——新增快捷键请同步补进 GROUPS。
import { hotkeyHelpVisible } from '../composables/useInteractionFeel.js'
import { useModalEsc } from '../composables/useModalEsc.js'

const GROUPS = [
  { title: '全局', keys: [
    ['/', '聚焦当前页搜索框'],
    ['Esc', '清空搜索 → 关闭弹层（分层）'],
    ['?', '打开 / 关闭本面板'],
  ] },
  { title: '表格', keys: [
    ['双击行', '打开明细 / 工作台'],
    ['右键行', '操作菜单（复制 / 编辑 / 以此新建…）'],
    ['双击日期格', '行内快改（对账 / 开票 / 目标回款）'],
    ['Shift + 点击', '区间勾选'],
    ['拖拽框选 + Ctrl/⌘ C', '像 Excel 一样复制单元格'],
    ['列头', '筛选 / 排序（可存入筛选方案）'],
  ] },
  { title: '录入', keys: [
    ['=', '快填系统算好的数（差额 / 全额 / 补齐）'],
    ['Ctrl/⌘ + Enter', '提交当前弹窗'],
    ['保存并继续', '连续录单不关窗（新建弹窗）'],
    ['整行粘贴', '目标网格 / 批量金额支持贴 Excel 一行'],
  ] },
  { title: '连续处理', keys: [
    ['J / K', '工作台上一条 / 下一条'],
    ['双击应收行', '打开连续处理工作台'],
  ] },
]

useModalEsc([() => hotkeyHelpVisible.value, () => { hotkeyHelpVisible.value = false }])
</script>

<template>
  <Teleport to="body">
    <Transition name="hk-fade">
      <div v-if="hotkeyHelpVisible" class="hk-overlay modal-overlay" @click.self="hotkeyHelpVisible = false">
        <div class="hk-card">
          <div class="hk-head">
            <span class="hk-title">⌨ 快捷键速查</span>
            <button class="hk-x" @click="hotkeyHelpVisible = false">×</button>
          </div>
          <div class="hk-grid">
            <div v-for="g in GROUPS" :key="g.title" class="hk-group">
              <div class="hk-g-title">{{ g.title }}</div>
              <div v-for="[k, desc] in g.keys" :key="k" class="hk-row">
                <kbd class="hk-kbd">{{ k }}</kbd>
                <span class="hk-desc">{{ desc }}</span>
              </div>
            </div>
          </div>
          <div class="hk-foot">随时按 <kbd class="hk-kbd">?</kbd> 呼出本面板</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.hk-overlay {
  position: fixed; inset: 0; z-index: 3000;
  background: rgba(40, 30, 22, 0.35);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.hk-card {
  background: var(--card, #fff); border-radius: 16px; max-width: 720px; width: 100%;
  max-height: 84vh; overflow: auto; padding: 18px 22px 14px;
  box-shadow: 0 18px 60px rgba(0,0,0,0.28);
}
.hk-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.hk-title { font-size: 15px; font-weight: 800; color: var(--text); }
.hk-x { border: none; background: none; font-size: 22px; color: var(--muted); cursor: pointer; line-height: 1; }
.hk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 26px; }
@media (max-width: 640px) { .hk-grid { grid-template-columns: 1fr; } }
.hk-g-title {
  font-size: 12px; font-weight: 800; color: var(--muted);
  border-bottom: 1px dashed rgba(150,120,100,0.3); padding-bottom: 4px; margin-bottom: 7px;
}
.hk-row { display: flex; align-items: center; gap: 10px; padding: 3px 0; }
.hk-kbd {
  flex-shrink: 0; min-width: 24px; text-align: center;
  border: 1px solid rgba(150,120,100,0.4); border-bottom-width: 2px; border-radius: 6px;
  background: rgba(180,140,110,0.07); padding: 1px 7px;
  font-size: 11.5px; font-weight: 700; color: var(--text); font-family: inherit;
}
.hk-desc { font-size: 12.5px; color: var(--text); }
.hk-foot { margin-top: 12px; font-size: 11.5px; color: var(--muted); text-align: center; }
.hk-fade-enter-active, .hk-fade-leave-active { transition: opacity .15s; }
.hk-fade-enter-from, .hk-fade-leave-to { opacity: 0; }
</style>
