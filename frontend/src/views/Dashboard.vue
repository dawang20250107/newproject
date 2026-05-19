<template>
  <div class="page">
    <div class="page-header compact" style="padding:10px 20px;margin-bottom:16px">
      <h1 class="page-title">数据看板</h1>
    </div>

    <!-- 占位提示：后期按飞书多维表格风格重新设计 -->
    <div class="placeholder-card">
      <div class="placeholder-icon">
        <svg width="40" height="40" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="11.1" cy="11.3" r="2.1" fill="currentColor" fill-opacity="0.95"/>
          <circle cx="16" cy="9.5" r="2.3" fill="currentColor" fill-opacity="0.95"/>
          <circle cx="20.9" cy="11.3" r="2.1" fill="currentColor" fill-opacity="0.95"/>
          <path d="M11.9 19.8c0-2.4 1.8-4.4 4.1-4.4s4.1 2 4.1 4.4c0 2.3-1.8 4.1-4.1 4.1s-4.1-1.8-4.1-4.1Z" fill="currentColor" fill-opacity="0.95"/>
        </svg>
      </div>
      <h2 class="placeholder-title">数据看板</h2>
      <p class="placeholder-desc">后期按飞书多维表格风格重新设计，届时可按事业部/部门维度查看汇总数据</p>
      <div class="placeholder-tags">
        <span class="placeholder-tag">6个事业部视图</span>
        <span class="placeholder-tag">多维筛选</span>
        <span class="placeholder-tag">权限分组</span>
      </div>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.placeholder-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  text-align: center;
  gap: 16px;
}
.placeholder-icon {
  width: 80px; height: 80px;
  background: linear-gradient(180deg, rgba(255,243,176,0.34), rgba(255,255,255,0.92));
  border: 1px solid rgba(212,175,55,0.18);
  border-radius: 20px;
  display: flex; align-items: center; justify-content: center;
  color: var(--color-primary);
  box-shadow: 0 10px 24px rgba(212,175,55,0.14);
}
.placeholder-title {
  font-size: 22px; font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}
.placeholder-desc {
  font-size: 14px; color: var(--text-muted);
  max-width: 360px; line-height: 1.6;
}
.placeholder-tags {
  display: flex; gap: 8px; flex-wrap: wrap; justify-content: center;
  margin-top: 4px;
}
.placeholder-tag {
  background: rgba(212,175,55,0.1);
  color: #b8860b;
  border: 1px solid rgba(212,175,55,0.22);
  border-radius: 20px;
  padding: 4px 14px;
  font-size: 12px; font-weight: 500;
}
</style>
