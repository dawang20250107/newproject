from django.urls import path
from . import views

urlpatterns = [
    # auth
    path('register', views.register),
    path('login', views.login),
    path('registration-status', views.registration_status),
    path('me', views.me),

    # users (super_admin)
    path('users', views.users),
    path('users/<int:uid>', views.user_detail),
    path('users/<int:uid>/approve', views.user_approve),
    path('users/<int:uid>/reject', views.user_reject),

    # job-title permission matrix (super_admin)
    path('permissions', views.permissions),
    path('permissions/<str:job>', views.permission_detail),

    # categories
    path('categories/l1', views.categories_l1),
    path('categories/l1/<int:cid>', views.category_l1_detail),
    path('categories/l2', views.categories_l2),
    path('categories/l2/<int:cid>', views.category_l2_detail),
    path('categories/l3', views.categories_l3),
    path('categories/l3/<int:cid>', views.category_l3_detail),

    # data import batches
    path('batches', views.batches),
    path('batches/template', views.batch_template),
    path('batches/upload', views.batch_upload),
    path('batches/submission-status', views.batch_submission_status),
    path('batches/<int:bid>/publish', views.batch_publish),
    path('batches/<int:bid>', views.batch_detail),

    # 项目毛利（业财融合）
    path('project-margin', views.project_margin),
    path('project-margin/upload', views.project_margin_upload),

    # 指标管理 & 财务驾驶舱
    path('targets', views.targets),
    path('targets/template', views.targets_template),
    path('targets/upload', views.targets_upload),
    path('targets/export', views.targets_export),
    path('metrics', views.metrics),
    path('cockpit', views.cockpit),
    path('cockpit/ai-analysis', views.cockpit_ai_analysis),
    path('cockpit/ai-analysis/stream', views.cockpit_ai_analysis_stream),
    path('cockpit/ai-chat/stream', views.cockpit_ai_chat_stream),
    path('cockpit/knowledge', views.cockpit_knowledge),
    path('cockpit/knowledge/distill', views.cockpit_knowledge_distill),
    path('cockpit/knowledge/import', views.cockpit_knowledge_import),
    path('cockpit/knowledge/<int:kid>', views.cockpit_knowledge_detail),

    # report
    path('report', views.report),
    path('report/export', views.report_export),
    path('report/ai-analysis', views.report_ai_analysis),
    path('report/ai-analysis/stream', views.report_ai_analysis_stream),

    # charts
    path('charts/trend', views.chart_trend),
    path('charts/waterfall', views.chart_waterfall),
    path('charts/ai-analysis', views.chart_ai_analysis),
]
