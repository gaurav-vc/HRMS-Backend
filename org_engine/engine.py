from django.db import transaction
from django.core.exceptions import ValidationError
from .models import OrganizationNode, OrganizationNodeType, OrganizationAuditLog

class HierarchyEngine:
    """
    Enterprise Hierarchy Engine responsible for recursive operations,
    cycle detection, and graph validation.
    """
    
    @staticmethod
    def _check_cycle(node, new_parent):
        """
        Validates that moving `node` under `new_parent` does not create a circular reference.
        """
        if not new_parent:
            return
            
        if node.id == new_parent.id:
            raise ValidationError("A node cannot be its own parent.")
            
        # If new_parent's path starts with node's path, new_parent is a descendant of node.
        # Moving node under its own descendant creates a cycle.
        if new_parent.path and node.path and new_parent.path.startswith(f"{node.path}."):
            raise ValidationError("Circular reference detected: Cannot move a node under its own descendant.")
            
    @staticmethod
    @transaction.atomic
    def move_node(node, new_parent, performed_by="System", effective_date=None):
        """
        Moves a node to a new parent, updating paths for it and all its descendants.
        Logs to HierarchyHistory.
        """
        from django.utils import timezone
        effective_date = effective_date or timezone.now()
        
        HierarchyEngine._check_cycle(node, new_parent)
        
        old_parent = node.parent
        old_path = node.path
        
        node.parent = new_parent
        node.save() # This generates the new path for the node
        
        new_path = node.path
        
        # Now update all descendants
        descendants = OrganizationNode.objects.filter(path__startswith=f"{old_path}.")
        
        for child in descendants:
            relative_path = child.path[len(old_path):]
            child.path = f"{new_path}{relative_path}"
            child.depth = child.path.count('.')
            child.save(update_fields=['path', 'depth'])
            
        # -----------------------------
        # Hierarchy History Management
        # -----------------------------
        from .models import HierarchyHistory
        
        # 1. Close the current open history record for the node
        current_hist = HierarchyHistory.objects.filter(node=node, effective_to__isnull=True).first()
        if current_hist:
            current_hist.effective_to = effective_date
            current_hist.save(update_fields=['effective_to'])
            
        # 2. Create the new history record
        HierarchyHistory.objects.create(
            node=node,
            parent_at_time=new_parent,
            path_at_time=new_path,
            effective_from=effective_date,
            reason=f"Moved by {performed_by}"
        )
        
        # Log the movement in Audit Log
        OrganizationAuditLog.objects.create(
            node=node,
            action="MOVE",
            old_parent=old_parent,
            new_parent=new_parent,
            performed_by_name=performed_by,
            before_state={'path': old_path, 'parent_id': old_parent.id if old_parent else None},
            after_state={'path': new_path, 'parent_id': new_parent.id if new_parent else None}
        )
        return node

    @staticmethod
    @transaction.atomic
    def clone_node(node, new_parent, performed_by="System"):
        """
        Recursively clones a node and all its descendants.
        """
        def _copy(src_node, dest_parent):
            new_node = OrganizationNode.objects.create(
                tenant_id=src_node.tenant_id,
                name=f"Copy of {src_node.name}",
                code=f"{src_node.code}_COPY" if src_node.code else None,
                node_type=src_node.node_type,
                parent=dest_parent,
                status=src_node.status
            )
            OrganizationAuditLog.objects.create(
                node=new_node,
                action="CLONE",
                new_parent=dest_parent,
                performed_by_name=performed_by
            )
            # Recursively copy children
            for child in OrganizationNode.objects.filter(parent=src_node):
                _copy(child, new_node)
            return new_node
            
        return _copy(node, new_parent)

    @staticmethod
    def get_reporting_chain(node):
        """
        Returns the straight-line reporting chain (ancestors) for a given node.
        """
        return node.get_ancestors()

    @staticmethod
    def analyze_impact(node, action="MOVE", new_parent=None):
        """
        Pre-commit Impact Analysis Engine.
        Returns a dictionary detailing the ripple effects of moving, archiving, or deleting a node.
        """
        descendants = node.get_descendants()
        total_affected = descendants.count()
        
        # Categorize affected nodes
        affected_employees = descendants.filter(node_type__name='Employee').count()
        affected_departments = descendants.filter(node_type__name='Department').count()
        
        impact_report = {
            'action': action,
            'target_node': node.name,
            'total_nodes_affected': total_affected,
            'employees_affected': affected_employees,
            'departments_affected': affected_departments,
            'will_break_workflows': False, # Placeholder for future workflow integration
            'cycle_detected': False
        }
        
        if action == "MOVE" and new_parent:
            try:
                HierarchyEngine._check_cycle(node, new_parent)
            except ValidationError:
                impact_report['cycle_detected'] = True
                
        return impact_report

    @staticmethod
    def resolve_approver(node, rule_type, target_node_type=None):
        """
        Dynamic Workflow Resolution Logic.
        Never relies on hardcoded manager IDs. Resolves approvers at runtime.
        
        rule_type options: 
        - 'NEAREST_PARENT': Immediate parent
        - 'NEAREST_TYPE': Walks up the tree until it finds `target_node_type` (e.g. 'HR', 'Project Head')
        - 'MATRIX': Checks NodeRelationship for a specific functional manager
        """
        if rule_type == 'NEAREST_PARENT':
            return node.parent
            
        if rule_type == 'NEAREST_TYPE' and target_node_type:
            # Materialized path makes this easy: fetch ancestors and reverse order to go up the tree
            ancestors = node.get_ancestors().order_by('-depth')
            for ancestor in ancestors:
                if ancestor.node_type.name.upper() == target_node_type.upper():
                    return ancestor
            return None
            
        if rule_type == 'MATRIX' and target_node_type:
            from .models import NodeRelationship
            rel = NodeRelationship.objects.filter(
                source_node=node, 
                relationship_type=target_node_type, 
                status='Active'
            ).first()
            return rel.target_node if rel else None
            
        return None

    @staticmethod
    @transaction.atomic
    def restore_node(node, performed_by="System"):
        """
        Enterprise Soft Restore capability.
        """
        # Restore this node and all descendants
        descendants = node.get_descendants(include_self=True)
        restored_count = descendants.update(status='Active')
        
        from .models import OrganizationAuditLog
        OrganizationAuditLog.objects.create(
            node=node,
            action="RESTORE",
            performed_by_name=performed_by,
            before_state={'status': 'Archived'},
            after_state={'status': 'Active'}
        )
        return restored_count
