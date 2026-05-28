import api from './index.js'

const ar = {
  // Projects
  listProjects: p => api.get('/ar/projects', { params: p }),
  projectStats: p => api.get('/ar/projects/stats', { params: p }),
  createProject: d => api.post('/ar/projects', d),
  getProject: id => api.get(`/ar/projects/${id}`),
  updateProject: (id, d) => api.put(`/ar/projects/${id}`, d),
  deleteProject: id => api.delete(`/ar/projects/${id}`),
  projectTemplate: () => api.get('/ar/projects/template', { responseType: 'blob' }),
  importProjects: fd => api.post('/ar/projects/import', fd),
  exportProjects: p => api.get('/ar/projects/export', { params: p, responseType: 'blob' }),

  // AR Records
  listRecords: p => api.get('/ar/records', { params: p }),
  recordsKpi: p => api.get('/ar/records/kpi', { params: p }),
  createRecord: d => api.post('/ar/records', d),
  getRecord: id => api.get(`/ar/records/${id}`),
  updateRecord: (id, d) => api.put(`/ar/records/${id}`, d),
  deleteRecord: id => api.delete(`/ar/records/${id}`),
  recordTemplate: () => api.get('/ar/records/template', { responseType: 'blob' }),
  importRecords: fd => api.post('/ar/records/import', fd),
  exportRecords: p => api.get('/ar/records/export', { params: p, responseType: 'blob' }),

  // Payments
  listPayments: id => api.get(`/ar/records/${id}/payments`),
  addPayment: (id, d) => api.post(`/ar/records/${id}/payments`, d),
  updatePayment: (rid, pid, d) => api.put(`/ar/records/${rid}/payments/${pid}`, d),
  deletePayment: (rid, pid) => api.delete(`/ar/records/${rid}/payments/${pid}`),

  // Analytics
  aging: p => api.get('/ar/analytics/aging', { params: p }),
  collectionRate: p => api.get('/ar/analytics/collection-rate', { params: p }),
  outstandingTop: p => api.get('/ar/analytics/outstanding-top', { params: p }),
  statusDist: p => api.get('/ar/analytics/status-dist', { params: p }),
  analyticsByPm: p => api.get('/ar/analytics/by-pm', { params: p }),

  // Cashflow
  cashflow: p => api.get('/ar/cashflow', { params: p }),

  // Budget
  listCollectionBudget: p => api.get('/ar/budget/collection', { params: p }),
  createCollectionBudget: d => api.post('/ar/budget/collection', d),
  updateCollectionBudget: (id, d) => api.put(`/ar/budget/collection/${id}`, d),
  deleteCollectionBudget: id => api.delete(`/ar/budget/collection/${id}`),
  collectionBudgetTemplate: () => api.get('/ar/budget/collection/template', { responseType: 'blob' }),
  importCollectionBudget: fd => api.post('/ar/budget/collection/import', fd),
  exportCollectionBudget: p => api.get('/ar/budget/collection/export', { params: p, responseType: 'blob' }),
  listPaymentBudget: p => api.get('/ar/budget/payment', { params: p }),
  createPaymentBudget: d => api.post('/ar/budget/payment', d),
  updatePaymentBudget: (id, d) => api.put(`/ar/budget/payment/${id}`, d),
  deletePaymentBudget: id => api.delete(`/ar/budget/payment/${id}`),
  paymentBudgetTemplate: () => api.get('/ar/budget/payment/template', { responseType: 'blob' }),
  importPaymentBudget: fd => api.post('/ar/budget/payment/import', fd),
  exportPaymentBudget: p => api.get('/ar/budget/payment/export', { params: p, responseType: 'blob' }),
  budgetSummary: p => api.get('/ar/budget/summary', { params: p }),
}

export default ar
