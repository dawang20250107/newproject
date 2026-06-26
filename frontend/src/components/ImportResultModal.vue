<script setup>
// 统一的「导入结果」弹窗：完整展示 成功/跳过 数量与全部未通过校验的行（可滚动，不截断）。
// 付款管理与审批管理共用，避免各自用 alert 截断只显示部分错误。
// result 形如 { created, skipped, errors:[...], message? } 或 { error: '整文件失败原因' }。
defineProps({ result: { type: Object, default: null } })
defineEmits(['close'])
</script>

<template>
  <div v-if="result" class="overlay" @click.self="$emit('close')">
    <div class="modal" style="width:540px">
      <div class="modal-header">
        <h3>{{ result.error ? '导入失败' : '导入完成' }}</h3>
        <button class="modal-close" @click="$emit('close')">×</button>
      </div>

      <!-- 整文件被拒（硬错误） -->
      <div v-if="result.error" class="imp-hero imp-hero-err">
        <div class="imp-emoji">⚠️</div>
        <div class="imp-msg">{{ result.error }}</div>
      </div>

      <template v-else>
        <div class="imp-summary">
          <div class="imp-stat imp-stat-ok">
            <div class="imp-num">{{ result.created || 0 }}</div>
            <div class="imp-lbl">成功导入</div>
          </div>
          <div class="imp-stat" :class="result.skipped ? 'imp-stat-skip' : ''">
            <div class="imp-num">{{ result.skipped || 0 }}</div>
            <div class="imp-lbl">跳过 / 未通过</div>
          </div>
        </div>

        <div v-if="result.message" class="imp-msg-banner">{{ result.message }}</div>

        <div v-if="result.errors && result.errors.length" class="imp-errbox">
          <div class="imp-errtitle">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            以下 {{ result.errors.length }} 行未通过校验，已跳过（可滚动查看全部）：
          </div>
          <ul class="imp-errlist">
            <li v-for="(e, i) in result.errors" :key="i">{{ e }}</li>
          </ul>
        </div>

        <div v-else-if="!result.skipped" class="imp-allok">🎉 全部数据校验通过，无跳过项。</div>
      </template>

      <div class="modal-footer">
        <button class="btn btn-primary" @click="$emit('close')">我知道了</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.imp-hero { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0 8px; text-align: center; }
.imp-emoji { font-size: 44px; }
.imp-msg { font-size: 14px; line-height: 1.6; }
.imp-hero-err .imp-msg { color: #c62828; }
.imp-summary { display: flex; gap: 14px; margin-bottom: 16px; }
.imp-stat { flex: 1; text-align: center; padding: 16px 10px; border-radius: 14px; border: 1px solid var(--border); background: rgba(255,253,250,0.6); }
.imp-stat-ok { background: rgba(46,125,50,0.08); border-color: rgba(46,125,50,0.25); }
.imp-stat-skip { background: rgba(245,127,23,0.09); border-color: rgba(245,127,23,0.3); }
.imp-num { font-size: 30px; font-weight: 800; line-height: 1; }
.imp-stat-ok .imp-num { color: #2e7d32; }
.imp-stat-skip .imp-num { color: #e65100; }
.imp-lbl { font-size: 12px; color: var(--muted); margin-top: 6px; letter-spacing: 0.03em; }
.imp-errbox { border-radius: 12px; border: 1px solid rgba(245,127,23,0.3); background: rgba(245,127,23,0.06); overflow: hidden; }
.imp-errtitle { display: flex; align-items: center; gap: 7px; padding: 10px 14px; font-size: 12.5px; font-weight: 600; color: #e65100; background: rgba(245,127,23,0.1); }
.imp-errtitle svg { flex-shrink: 0; }
.imp-errlist { margin: 0; padding: 8px 14px 10px 30px; max-height: min(52vh, 440px); overflow-y: auto; font-size: 12.5px; line-height: 1.7; color: #b35309; }
.imp-allok { text-align: center; color: #2e7d32; font-size: 13.5px; padding: 6px 0 4px; }
.imp-msg-banner { font-size: 13px; color: #5a4030; background: rgba(201,99,66,0.07); border: 1px solid rgba(201,99,66,0.18); border-radius: 8px; padding: 8px 14px; margin-bottom: 12px; line-height: 1.5; }
</style>
