from django.urls import path
from ar import views

urlpatterns = [
    # Projects
    path('projects', views.projects),
    path('projects/stats', views.project_stats),
    path('projects/template', views.project_template),
    path('projects/import', views.project_import),
    path('projects/export', views.project_export),
    path('projects/<int:pk>', views.project_detail),

    # AR Records
    path('records/date-bounds', views.ar_records_date_bounds),
    path('records', views.ar_records),
    path('records/kpi', views.ar_records_kpi),
    path('records/summary', views.ar_records_group_summary),
    path('records/payments', views.ar_payment_ledger),
    path('records/payments/export', views.ar_payment_ledger_export),
    path('records/template', views.ar_record_template),
    path('records/import', views.ar_record_import),
    path('records/export', views.ar_record_export),
    path('records/health', views.ar_data_health),
    path('records/recompute', views.ar_records_recompute_bulk),
    path('records/<int:pk>', views.ar_record_detail),
    path('records/<int:pk>/recompute', views.ar_record_recompute),
    path('records/<int:pk>/payments', views.ar_payments),
    path('records/<int:pk>/payments/<int:ppk>', views.ar_payment_detail),

    # 预收预付 (advances)
    path('advances', views.advances),
    path('advances/kpi', views.advances_kpi),
    path('advances/summary', views.advances_summary),
    path('advances/available', views.advances_available),
    path('advances/template', views.advance_template),
    path('advances/import', views.advance_import),
    path('advances/export', views.advance_export),
    path('advances/<int:pk>', views.advance_detail),
    path('advances/<int:pk>/writeoffs', views.advance_writeoffs),
    path('advances/<int:pk>/writeoffs/<int:wid>', views.advance_writeoff_detail),

    # Analytics
    path('analytics/aging', views.analytics_aging),
    path('analytics/collection-rate', views.analytics_collection_rate),
    path('analytics/outstanding-top', views.analytics_outstanding_top),
    path('analytics/status-dist', views.analytics_status_dist),
    path('analytics/by-pm', views.analytics_by_pm),

    # Cashflow comparison
    path('cashflow', views.cashflow),

    # Budget
    path('budget/collection', views.budget_collection),
    path('budget/collection/template', views.budget_collection_template),
    path('budget/collection/import', views.budget_collection_import),
    path('budget/collection/export', views.budget_collection_export),
    path('budget/collection/<int:pk>', views.budget_collection_detail),
    path('budget/payment', views.budget_payment),
    path('budget/payment/template', views.budget_payment_template),
    path('budget/payment/import', views.budget_payment_import),
    path('budget/payment/export', views.budget_payment_export),
    path('budget/payment/<int:pk>', views.budget_payment_detail),
    path('budget/summary', views.budget_summary),
]
