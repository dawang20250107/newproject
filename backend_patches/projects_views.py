from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
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
        if keyword:
            qs = qs.filter(project_name__icontains=keyword) | qs.filter(project_code__icontains=keyword) | qs.filter(customer_name__icontains=keyword)
        if manager:
            qs = qs.filter(manager_name=manager)
        if project_name:
            qs = qs.filter(project_name=project_name)
        return qs

    def perform_create(self, serializer):
        # project_code auto-generate if not provided
        instance = serializer.save()
        if not instance.project_code:
            import uuid
            code = 'PRJ' + uuid.uuid4().hex[:8].upper()
            Project.objects.filter(pk=instance.pk).update(project_code=code)

    def update(self, request, *args, **kwargs):
        # Prevent updating read-only fields that don't exist in the model
        data = request.data.copy()
        data.pop('status', None)  # status field doesn't exist in projects table
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        data = request.data.copy()
        data.pop('status', None)
        return super().partial_update(request, *args, **kwargs)
