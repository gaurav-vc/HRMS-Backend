from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from .models import OrganizationNodeType, OrganizationNode, OrganizationAuditLog
from .serializers import OrganizationNodeTypeSerializer, OrganizationNodeSerializer, OrganizationAuditLogSerializer
from .engine import HierarchyEngine

class OrganizationNodeTypeViewSet(viewsets.ModelViewSet):
    queryset = OrganizationNodeType.objects.all().order_by('level_order')
    serializer_class = OrganizationNodeTypeSerializer

class OrganizationNodeViewSet(viewsets.ModelViewSet):
    queryset = OrganizationNode.objects.all()
    serializer_class = OrganizationNodeSerializer

    def get_queryset(self):
        qs = OrganizationNode.objects.all()
        node_type = self.request.query_params.get('node_type')
        if node_type:
            qs = qs.filter(node_type__name__iexact=node_type)
        return qs

    def perform_create(self, serializer):
        node = serializer.save()
        OrganizationAuditLog.objects.create(
            node=node,
            action="CREATE",
            performed_by_name=self.request.user.username if self.request.user.is_authenticated else "System"
        )

    @action(detail=False, methods=['get'])
    def tree(self, request):
        tenant_id = request.query_params.get('tenant_id', 1)
        # Using Materialized path we can fetch ordered by path to easily construct
        nodes = list(OrganizationNode.objects.filter(tenant_id=tenant_id).select_related('node_type').order_by('path'))
        
        # Build tree in memory - O(N) extremely fast for <100k nodes
        node_map = {}
        for node in nodes:
            node_map[node.id] = {
                'id': node.id,
                'name': node.name,
                'node_type': node.node_type.name if node.node_type else None,
                'status': node.status,
                'parent_id': node.parent_id,
                'path': node.path,
                'depth': node.depth,
                'children': []
            }
        
        tree = []
        for node in nodes:
            if node.parent_id and node.parent_id in node_map:
                node_map[node.parent_id]['children'].append(node_map[node.id])
            elif not node.parent_id:
                tree.append(node_map[node.id])
                
        return Response(tree)

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        node = self.get_object()
        new_parent_id = request.data.get('new_parent_id')
        new_parent = OrganizationNode.objects.filter(id=new_parent_id).first() if new_parent_id else None
        
        try:
            HierarchyEngine.move_node(
                node, 
                new_parent, 
                performed_by=request.user.username if request.user.is_authenticated else "System"
            )
            return Response({'status': 'moved'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def clone(self, request, pk=None):
        node = self.get_object()
        new_parent_id = request.data.get('new_parent_id', node.parent_id)
        new_parent = OrganizationNode.objects.filter(id=new_parent_id).first() if new_parent_id else None
        
        try:
            cloned = HierarchyEngine.clone_node(
                node, 
                new_parent,
                performed_by=request.user.username if request.user.is_authenticated else "System"
            )
            return Response(OrganizationNodeSerializer(cloned).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        node = self.get_object()
        
        # Soft delete / Archive node and all descendants using Path query!
        descendants = node.get_descendants(include_self=True)
        
        updated_count = descendants.update(status='Archived')
        
        OrganizationAuditLog.objects.create(
            node=node,
            action="ARCHIVE",
            performed_by_name=request.user.username if request.user.is_authenticated else "System",
            before_state={'status': 'Active'},
            after_state={'status': 'Archived'}
        )
        
        return Response({'status': 'archived', 'nodes_affected': updated_count})

    @action(detail=True, methods=['get'])
    def impact_analysis(self, request, pk=None):
        node = self.get_object()
        action_type = request.query_params.get('action', 'MOVE')
        new_parent_id = request.query_params.get('new_parent_id')
        new_parent = OrganizationNode.objects.filter(id=new_parent_id).first() if new_parent_id else None
        
        report = HierarchyEngine.analyze_impact(node, action=action_type, new_parent=new_parent)
        return Response(report)

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        node = self.get_object()
        try:
            count = HierarchyEngine.restore_node(
                node, 
                performed_by=request.user.username if request.user.is_authenticated else "System"
            )
            return Response({'status': 'restored', 'nodes_restored': count})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def bulk_import(self, request):
        """
        Enterprise Bulk Operations with Preview & Rollback.
        Expected data format: List of dicts [{"name": "Sales", "node_type": "Department", "parent_code": "ORG1"}]
        """
        import json
        preview_mode = request.query_params.get('preview', 'true').lower() == 'true'
        data = request.data.get('nodes', [])
        
        results = {'success': 0, 'errors': [], 'preview_mode': preview_mode}
        
        # In a real implementation this parses CSV or Excel. We'll simulate receiving parsed JSON.
        for idx, row in enumerate(data):
            try:
                # Resolve Type
                node_type, _ = OrganizationNodeType.objects.get_or_create(name=row.get('node_type', 'Employee'))
                
                # Resolve Parent
                parent = None
                if row.get('parent_code'):
                    parent = OrganizationNode.objects.filter(code=row.get('parent_code')).first()
                    if not parent:
                        raise ValueError(f"Parent code {row.get('parent_code')} not found.")
                
                node = OrganizationNode(
                    name=row.get('name'),
                    code=row.get('code'),
                    node_type=node_type,
                    parent=parent
                )
                
                # Validate cycle BEFORE save
                if parent:
                    HierarchyEngine._check_cycle(node, parent)
                
                if not preview_mode:
                    node.save()
                    OrganizationAuditLog.objects.create(
                        node=node, action="BULK_IMPORT", performed_by_name=request.user.username if request.user.is_authenticated else "System"
                    )
                
                results['success'] += 1
            except Exception as e:
                results['errors'].append({'row': idx, 'error': str(e)})
        
        # If preview mode, or if errors occurred in strict mode, rollback transaction
        if preview_mode or (len(results['errors']) > 0 and request.query_params.get('strict', 'true').lower() == 'true'):
            transaction.set_rollback(True)
            if not preview_mode:
                results['status'] = "Rolled back due to errors."
                
        return Response(results)

class OrganizationAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OrganizationAuditLog.objects.all().order_by('-timestamp')
    serializer_class = OrganizationAuditLogSerializer
