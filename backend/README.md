# KXT Django 后端

微信云托管 Django 后端服务，为 KXT 数据分析平台提供 RESTful API。

## 技术栈

- Django 3.2
- MySQL (PyMySQL)
- django-cors-headers

## 快速开始

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

## API 接口

| 接口                                   | 方法  | 说明      |
| ------------------------------------ | --- | ------- |
| `/api/dashboard/kpi`                 | GET | 核心KPI   |
| `/api/dashboard/projects-monthly`    | GET | 项目×月度堆叠 |
| `/api/dashboard/abnormal-ranking`    | GET | 异常排名    |
| `/api/dashboard/unpaid-distribution` | GET | 未收款分布   |
| `/api/dashboard/manager-comparison`  | GET | 负责人对比   |
| `/api/dashboard/monthly-abnormal`    | GET | 月度异常    |
| `/api/projects`                      | GET | 项目列表    |
| `/api/projects/<id>`                 | GET | 项目详情    |

## 部署

推送到 GitHub 后，在微信云托管控制台选择此仓库部署即可。
