from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connection


class PaymentRegistrationView(APIView):
    def get(self, request):
        keyword = request.GET.get('keyword', '').strip()
        filter_month = request.GET.get('month', '').strip()
        status_filter = request.GET.get('status', '').strip()
        manager_filter = request.GET.get('manager', '').strip()
        project_filter = request.GET.get('project_name', '').strip()
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))
        ordering = request.GET.get('ordering', '-apply_amount')

        # Validate ordering
        allowed_orders = ['-apply_amount', 'apply_amount', '-paid_amount', 'paid_amount',
                         '-pending_amount', 'pending_amount', '-created_at', 'created_at',
                         'applicant_name', '-applicant_name']
        if ordering not in allowed_orders:
            ordering = '-apply_amount'
        order_str = ordering.replace('-', '')

        where = ['1=1']
        params = []
        if keyword:
            where.append('(applicant_name LIKE %s OR project_name LIKE %s OR description LIKE %s)')
            kw = '%%%s%%' % keyword
            params.extend([kw, kw, kw])
        if filter_month:
            where.append('DATE_FORMAT(created_at, %%Y-%%m) = %s')
            params.append(filter_month)
        if status_filter:
            if status_filter == 'approved':
                where.append("source_sheet = '已审批未付'")
            elif status_filter == 'paid':
                where.append('(pay_date IS NOT NULL AND pay_date != "")')
            elif status_filter == 'pending':
                where.append("(source_sheet != '已审批未付' OR source_sheet IS NULL)")
        if manager_filter:
            where.append('payment_manager = %s')
            params.append(manager_filter)
        if project_filter:
            where.append('project_name = %s')
            params.append(project_filter)

        where_clause = ' AND '.join(where)

        # Count
        count_sql = 'SELECT COUNT(*) FROM payment_registrations WHERE ' + where_clause
        with connection.cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        # Fix: select dingtalk_no (钉钉编号=invoice_no field) - keep invoice_no as is
        sel = ('id, applicant_name, invoice_no, description, project_name, planned_date, '
               'apply_amount, paid_amount, pending_amount, pay_date, is_paid, payment_manager, '
               'has_invoice, expense_summary, source_sheet, created_at')
        sql = (f'SELECT {sel} FROM payment_registrations '
               f'WHERE {where_clause} ORDER BY {order_str} {"" if ordering.startswith("-") else "ASC"} '
               f'LIMIT %s OFFSET %s')
        with connection.cursor() as cur:
            cur.execute(sql, params + [page_size, offset])
            rows = cur.fetchall()

        items = []
        for r in rows:
            items.append({
                'id': r[0], 'applicant_name': r[1], 'invoice_no': r[2], 'description': r[3],
                'project_name': r[4], 'planned_date': r[5].isoformat() if r[5] else None,
                'apply_amount': float(r[6]) if r[6] else 0,
                'paid_amount': float(r[7]) if r[7] else 0,
                'pending_amount': float(r[8]) if r[8] else 0,
                'pay_date': r[9].isoformat() if r[9] else None,
                'is_paid': bool(r[10]),
                'payment_manager': r[11], 'has_invoice': bool(r[12]),
                'expense_summary': float(r[13]) if r[13] else None,
                'source_sheet': r[14], 'created_at': r[15].isoformat() if r[15] else None,
            })

        return Response({
            'count': total, 'page': page, 'page_size': page_size,
            'results': items
        })


class PaymentRegistrationSummaryView(APIView):
    def get(self, request):
        with connection.cursor() as cur:
            # Fix: 已审批 = source_sheet = '已审批未付' (不是invoice_no)
            cur.execute("""
                SELECT
                    COUNT(*) as total_count,
                    SUM(CASE WHEN source_sheet = '已审批未付' THEN 1 ELSE 0 END) as approved_count,
                    SUM(CASE WHEN pay_date IS NOT NULL AND pay_date != '' THEN 1 ELSE 0 END) as paid_count,
                    COALESCE(SUM(apply_amount), 0) as total_apply,
                    COALESCE(SUM(paid_amount), 0) as total_paid,
                    COALESCE(SUM(pending_amount), 0) as total_pending,
                    COALESCE(SUM(CASE WHEN source_sheet = '已审批未付' THEN apply_amount ELSE 0 END), 0) as approved_apply,
                    COALESCE(SUM(CASE WHEN source_sheet = '已审批未付' THEN paid_amount ELSE 0 END), 0) as approved_paid,
                    COALESCE(SUM(CASE WHEN source_sheet = '已审批未付' THEN pending_amount ELSE 0 END), 0) as approved_pending,
                    COUNT(DISTINCT project_name) as project_count,
                    COUNT(DISTINCT payment_manager) as manager_count
                FROM payment_registrations
            """)
            row = cur.fetchone()

            # by_project
            cur.execute("""
                SELECT project_name,
                       COUNT(*) as count,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                WHERE source_sheet = '已审批未付'
                GROUP BY project_name
                ORDER BY total_apply DESC
                LIMIT 20
            """)
            by_project = []
            for r in cur.fetchall():
                by_project.append({
                    'project_name': r[0], 'count': r[1],
                    'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])
                })

            # by_manager
            cur.execute("""
                SELECT payment_manager,
                       COUNT(*) as count,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                WHERE source_sheet = '已审批未付' AND payment_manager IS NOT NULL AND payment_manager != ''
                GROUP BY payment_manager
                ORDER BY total_apply DESC
            """)
            by_manager = []
            for r in cur.fetchall():
                by_manager.append({
                    'payment_manager': r[0] or '(未分配)', 'count': r[1],
                    'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])
                })

            # by_month (from created_at)
            cur.execute("""
                SELECT DATE_FORMAT(created_at, '%%Y-%%m') as month,
                       COUNT(*) as count,
                       COALESCE(SUM(apply_amount), 0) as total_apply,
                       COALESCE(SUM(paid_amount), 0) as total_paid,
                       COALESCE(SUM(pending_amount), 0) as total_pending
                FROM payment_registrations
                GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
                ORDER BY month DESC
                LIMIT 12
            """)
            by_month = []
            for r in cur.fetchall():
                by_month.append({
                    'month': r[0], 'count': r[1],
                    'total_apply': float(r[2]), 'total_paid': float(r[3]), 'total_pending': float(r[4])
                })

        return Response({
            'summary': {
                'total_count': row[0] or 0,
                'approved_count': row[1] or 0,
                'paid_count': row[2] or 0,
                'total_apply': float(row[3]),
                'total_paid': float(row[4]),
                'total_pending': float(row[5]),
                'approved_apply': float(row[6]),
                'approved_paid': float(row[7]),
                'approved_pending': float(row[8]),
                'project_count': row[9] or 0,
                'manager_count': row[10] or 0,
            },
            'by_project': by_project,
            'by_manager': by_manager,
            'by_month': by_month,
        })
