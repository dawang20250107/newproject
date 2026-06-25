from django.urls import path
from ar import views

urlpatterns = [
    # Projects
    path('projects', views.projects),
    path('projects/bulk-delete', views.projects_bulk_delete),
    path('projects/stats', views.project_stats),
    path('projects/drafts', views.project_drafts),
    path('projects/drafts/promote', views.project_drafts_promote),
    path('projects/template', views.project_template),
    path('projects/import', views.project_import),
    path('projects/import/precheck', views.project_import_precheck),
    path('projects/export', views.project_export),
    path('projects/<int:pk>', views.project_detail),

    # Customers
    path('customers', views.customers),
    path('customers/bulk-delete', views.customers_bulk_delete),
    path('customers/bulk-tag-level', views.customers_bulk_tag_level),
    path('customers/sync-from-projects', views.customers_sync_from_projects),
    path('customers/<int:pk>', views.customer_detail),

    # Contracts
    path('contracts', views.contracts),
    path('contracts/<int:pk>', views.contract_detail),

    # AR Records
    path('records/date-bounds', views.ar_records_date_bounds),
    path('records/distinct-values', views.ar_records_distinct_values),
    path('records', views.ar_records),
    path('records/kpi', views.ar_records_kpi),
    path('records/summary', views.ar_records_group_summary),
    path('records/payments', views.ar_payment_ledger),
    path('records/payments/export', views.ar_payment_ledger_export),
    path('records/collection', views.ar_collection_workbench),
    path('records/collection/dunning', views.ar_collection_dunning),
    path('records/invoice-batches', views.ar_invoice_batches),
    path('records/invoice-batches/<str:batch_no>', views.ar_invoice_batch_detail),
    path('records/invoice-batches/<str:batch_no>/invoice', views.ar_invoice_batch_invoice),
    path('records/invoice-batches/<str:batch_no>/invoice-undo', views.ar_invoice_batch_invoice_undo),
    path('records/invoice-batches/<str:batch_no>/payment', views.ar_invoice_batch_payment),
    path('records/invoice-batches/<str:batch_no>/payment-undo', views.ar_invoice_batch_payment_undo),
    path('records/batch-assign', views.ar_records_batch_assign),
    path('records/template', views.ar_record_template),
    path('records/import', views.ar_record_import),
    path('records/import/precheck', views.ar_record_import_precheck),
    path('records/export', views.ar_record_export),
    path('records/health', views.ar_data_health),
    path('records/recompute', views.ar_records_recompute_bulk),
    path('records/bulk-assign-collector', views.ar_records_bulk_assign_collector),
    path('records/bulk-delete', views.ar_records_bulk_delete),
    path('records/<int:pk>', views.ar_record_detail),
    path('records/<int:pk>/recompute', views.ar_record_recompute),
    path('records/<int:pk>/payments', views.ar_payments),
    path('records/<int:pk>/payments/<int:ppk>', views.ar_payment_detail),
    path('records/<int:pk>/adjustments', views.ar_adjustments),
    path('records/<int:pk>/adjustments/<int:aid>', views.ar_adjustment_detail),

    # 账龄分桶边界配置
    path('aging-config', views.ar_aging_config),

    # 筛选方案 (filter schemes)：命名保存高级筛选，私有/公共团队共享 + 默认方案
    path('filter-schemes', views.ar_filter_schemes),
    path('filter-schemes/set-default', views.ar_filter_scheme_default),
    path('filter-schemes/<int:pk>', views.ar_filter_scheme_detail),

    # 供应商池 (suppliers)
    path('suppliers', views.suppliers),
    path('suppliers/search', views.supplier_search),
    path('suppliers/<int:pk>', views.supplier_detail),

    # 预收预付 (advances)
    path('advances', views.advances),
    path('advances/kpi', views.advances_kpi),
    path('advances/summary', views.advances_summary),
    path('advances/available', views.advances_available),
    path('advances/offsettable', views.advance_offsettable_records),
    path('advances/template', views.advance_template),
    path('advances/import', views.advance_import),
    path('advances/import/precheck', views.advance_import_precheck),
    path('advances/export', views.advance_export),
    path('advances/<int:pk>', views.advance_detail),
    path('advances/offset-workbench', views.advance_offset_workbench),
    path('advances/diff-summary', views.advance_diff_summary),
    path('advances/diff-timeline', views.advance_diff_timeline),
    path('advances/diff-timeline/export', views.advance_diff_timeline_export),
    path('advances/<int:pk>/batch-writeoff', views.advance_batch_writeoff),
    path('advances/<int:pk>/installments', views.advance_installments),
    path('advances/<int:pk>/installments/<int:iid>', views.advance_installment_detail),
    path('advances/<int:pk>/writeoffs', views.advance_writeoffs),
    path('advances/<int:pk>/writeoffs/<int:wid>', views.advance_writeoff_detail),

    # Analytics
    path('analytics/aging', views.analytics_aging),
    path('analytics/collection-rate', views.analytics_collection_rate),
    path('analytics/outstanding-top', views.analytics_outstanding_top),
    path('analytics/status-dist', views.analytics_status_dist),
    path('analytics/by-pm', views.analytics_by_pm),
    path('analytics/by-dept', views.analytics_by_dept),
    path('analytics/unit-economics', views.analytics_unit_economics),
    path('analytics/business-finance', views.analytics_business_finance),
    path('analytics/project-pnl', views.analytics_project_pnl),
    path('analytics/project-cashflow', views.analytics_project_cashflow),
    path('analytics/forecast', views.analytics_forecast),
    path('analytics/target-decomp', views.analytics_target_decomp),
    path('analytics/aging-by-customer', views.analytics_aging_by_customer),

    # P4 行动项
    path('actions', views.ar_actions),
    path('actions/from-signal', views.ar_actions_from_signal),
    path('actions/<int:pk>', views.ar_action_detail),

    # Cashflow comparison
    path('cashflow', views.cashflow),

    # 周期报表（周报 / 月报）
    path('periodic-report', views.periodic_report),
    path('periodic-report/export', views.periodic_report_export),

    # 资金池 (cash pool)
    path('pool', views.cash_pool),
    path('pool/config', views.cash_pool_config),
    path('pool/transfers', views.cash_pool_transfers),
    path('pool/transfers/<int:pk>', views.cash_pool_transfer_detail),
    path('pool/transfers/<int:pk>/review', views.cash_pool_transfer_review),

    # Budget
    path('budget/collection', views.budget_collection),
    path('budget/collection/template', views.budget_collection_template),
    path('budget/collection/import', views.budget_collection_import),
    path('budget/collection/import/precheck', views.budget_collection_import_precheck),
    path('budget/collection/export', views.budget_collection_export),
    path('budget/collection/<int:pk>', views.budget_collection_detail),
    path('budget/payment', views.budget_payment),
    path('budget/payment/template', views.budget_payment_template),
    path('budget/payment/import', views.budget_payment_import),
    path('budget/payment/import/precheck', views.budget_payment_import_precheck),
    path('budget/payment/export', views.budget_payment_export),
    path('budget/payment/<int:pk>', views.budget_payment_detail),
    path('budget/summary', views.budget_summary),
    path('budget/project-compare', views.budget_project_compare),

    # 催收跟进日志
    path('records/<int:pk>/collection-logs', views.ar_collection_logs),
    path('records/<int:pk>/collection-logs/<int:lid>', views.ar_collection_log_detail),

    # 统一动态 + 附件
    path('records/<int:pk>/activity', views.ar_activity_list),
    path('records/<int:pk>/activity/<int:aid>', views.ar_activity_detail),
    path('records/<int:pk>/attachments', views.ar_attachment_list),
    path('records/<int:pk>/attachments/<int:fid>', views.ar_attachment_detail),
    path('records/<int:pk>/attachments/<int:fid>/thumb', views.ar_attachment_thumb),
    path('records/<int:pk>/quick-edit', views.ar_record_quick_edit),
    path('records/<int:pk>/audit', views.ar_record_audit),
]
