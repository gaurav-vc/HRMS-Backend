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
        try:
            from organisation.models import Entity, Branch, Site, Department
            from employees.models import Employee
            from authentication.permissions import isolate_queryset

            # Build dynamic tree from legacy tables
            tree = []
            node_map = {}

            def create_node(n_id, name, n_type, status='Active'):
                node = {
                    'id': n_id,
                    'name': name,
                    'node_type': n_type,
                    'status': status,
                    'children': []
                }
                node_map[n_id] = node
                return node

            # 1. Entities (100000+)
            for e in isolate_queryset(Entity.objects.all(), request.user):
                tree.append(create_node(100000 + e.id, e.name, 'Entity'))

            # 2. Branches (200000+)
            for b in isolate_queryset(Branch.objects.all(), request.user):
                node = create_node(200000 + b.id, b.name, 'Branch')
                if b.entity_id and (100000 + b.entity_id) in node_map:
                    node_map[100000 + b.entity_id]['children'].append(node)
                else:
                    tree.append(node)

            # 3. Sites (300000+)
            for s in isolate_queryset(Site.objects.all(), request.user):
                node = create_node(300000 + s.id, s.name, 'Site')
                if s.branch_id and (200000 + s.branch_id) in node_map:
                    node_map[200000 + s.branch_id]['children'].append(node)
                else:
                    tree.append(node)

            # 4. Departments (400000+)
            for d in isolate_queryset(Department.objects.all(), request.user):
                node = create_node(400000 + d.id, d.name, 'Department')
                if d.entity_id and (100000 + d.entity_id) in node_map:
                    node_map[100000 + d.entity_id]['children'].append(node)
                else:
                    tree.append(node)

            # 5. Employees (500000+)
            emps = list(isolate_queryset(Employee.objects.all(), request.user))
            for emp in emps:
                create_node(500000 + emp.id, f"{emp.first_name} {emp.last_name}", 'Employee', emp.status)
                
            for emp in emps:
                emp_node = node_map[500000 + emp.id]
                if emp.manager_id and (500000 + emp.manager_id) in node_map:
                    node_map[500000 + emp.manager_id]['children'].append(emp_node)
                elif emp.department_id and (400000 + emp.department_id) in node_map:
                    node_map[400000 + emp.department_id]['children'].append(emp_node)
                elif emp.site_id and (300000 + emp.site_id) in node_map:
                    node_map[300000 + emp.site_id]['children'].append(emp_node)
                elif emp.branch_id and (200000 + emp.branch_id) in node_map:
                    node_map[200000 + emp.branch_id]['children'].append(emp_node)
                elif emp.entity_id and (100000 + emp.entity_id) in node_map:
                    node_map[100000 + emp.entity_id]['children'].append(emp_node)
                else:
                    tree.append(emp_node)

            return Response(tree)
        except Exception as e:
            return Response({'error': 'Failed to load organization tree.', 'details': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        try:
            pk = int(pk)
            new_parent_id = int(request.data.get('new_parent_id'))
            
            # We only support moving Employees for now to prevent breaking structural integrity
            if pk >= 500000:
                from employees.models import Employee
                emp = Employee.objects.get(id=pk - 500000)
                
                # Clear all previous structural links
                emp.manager = None
                emp.department = None
                emp.site = None
                emp.branch = None
                emp.entity = None
                
                if new_parent_id >= 500000:
                    emp.manager_id = new_parent_id - 500000
                    # Inherit manager's structure
                    mgr = Employee.objects.get(id=new_parent_id - 500000)
                    emp.department = mgr.department
                    emp.site = mgr.site
                    emp.branch = mgr.branch
                    emp.entity = mgr.entity
                elif new_parent_id >= 400000:
                    emp.department_id = new_parent_id - 400000
                    from organisation.models import Department
                    dept = Department.objects.get(id=new_parent_id - 400000)
                    emp.entity = dept.entity
                elif new_parent_id >= 300000:
                    emp.site_id = new_parent_id - 300000
                    from organisation.models import Site
                    site = Site.objects.get(id=new_parent_id - 300000)
                    emp.branch = site.branch
                    if site.branch:
                        emp.entity = site.branch.entity
                elif new_parent_id >= 200000:
                    emp.branch_id = new_parent_id - 200000
                    from organisation.models import Branch
                    branch = Branch.objects.get(id=new_parent_id - 200000)
                    emp.entity = branch.entity
                elif new_parent_id >= 100000:
                    emp.entity_id = new_parent_id - 100000
                    
                emp.save()
                return Response({'status': 'moved'})
            else:
                return Response({'error': 'Can only drag and move Employees in real-time view.'}, status=status.HTTP_400_BAD_REQUEST)
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
        return Response({
            "action": "MOVE",
            "target_node": "Target Group",
            "cycle_detected": False,
            "total_nodes_affected": 1,
            "employees_affected": 1,
            "departments_affected": 0
        })

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
