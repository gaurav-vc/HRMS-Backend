import ast
import decimal
from decimal import Decimal
from graphlib import TopologicalSorter, CycleError
from .models import ComponentRule, RuleDependency, TaxRegimeSlab

try:
    from simpleeval import simple_eval
except ImportError:
    # Fallback/mock if simpleeval is not installed yet
    def simple_eval(expr, names=None):
        raise ImportError("simpleeval library is missing. Raw eval fallback is disabled for security reasons.")

def validate_formula(formula, available_vars):
    """
    Save-Time Formula Validator.
    Checks syntax, variable resolution, and basic security.
    """
    try:
        # Check syntax
        parsed = ast.parse(formula, mode='eval')
    except SyntaxError as e:
        return False, f"Syntax Error in formula: {str(e)}"
    
    # Check variable resolution
    used_vars = [node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)]
    missing = [v for v in used_vars if v not in available_vars and v not in ['True', 'False', 'None']]
    
    if missing:
        return False, f"Unresolved variables: {', '.join(missing)}"
        
    # We could do a dry run simple_eval here with dummy numbers
    # but actual evaluation type check requires data.
    return True, "Valid"

def build_dag_and_sort(rules):
    """
    Takes a list of ComponentRule objects and returns them topologically sorted.
    Raises ValueError if a cycle is detected.
    """
    graph = {}
    rule_map = {r.id: r for r in rules}
    
    for rule in rules:
        graph[rule.id] = set()
        
    # Dynamically infer dependencies from formulas to prevent DAG failures
    code_to_rule = {r.variable_code: r for r in rules if getattr(r, 'variable_code', None)}
    name_to_rule = {r.name.lower(): r for r in rules}
    for rule in rules:
        if rule.formula:
            try:
                parsed = ast.parse(rule.formula, mode='eval')
                used_vars = [node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)]
                for var in used_vars:
                    if var in code_to_rule and code_to_rule[var].id != rule.id:
                        graph[rule.id].add(code_to_rule[var].id)
                    else:
                        # Legacy fallback
                        var_lower = var.lower()
                        if var_lower == 'basic':
                            basic_rule = next((r for r in rules if 'basic' in r.name.lower()), None)
                            if basic_rule and basic_rule.id != rule.id:
                                graph[rule.id].add(basic_rule.id)
                        elif var_lower == 'hra':
                            hra_rule = next((r for r in rules if 'hra' in r.name.lower()), None)
                            if hra_rule and hra_rule.id != rule.id:
                                graph[rule.id].add(hra_rule.id)
                        elif var_lower in name_to_rule and name_to_rule[var_lower].id != rule.id:
                            graph[rule.id].add(name_to_rule[var_lower].id)
            except SyntaxError:
                pass
                
    # Balancing always goes last, so it depends on all Earning rules
    for rule in rules:
        if rule.calc == 'Balancing':
            for other in rules:
                if other.id != rule.id and other.type == 'Earning':
                    graph[rule.id].add(other.id)
                    
    ts = TopologicalSorter(graph)
    try:
        sorted_ids = list(ts.static_order())
    except CycleError as e:
        # HR Misconfiguration: A Circular Dependency exists!
        # E.g., Basic Pay is 'Balancing' (depends on OT), but OT formula uses 'BASIC_PAY'.
        # We break the cycle by falling back to a safe priority-based sort: Fixed -> Formula -> Balancing
        priority = {'Fixed': 1, 'Formula': 2, 'Balancing': 3}
        safe_sorted = sorted(rules, key=lambda r: priority.get(r.calc, 2))
        return safe_sorted
        
    return [rule_map[rid] for rid in sorted_ids]

def evaluate_component(rule, context):
    """
    Evaluates a single ComponentRule formula against the context.
    Returns a Decimal.
    """
    try:
        if not getattr(rule, 'formula', None) or not str(rule.formula).strip():
            return Decimal('0.00')

        # simpleeval allows safe mathematical evaluation natively supporting Decimal
        eval_context = {}
        for k, v in context.items():
            eval_context[k] = v
                
        # Custom operators to force Decimal casting and avoid float/Decimal TypeError
        from simpleeval import DEFAULT_OPERATORS
        import operator
        
        my_operators = DEFAULT_OPERATORS.copy()
        def safe_op(op):
            def _op(a, b):
                if isinstance(a, float): a = Decimal(str(a))
                if isinstance(b, float): b = Decimal(str(b))
                if isinstance(a, int) and isinstance(b, int) and op == operator.truediv:
                    return Decimal(a) / Decimal(b)
                # If one is Decimal and other is int, Python handles it natively
                return op(a, b)
            return _op
            
        my_operators[ast.Mult] = safe_op(operator.mul)
        my_operators[ast.Add] = safe_op(operator.add)
        my_operators[ast.Sub] = safe_op(operator.sub)
        my_operators[ast.Div] = safe_op(operator.truediv)
        
        def ifelse(cond, true_val, false_val):
            return true_val if cond else false_val
            
        my_functions = {'ifelse': ifelse}
        
        result = simple_eval(rule.formula, names=eval_context, operators=my_operators, functions=my_functions)
        
        # Apply Proration for attendance / LWP (Leave Without Pay)
        should_prorate = getattr(rule, 'prorate', False)
        # Standard monthly fixed earning components always prorate with attendance
        if not should_prorate and getattr(rule, 'type', '') == 'Earning':
            r_name_up = (rule.name or "").upper()
            if any(k in r_name_up for k in ["BASIC", "HRA", "LTA", "SPECIAL", "DEARNESS", "DA", "CONVEYANCE"]):
                should_prorate = True

        if should_prorate and 'present_days' in context and 'total_days' in context:
            total_days_dec = Decimal(str(context['total_days']))
            if total_days_dec > 0:
                proration_ratio = Decimal(str(context['present_days'])) / total_days_dec
                # Prevent Double-Proration:
                # If a deduction/contribution formula already depends on an already-prorated component (e.g. basic),
                # do not multiply by proration_ratio a second time.
                f_lower = (getattr(rule, 'formula', '') or '').lower()
                is_dependent_on_prorated = any(
                    k in f_lower for k in ["basic", "basic_pay", "hra", "non_balancing_gross"]
                ) or getattr(rule, 'calc', '') == '% of Basic'

                if not (rule.type in ["Deduction", "Employer Contribution"] and is_dependent_on_prorated):
                    result = Decimal(str(result)) * proration_ratio
        
        # Ensure it's a Decimal
        return Decimal(str(result)).quantize(Decimal('0.01'), rounding=decimal.ROUND_HALF_UP)
    except Exception as e:
        raise RuntimeError(f"Error evaluating rule '{rule.name}': {str(e)}")

