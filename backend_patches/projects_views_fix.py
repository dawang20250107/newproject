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
        # 聚合维度过滤
        business_model = self.request.query_params.get('business_model', '')
        department = self.request.query_params.get('department', '')
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
        if business_model:
            qs = qs.filter(business_model__icontains=business_model)
        if department:
            qs = qs.filter(department__icontains=department)

        # 支持排序的字段
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
    """项目统计 - 项目总数、项目经理数、按月新增"""

    def get(self, request):
        from django.db.models import Count
        month = request.query_params.get('month', '')  # e.g. 2026-04

        qs = Project.objects.all()
        total_projects = qs.count()
        total_managers = qs.values('manager_name').distinct().count()

        # 本月新增
        new_this_month = 0
        if month:
            new_this_month = qs.filter(created_at__gte=f'{month}-01').count()

        return Response({
            'total_projects': total_projects,
            'total_managers': total_managers,
            'new_this_month': new_this_month,
        })
