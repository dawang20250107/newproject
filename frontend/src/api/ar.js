import api from './index.js'

const ar = {
  // Projects
  listProjects: p => api.get('/ar/projects', { params: p }),
  projectStats: p => api.get('/ar/projects/stats', { params: p }),
  createProject: d => api.post('/ar/projects', d),
  getProject: id => api.get(`/ar/projects/${id}`),
  updateProject: (id, d) => api.put(`/ar/projects/${id}`, d),
  deleteProject: id => api.delete(`/ar/projects/${id}`),
  bulkDeleteProjects: (body, params) => api.post('/ar/projects/bulk-delete', body, { params }),
  projectTemplate: () => api.get('/ar/projects/template', { responseType: 'blob' }),
  importProjects: fd => api.post('/ar/projects/import', fd),
  precheckProjects: fd => api.post('/ar/projects/import/precheck', fd),
  exportProjects: p => api.get('/ar/projects/export', { params: p, responseType: 'blob' }),

  // AR Records
  recordsDateBounds: () => api.get('/ar/records/date-bounds'),
  recordsDistinctValues: p => api.get('/ar/records/distinct-values', { params: p }),
  listRecords: p => api.get('/ar/records', { params: p }),
  recordsKpi: p => api.get('/ar/records/kpi', { params: p }),
  recordsSummary: p => api.get('/ar/records/summary', { params: p }),
  listPaymentLedger: p => api.get('/ar/records/payments', { params: p }),
  exportPaymentLedger: p => api.get('/ar/records/payments/export', { params: p, responseType: 'blob' }),
  collectionWorkbench: p => api.get('/ar/records/collection', { params: p }),
  createDunning: d => api.post('/ar/records/collection/dunning', d),
  // 筛选方案（私有/公共团队共享）
  listFilterSchemes: p => api.get('/ar/filter-schemes', { params: p }),
  createFilterScheme: d => api.post('/ar/filter-schemes', d),
  updateFilterScheme: (id, d) => api.put(`/ar/filter-schemes/${id}`, d),
  deleteFilterScheme: id => api.delete(`/ar/filter-schemes/${id}`),
  setDefaultFilterScheme: d => api.post('/ar/filter-schemes/set-default', d),
  createRecord: d => api.post('/ar/records', d),
  getRecord: id => api.get(`/ar/records/${id}`),
  updateRecord: (id, d) => api.put(`/ar/records/${id}`, d),
  deleteRecord: id => api.delete(`/ar/records/${id}`),
  // 批量删除：显式 ids，或 {all:true} + 当前筛选(conditions/match 走 params)
  bulkDeleteRecords: (body, params) => api.post('/ar/records/bulk-delete', body, { params }),
  // 合并开票批次
  listInvoiceBatches: p => api.get('/ar/records/invoice-batches', { params: p }),
  getInvoiceBatch: bn => api.get(`/ar/records/invoice-batches/${encodeURIComponent(bn)}`),
  batchInvoice: (bn, d) => api.post(`/ar/records/invoice-batches/${encodeURIComponent(bn)}/invoice`, d),
  batchInvoiceUndo: (bn, d) => api.post(`/ar/records/invoice-batches/${encodeURIComponent(bn)}/invoice-undo`, d),
  batchPayment: (bn, d) => api.post(`/ar/records/invoice-batches/${encodeURIComponent(bn)}/payment`, d),
  batchPaymentUndo: (bn, d) => api.post(`/ar/records/invoice-batches/${encodeURIComponent(bn)}/payment-undo`, d),
  batchAssignBatchNo: (d, params) => api.post('/ar/records/batch-assign', d, { params }),
  recordTemplate: () => api.get('/ar/records/template', { responseType: 'blob' }),
  importRecords: fd => api.post('/ar/records/import', fd),
  precheckRecords: fd => api.post('/ar/records/import/precheck', fd),
  exportRecords: p => api.get('/ar/records/export', { params: p, responseType: 'blob' }),
  dataHealth: p => api.get('/ar/records/health', { params: p }),
  recomputeRecords: ids => api.post('/ar/records/recompute', { ids }),

  // 催收跟进日志
  listCollectionLogs: id => api.get(`/ar/records/${id}/collection-logs`),
  addCollectionLog: (id, d) => api.post(`/ar/records/${id}/collection-logs`, d),
  updateCollectionLog: (rid, lid, d) => api.put(`/ar/records/${rid}/collection-logs/${lid}`, d),
  deleteCollectionLog: (rid, lid) => api.delete(`/ar/records/${rid}/collection-logs/${lid}`),

  // ── 应收动态 + 附件（催款工作台）─────────────────────────────────────────
  listActivity: (id, params) => api.get(`/ar/records/${id}/activity`, { params }),
  addActivity: (id, d) => api.post(`/ar/records/${id}/activity`, d),
  updateActivity: (id, aid, d) => api.put(`/ar/records/${id}/activity/${aid}`, d),
  deleteActivity: (id, aid) => api.delete(`/ar/records/${id}/activity/${aid}`),
  uploadAttachment: (id, formData) => api.post(`/ar/records/${id}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  deleteAttachment: (id, fid) => api.delete(`/ar/records/${id}/attachments/${fid}`),
  quickEdit: (id, d) => api.patch(`/ar/records/${id}/quick-edit`, d),
  recordAudit: id => api.get(`/ar/records/${id}/audit`),

  // 批量分配催收人
  bulkAssignCollector: (body, params) => api.post('/ar/records/bulk-assign-collector', body, { params }),

  // 账龄分桶配置
  getAgingConfig: () => api.get('/ar/aging-config'),
  updateAgingConfig: d => api.put('/ar/aging-config', d),

  // 差额调整明细（多次、各带原因与金额；合计为派生）
  listAdjustments: id => api.get(`/ar/records/${id}/adjustments`),
  addAdjustment: (id, d) => api.post(`/ar/records/${id}/adjustments`, d),
  deleteAdjustment: (rid, aid) => api.delete(`/ar/records/${rid}/adjustments/${aid}`),

  // Payments
  listPayments: id => api.get(`/ar/records/${id}/payments`),
  addPayment: (id, d) => api.post(`/ar/records/${id}/payments`, d),
  updatePayment: (rid, pid, d) => api.put(`/ar/records/${rid}/payments/${pid}`, d),
  deletePayment: (rid, pid) => api.delete(`/ar/records/${rid}/payments/${pid}`),

  // 客户 (customers)
  listCustomers: p => api.get('/ar/customers', { params: p }),
  createCustomer: d => api.post('/ar/customers', d),
  getCustomer: id => api.get(`/ar/customers/${id}`),
  updateCustomer: (id, d) => api.put(`/ar/customers/${id}`, d),
  deleteCustomer: id => api.delete(`/ar/customers/${id}`),
  bulkTagCustomerLevel: d => api.post('/ar/customers/bulk-tag-level', d),
  bulkDeleteCustomers: d => api.post('/ar/customers/bulk-delete', d),
  syncCustomersFromProjects: () => api.post('/ar/customers/sync-from-projects', {}),

  // 合同 (contracts)
  listContracts: p => api.get('/ar/contracts', { params: p }),
  createContract: d => api.post('/ar/contracts', d),
  getContract: id => api.get(`/ar/contracts/${id}`),
  updateContract: (id, d) => api.put(`/ar/contracts/${id}`, d),
  deleteContract: id => api.delete(`/ar/contracts/${id}`),

  // 草稿项目
  listDraftProjects: p => api.get('/ar/projects/drafts', { params: p }),
  promoteDraftProjects: (body) => api.post('/ar/projects/drafts/promote', body || {}),

  // 供应商池 (suppliers)
  listSuppliers: p => api.get('/ar/suppliers', { params: p }),
  searchSuppliers: p => api.get('/ar/suppliers/search', { params: p }),
  createSupplier: d => api.post('/ar/suppliers', d),
  getSupplierDetail: id => api.get(`/ar/suppliers/${id}`),
  updateSupplier: (id, d) => api.put(`/ar/suppliers/${id}`, d),
  deleteSupplier: id => api.delete(`/ar/suppliers/${id}`),

  // 预收预付 (advances)
  listAdvances: p => api.get('/ar/advances', { params: p }),
  advancesKpi: p => api.get('/ar/advances/kpi', { params: p }),
  advancesSummary: p => api.get('/ar/advances/summary', { params: p }),
  advancesAvailable: p => api.get('/ar/advances/available', { params: p }),
  // 预收核销工作台 + 批量核销（一笔预收按先进先出冲抵多条应收）
  offsetWorkbench: p => api.get('/ar/advances/offset-workbench', { params: p }),
  advanceDiffSummary: p => api.get('/ar/advances/diff-summary', { params: p }),
  batchWriteoff: (advId, d) => api.post(`/ar/advances/${advId}/batch-writeoff`, d),
  // 收付明细（一条预收/预付多次到账/付出；总额为派生）
  listAdvInstallments: id => api.get(`/ar/advances/${id}/installments`),
  addAdvInstallment: (id, d) => api.post(`/ar/advances/${id}/installments`, d),
  deleteAdvInstallment: (id, iid) => api.delete(`/ar/advances/${id}/installments/${iid}`),
  advanceOffsettable: p => api.get('/ar/advances/offsettable', { params: p }),
  createAdvance: d => api.post('/ar/advances', d),
  getAdvance: id => api.get(`/ar/advances/${id}`),
  updateAdvance: (id, d) => api.put(`/ar/advances/${id}`, d),
  deleteAdvance: id => api.delete(`/ar/advances/${id}`),
  advanceTemplate: () => api.get('/ar/advances/template', { responseType: 'blob' }),
  importAdvances: fd => api.post('/ar/advances/import', fd),
  precheckAdvances: fd => api.post('/ar/advances/import/precheck', fd),
  exportAdvances: p => api.get('/ar/advances/export', { params: p, responseType: 'blob' }),
  listWriteoffs: id => api.get(`/ar/advances/${id}/writeoffs`),
  addWriteoff: (id, d) => api.post(`/ar/advances/${id}/writeoffs`, d),
  updateWriteoff: (rid, wid, d) => api.put(`/ar/advances/${rid}/writeoffs/${wid}`, d),
  deleteWriteoff: (rid, wid) => api.delete(`/ar/advances/${rid}/writeoffs/${wid}`),

  // Analytics
  aging: p => api.get('/ar/analytics/aging', { params: p }),
  collectionRate: p => api.get('/ar/analytics/collection-rate', { params: p }),
  outstandingTop: p => api.get('/ar/analytics/outstanding-top', { params: p }),
  statusDist: p => api.get('/ar/analytics/status-dist', { params: p }),
  analyticsByPm: p => api.get('/ar/analytics/by-pm', { params: p }),
  analyticsByDept: p => api.get('/ar/analytics/by-dept', { params: p }),
  unitEconomics: p => api.get('/ar/analytics/unit-economics', { params: p }),
  businessFinance: p => api.get('/ar/analytics/business-finance', { params: p }),
  projectPnl: p => api.get('/ar/analytics/project-pnl', { params: p }),
  projectCashflow: p => api.get('/ar/analytics/project-cashflow', { params: p }),
  forecast: p => api.get('/ar/analytics/forecast', { params: p }),
  agingByCustomer: p => api.get('/ar/analytics/aging-by-customer', { params: p }),

  // P4 行动项
  listActions: p => api.get('/ar/actions', { params: p }),
  createAction: d => api.post('/ar/actions', d),
  updateAction: (id, d) => api.put(`/ar/actions/${id}`, d),
  deleteAction: id => api.delete(`/ar/actions/${id}`),
  actionFromSignal: d => api.post('/ar/actions/from-signal', d),

  // P4 目标分解
  targetDecomp: p => api.get('/ar/analytics/target-decomp', { params: p }),

  // Cashflow
  cashflow: p => api.get('/ar/cashflow', { params: p }),

  // 周期报表（周报 / 月报）
  periodicReport: p => api.get('/ar/periodic-report', { params: p }),
  exportPeriodicReport: p => api.get('/ar/periodic-report/export', { params: p, responseType: 'blob' }),

  // Budget
  listCollectionBudget: p => api.get('/ar/budget/collection', { params: p }),
  createCollectionBudget: d => api.post('/ar/budget/collection', d),
  updateCollectionBudget: (id, d) => api.put(`/ar/budget/collection/${id}`, d),
  deleteCollectionBudget: id => api.delete(`/ar/budget/collection/${id}`),
  collectionBudgetTemplate: () => api.get('/ar/budget/collection/template', { responseType: 'blob' }),
  importCollectionBudget: fd => api.post('/ar/budget/collection/import', fd),
  precheckCollectionBudget: fd => api.post('/ar/budget/collection/import/precheck', fd),
  exportCollectionBudget: p => api.get('/ar/budget/collection/export', { params: p, responseType: 'blob' }),
  listPaymentBudget: p => api.get('/ar/budget/payment', { params: p }),
  createPaymentBudget: d => api.post('/ar/budget/payment', d),
  updatePaymentBudget: (id, d) => api.put(`/ar/budget/payment/${id}`, d),
  deletePaymentBudget: id => api.delete(`/ar/budget/payment/${id}`),
  paymentBudgetTemplate: () => api.get('/ar/budget/payment/template', { responseType: 'blob' }),
  importPaymentBudget: fd => api.post('/ar/budget/payment/import', fd),
  precheckPaymentBudget: fd => api.post('/ar/budget/payment/import/precheck', fd),
  exportPaymentBudget: p => api.get('/ar/budget/payment/export', { params: p, responseType: 'blob' }),
  budgetSummary: p => api.get('/ar/budget/summary', { params: p }),
  budgetProjectCompare: p => api.get('/ar/budget/project-compare', { params: p }),

  // 资金池 (cash pool)
  cashPool: p => api.get('/ar/pool', { params: p }),
  poolConfigs: () => api.get('/ar/pool/config'),
  savePoolConfig: d => api.post('/ar/pool/config', d),
  listPoolTransfers: () => api.get('/ar/pool/transfers'),
  createPoolTransfer: d => api.post('/ar/pool/transfers', d),
  deletePoolTransfer: id => api.delete(`/ar/pool/transfers/${id}`),
  reviewPoolTransfer: (id, d) => api.post(`/ar/pool/transfers/${id}/review`, d),
}

export default ar