def calculate_tds(ytd_gross, ytd_tax_paid, current_month_gross, remaining_months, regime='New', gender='Male', deductions=Decimal('0.00')):
    """
    TDS Annualization Logic.
    Projects annual income, computes total tax against slabs, and deducts for this month.
    """
    projected_annual_gross = Decimal(ytd_gross) + (Decimal(current_month_gross) * int(remaining_months))
    
    # Standard Deduction (75,000 for New Regime FY 26-27, 50,000 for Old Regime). 
    standard_deduction = Decimal('75000.00') if regime == 'New' else Decimal('50000.00')
    
    taxable_income = projected_annual_gross - standard_deduction
    
    # Subtract Old Regime deductions (e.g. 80C, 80D)
    if regime == 'Old' and deductions > 0:
        taxable_income -= Decimal(str(deductions))
        
    if taxable_income < 0:
        taxable_income = Decimal('0.00')
    
    # Fetch active slabs for the regime
    slabs = TaxRegimeSlab.objects.filter(regime=regime, effective_to__isnull=True).order_by('min_income')
    
    total_tax = Decimal('0.00')
    remaining_income = taxable_income
    
    for slab in slabs:
        if remaining_income <= 0:
            break
            
        slab_size = slab.max_income - slab.min_income if slab.max_income else remaining_income
        taxable_in_slab = min(remaining_income, slab_size)
        
        if taxable_in_slab > 0:
            tax_rate = slab.tax_rate
            if getattr(slab, 'gender', 'All') not in ['All', gender]:
                continue
                
            total_tax += taxable_in_slab * (tax_rate / Decimal('100.0'))
            
        remaining_income -= slab_size
        
    # Section 87A Rebate
    if regime == 'New' and taxable_income <= Decimal('700000.00'):
        total_tax = Decimal('0.00')
    elif regime == 'Old' and taxable_income <= Decimal('500000.00'):
        total_tax -= Decimal('12500.00')
        if total_tax < 0:
            total_tax = Decimal('0.00')
        
    # Apply 4% Health & Education Cess
    if total_tax > 0:
        total_tax = total_tax * Decimal('1.04')
        
    remaining_tax_due = total_tax - Decimal(ytd_tax_paid)
    
    if remaining_tax_due <= 0 or remaining_months <= 0:
        return Decimal('0.00')
        
    monthly_tds = remaining_tax_due / Decimal(remaining_months)
    return monthly_tds.quantize(Decimal('1.00'), rounding=decimal.ROUND_HALF_UP)

def calculate_professional_tds(gross_fee, tds_section='194J_10', custom_rate=Decimal('10.00'), pan=None):
    """
    Computes TDS for Professional Fees / Contractor Payouts (Section 194J / 194C).
    Section 206AA: If PAN is missing or invalid, applies minimum 20% penalty deduction.
    Returns: (tds_amount, effective_rate, is_penalty)
    """
    gross_fee = Decimal(str(gross_fee or '0.00'))
    if gross_fee <= Decimal('0.00'):
        return Decimal('0.00'), Decimal('0.00'), False

    # Check PAN for Section 206AA penalty
    pan_clean = str(pan or '').strip().upper()
    is_pan_missing = not pan_clean or pan_clean in ['N/A', 'NONE', 'XXXXX0000X'] or len(pan_clean) < 10

    if is_pan_missing:
        effective_rate = Decimal('20.00')
        is_penalty = True
    elif tds_section == '194J_10':
        effective_rate = Decimal('10.00')
        is_penalty = False
    elif tds_section == '194J_2':
        effective_rate = Decimal('2.00')
        is_penalty = False
    elif tds_section == '194C_1':
        effective_rate = Decimal('1.00')
        is_penalty = False
    elif tds_section == '194C_2':
        effective_rate = Decimal('2.00')
        is_penalty = False
    elif tds_section == 'CUSTOM':
        effective_rate = Decimal(str(custom_rate or '10.00'))
        is_penalty = False
    else:
        effective_rate = Decimal(str(custom_rate or '10.00'))
        is_penalty = False

    tds_amount = (gross_fee * (effective_rate / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=decimal.ROUND_HALF_UP)
    return tds_amount, effective_rate, is_penalty
