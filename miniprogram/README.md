# KXT 微信小程序

## 项目结构

```
miniprogram/
├── project.config.json    # 微信开发者工具项目配置
├── sitemap.json            # SEO 配置
└── miniprogram/
    ├── app.js             # 应用入口
    ├── app.json           # 应用配置
    ├── app.wxss           # 全局样式
    ├── pages/
    │   ├── index/         # 数据大屏（首页）
    │   ├── project-list/  # 项目列表
    │   ├── project-detail/# 项目详情
    │   └── mine/          # 个人中心
    └── utils/
        ├── config.js      # API 配置
        └── request.js     # 请求封装
```

## 快速开始

### 1. 导入项目

1. 下载微信开发者工具：https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html
2. 打开开发者工具，点击「导入项目」
3. 选择本目录，`AppID` 填写：`wx67248c26cfe8f21b`

### 2. 配置后端地址

打开 `miniprogram/utils/config.js`，确认 `API_BASE` 为云托管后端地址：

```javascript
API_BASE: 'https://kxtshare-248461-6-1371772686.sh.run.tcloudbase.com',
```

如有变更，请修改此行。

### 3. 编译预览

在微信开发者工具中，点击「编译」即可预览效果。

### 4. 添加 Tab Bar 图标

在 `miniprogram/assets/` 目录下放入以下图标文件（建议尺寸 81×81 PNG）：

| 文件名 | 用途 |
|--------|------|
| tab-dashboard.png / tab-dashboard-active.png | 大屏 Tab |
| tab-project.png / tab-project-active.png | 项目 Tab |
| tab-mine.png / tab-mine-active.png | 我的 Tab |

> 注：如暂不添加图标，TabBar 会显示占位文字。

### 5. 上传发布

1. 点击「上传」按钮
2. 在微信公众平台 (https://mp.weixin.qq.com) 提交审核
3. 审核通过后即可发布

## 功能模块

| 页面 | 功能说明 |
|------|---------|
| 数据大屏 | 6个KPI指标 + 异常排名 + 分布图 + 负责人对比 + 月度趋势 |
| 项目列表 | 搜索 + 分页 + 项目卡片，含金额和逾期信息 |
| 项目详情 | 单项目完整数据，含月度明细表和回款进度条 |
| 个人中心 | 系统信息和快捷操作 |

## API 端点

| 接口 | 说明 |
|------|------|
| `/api/dashboard/kpi` | 核心KPI |
| `/api/dashboard/abnormal-ranking` | 异常排名 |
| `/api/dashboard/unpaid-distribution` | 未收款分布 |
| `/api/dashboard/manager-comparison` | 负责人对比 |
| `/api/dashboard/monthly-abnormal` | 月度异常 |
| `/api/projects` | 项目列表 |
| `/api/projects/<id>` | 项目详情 |

## 数据更新流程

1. 在 1号服务器 更新 MySQL 数据
2. Django 后端自动读取并提供 API
3. 小程序下拉刷新获取最新数据
