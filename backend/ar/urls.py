from django.urls import path
from ar import views

urlpatterns = [
    # Projects
    path('projects', views.projects),
    path('projects/template', views.project_template),
    path('projects/import', views.project_import),
    path('projects/export', views.project_export),
    path('projects/<int:pk>', views.project_detail),

    # AR Records
    path('records', views.ar_records),
    path('records/template', views.ar_record_template),
    path('records/import', views.ar_record_import),
    path('records/export', views.ar_record_export),
    path('records/<int:pk>', views.ar_record_detail),
    path('records/<int:pk>/payments', views.ar_payments),
    path('records/<int:pk>/payments/<int:ppk>', views.ar_payment_detail),

    # Analytics
    path('analytics/aging', views.analytics_aging),
    path('analytics/collection-rate', views.analytics_collection_rate),
    path('analytics/outstanding-top', views.analytics_outstanding_top),
    path('analytics/status-dist', views.analytics_status_dist),

    # Cashflow comparison
    path('cashflow', views.cashflow),

    # Budget
    path('budget/collection', views.budget_collection),
    path('budget/collection/<int:pk>', views.budget_collection_detail),
    path('budget/payment', views.budget_payment),
    path('budget/payment/<int:pk>', views.budget_payment_detail),
    path('budget/summary', views.budget_summary),
]
