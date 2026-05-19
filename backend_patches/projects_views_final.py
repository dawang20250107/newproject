from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets
from .models import Project
from .serializers import ProjectSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    """项目管理 CRUD"""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        keyword = self.request.query_params.get('search', '')
        manager = self.request.query_params.get('manager_name', '')
        project_name = self.request.query_params.get('project_name', '')
        ordering = self.request.query_params.get('ordering', '').strip()

        if keyword:
            qs = qs.filter(
                project_name__icontains=keyword
            ) | qs.filter(
                project_code__icontains=keyword
            ) | qs.filter(
                customer_name__icontains=keyword
            )
        if manager:
            qs = qs.filter(manager_name=manager)
        if project_name:
            qs = qs.filter(project_name=project_name)

        if ordering:
            field_map = {
                'project_name': 'project_name', '-project_name': '-project_name',
                'manager_name': 'manager_name', '-manager_name': '-manager_name',
                'contract_amount': 'contract_amount', '-contract_amount': '-contract_amount',
                'created_at': 'created_at', '-created_at': '-created_at',
                'id': 'id', '-id': '-id',
            }
            order_field = field_map.get(ordering, '-created_at')
            qs = qs.order_by(order_field)
        else:
            qs = qs.order_by('-created_at')

        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        if not instance.project_code:
            import uuid
            code = 'PRJ' + uuid.uuid4().hex[:8].upper()
            Project.objects.filter(pk=instance.pk).update(project_code=code)

    def update(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop('status', None)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop('status', None)
        return super().partial_update(request, *args, **kwargs)


class ProjectSummaryView(APIView):
    """项目统计"""

    def get(self, request):
        month = request.query_params.get('month', '')
        qs = Project.objects.all()
        total_projects = qs.count()
        total_managers = qs.values('manager_name').distinct().count()
        new_this_month = 0
        if month:
            new_this_month = qs.filter(created_at__gte=f'{month}-01').count()
        return Response({
            'total_projects': total_projects,
            'total_managers': total_managers,
            'new_this_month': new_this_month,
        })


class UnpaidRecordsView(APIView):
    """未回款记录查询"""

    def get(self, request):
        project_name = request.query_params.get('project_name', '').strip()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 50))

        from django.db import connection
        where = ['1=1']
        params = []
        if project_name:
            where.append('project_name = %s')
            params.append(project_name)

        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM unpaid_records WHERE {' AND '.join(where)}", params)
            total = cur.fetchone()[0]

        offset = (page - 1) * page_size
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT id, project_id, project_name, manager_name, abnormal_amount, "
                f"received_amount, unpaid_amount, days_overdue, status, record_date, created_at "
                f"FROM unpaid_records WHERE {' AND '.join(where)} "
                f"ORDER BY days_overdue DESC LIMIT %s OFFSET %s",
                params + [page_size, offset]
            )
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                'id': r[0], 'project_id': r[1], 'project_name': r[2],
                'manager_name': r[3], 'abnormal_amount': float(r[4]) if r[4] else 0,
                'received_amount': float(r[5]) if r[5] else 0,
                'unpaid_amount': float(r[6]) if r[6] else 0,
                'days_overdue': r[7] or 0,
                'status': r[8] or 'normal',
                'record_date': r[9].isoformat() if r[9] else None,
                'created_at': r[10].isoformat() if r[10] else None,
            })

        return Response({'count': total, 'results': results})
