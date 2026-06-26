# 集团财务管理平台

业财融合的财务管理系统，覆盖应收账款、资金排款付款、经营驾驶舱三大业务域。
后端 Django（单一计算正源），前端 Vue 3，前端构建产物随后端一同部署。

## 技术栈

- **后端**：Django + Django REST 风格视图，按业务域拆分应用（`ar` / `caiwu` / `paikuan`）
- **前端**：Vue 3（Composition API）+ Vite，源码在 `frontend/`，构建产物提交于 `backend/frontend_dist/` 由 Django 直接服务
- **鉴权**：JWT，登录后每个受保护请求重载当前用户并校验在职/审批状态、岗位权限、事业部隔离

## 目录结构

```
backend/
  ar/        应收账款域 —— 应收台账、回款、差额调整、账龄、周期报表、现金流、资金池
  caiwu/     财务分析域 —— 经营数据、利润表、预算、驾驶舱、知识库
  paikuan/   排款付款域 —— 审批管理、排款管理、付款管理（与应收双向同步留痕）
  frontend_dist/   前端构建产物（npm run build 生成，随后端部署）
frontend/
  src/       Vue 3 源码（视图、组件、API 封装、组合式函数）
```

## 本地开发

```bash
# 后端
cd backend
python manage.py migrate
python manage.py runserver

# 前端（开发热更新）
cd frontend
npm install
npm run dev

# 前端构建（产物输出到 backend/frontend_dist/，需提交）
cd frontend
npm run build
```

## 测试

```bash
cd backend
python manage.py test          # 全量
python manage.py test ar       # 指定业务域
```

变更记录见 [CHANGELOG.md](CHANGELOG.md)。
