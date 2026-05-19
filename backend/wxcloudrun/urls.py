from django.conf.urls import url
from wxcloudrun import views

urlpatterns = [
    # 主页
    url(r'^$', views.index, name='index'),

    # ── 仪表板 API ──
    url(r'^api/dashboard/kpi$', views.dashboard_kpi, name='dashboard_kpi'),
    url(r'^api/dashboard/projects-monthly$', views.dashboard_projects_monthly, name='dashboard_projects_monthly'),
    url(r'^api/dashboard/abnormal-ranking$', views.dashboard_abnormal_ranking, name='dashboard_abnormal_ranking'),
    url(r'^api/dashboard/unpaid-distribution$', views.dashboard_unpaid_distribution, name='dashboard_unpaid_distribution'),
    url(r'^api/dashboard/manager-comparison$', views.dashboard_manager_comparison, name='dashboard_manager_comparison'),
    url(r'^api/dashboard/monthly-abnormal$', views.dashboard_monthly_abnormal, name='dashboard_monthly_abnormal'),
    url(r'^api/dashboard/manager/detail$', views.dashboard_manager_detail, name='dashboard_manager_detail'),

    # ── 项目 API（原有：UnpaidRecord 聚合） ──
    url(r'^api/projects$', views.project_list, name='project_list'),
    url(r'^api/projects/(?P<project_id>\d+)$', views.project_detail, name='project_detail'),

    # ── 项目 ERP API（直接查 projects 表，全列） ──
    url(r'^api/projects-erp$', views.projects_erp_list, name='projects_erp_list'),
    url(r'^api/projects-erp/summary$', views.project_erp_summary, name='project_erp_summary'),
    url(r'^api/projects-erp/(?P<project_id>\d+)$', views.project_erp_detail, name='project_erp_detail'),

    # ── 应收账款 API（receivable_data 表） ──
    url(r'^api/receivables$', views.receivables_list, name='receivables_list'),

    # ── 应付管理 API（payment_registrations 表） ──
    url(r'^api/payables/registrations$', views.payables_registrations_list, name='payables_registrations_list'),
    url(r'^api/payables/registrations/summary$', views.payables_registrations_summary, name='payables_registrations_summary'),

    # ── 同步 API ──
    url(r'^api/sync/from-docs$', views.sync_from_docs, name='sync_from_docs'),
]
