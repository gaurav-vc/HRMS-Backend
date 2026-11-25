import os
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
)
from reportlab.pdfgen import canvas

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_charts")
os.makedirs(TEMP_DIR, exist_ok=True)
CHART1_PATH = os.path.join(TEMP_DIR, "salary_structure_to_tax.png")
CHART2_PATH = os.path.join(TEMP_DIR, "tax_calculation_flow.png")

# -------------------------------------------------------------
# 1. GENERATE CLEAN, SIMPLE VISUAL DIAGRAMS (NO UNICODE TOFU)
# -------------------------------------------------------------
def generate_salary_structure_chart():
    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 35)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')

    # Box 1: CTC
    b1 = patches.FancyBboxPatch((2, 6), 20, 22, boxstyle="round,pad=0.5,rounding_size=1.5",
                                facecolor='#EFF6FF', edgecolor='#2563EB', linewidth=1.5)
    ax.add_patch(b1)
    ax.text(12, 23.5, "Annual CTC", fontsize=11, fontweight='bold', color='#1E3A8A', ha='center')
    ax.text(12, 14, "Cost to Company\n= Gross Salary\n+ Employer PF (12%)\n+ Employer ESIC\n+ Gratuity",
            fontsize=8.5, color='#1E293B', ha='center')

    # Arrow 1
    ax.annotate("", xy=(26, 17), xytext=(22, 17),
                arrowprops=dict(facecolor='#2563EB', edgecolor='#2563EB', width=1.5, headwidth=6))

    # Box 2: Monthly Gross
    b2 = patches.FancyBboxPatch((26, 6), 22, 22, boxstyle="round,pad=0.5,rounding_size=1.5",
                                facecolor='#F0FDF4', edgecolor='#16A34A', linewidth=1.5)
    ax.add_patch(b2)
    ax.text(37, 23.5, "Monthly Gross", fontsize=11, fontweight='bold', color='#14532D', ha='center')
    ax.text(37, 14, "Earnings Components:\n• Basic Pay (40-50%)\n• HRA (50% of Basic)\n• Special Allowance\n• Statutory Bonus",
            fontsize=8.5, color='#1E293B', ha='center')

    # Arrow 2
    ax.annotate("", xy=(52, 17), xytext=(48, 17),
                arrowprops=dict(facecolor='#16A34A', edgecolor='#16A34A', width=1.5, headwidth=6))

    # Box 3: Monthly Deductions
    b3 = patches.FancyBboxPatch((52, 6), 22, 22, boxstyle="round,pad=0.5,rounding_size=1.5",
                                facecolor='#FEF2F2', edgecolor='#DC2626', linewidth=1.5)
    ax.add_patch(b3)
    ax.text(63, 23.5, "Monthly Deductions", fontsize=11, fontweight='bold', color='#991B1B', ha='center')
    ax.text(63, 14, "Statutory Cuts:\n• Employee PF (12%)\n• Professional Tax (PT)\n• Monthly TDS (Tax)\n• Loan / Advance Recov.",
            fontsize=8.5, color='#1E293B', ha='center')

    # Arrow 3
    ax.annotate("", xy=(78, 17), xytext=(74, 17),
                arrowprops=dict(facecolor='#DC2626', edgecolor='#DC2626', width=1.5, headwidth=6))

    # Box 4: Net In-Hand
    b4 = patches.FancyBboxPatch((78, 6), 20, 22, boxstyle="round,pad=0.5,rounding_size=1.5",
                                facecolor='#FAF5FF', edgecolor='#9333EA', linewidth=1.5)
    ax.add_patch(b4)
    ax.text(88, 23.5, "Net In-Hand Pay", fontsize=11, fontweight='bold', color='#581C87', ha='center')
    ax.text(88, 14, "Credited to Bank\n\n= Monthly Gross\n- Total Deductions\n(Take-Home Pay)",
            fontsize=8.5, color='#1E293B', ha='center')

    plt.tight_layout()
    plt.savefig(CHART1_PATH, dpi=300, bbox_inches='tight')
    plt.close()

def generate_tax_flow_chart():
    fig, ax = plt.subplots(figsize=(10, 2.8), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 30)
    ax.axis('off')
    fig.patch.set_facecolor('#FFFFFF')

    steps = [
        ("Step 1: Total Gross", "Prev Employer Gross\n+ Our Annual Salary\n+ Other Incomes", '#0284C7'),
        ("Step 2: Deductions", "Less: Std Deduction (Rs. 75k)\nLess: Exemptions u/s 10\n= Net Taxable Income", '#4F46E5'),
        ("Step 3: Annual Tax", "Apply Regime Slabs\nLess: Sec 87A Rebate\nAdd: 4% Health & Ed Cess", '#D97706'),
        ("Step 4: Monthly TDS", "Less: Prev Employer TDS\nLess: Current YTD TDS\nDivide by Remaining Mos", '#059669'),
    ]

    for i, (title, desc, col) in enumerate(steps):
        x = 2 + i * 25
        b = patches.FancyBboxPatch((x, 3), 21, 23, boxstyle="round,pad=0.5,rounding_size=1.5",
                                   facecolor='#F8FAFC', edgecolor=col, linewidth=1.5)
        ax.add_patch(b)
        h = patches.FancyBboxPatch((x, 19), 21, 7, boxstyle="round,pad=0.0,rounding_size=1.2",
                                   facecolor=col, edgecolor=col)
        ax.add_patch(h)
        ax.text(x + 10.5, 22.5, title, fontsize=9.5, fontweight='bold', color='#FFFFFF', ha='center')
        ax.text(x + 10.5, 11, desc, fontsize=8, color='#1E293B', ha='center')

        if i < 3:
            ax.annotate("", xy=(x + 24.5, 14.5), xytext=(x + 21.5, 14.5),
                        arrowprops=dict(facecolor='#64748B', edgecolor='#64748B', width=1.5, headwidth=5))

    plt.tight_layout()
    plt.savefig(CHART2_PATH, dpi=300, bbox_inches='tight')
    plt.close()

# -------------------------------------------------------------
# 2. NUMBERED CANVAS FOR CLEAN HEADER / FOOTER
# -------------------------------------------------------------
class SimpleNumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        if self._pageNumber > 1:
            self.drawString(54, 755, "INCOME TAX, SALARY STRUCTURE & TDS CALCULATION — MANAGEMENT BLUEPRINT")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.75)
            self.line(54, 747, 558, 747)

        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(54, 45, 558, 45)

        self.setFont("Helvetica", 8)
        self.drawString(54, 32, "Enterprise HRMS — Plain-Language Engineering & Financial Design")
        self.drawRightString(558, 32, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()

# -------------------------------------------------------------
# 3. BUILD THE STREAMLINED EXECUTIVE PDF
# -------------------------------------------------------------
def build_simple_pdf(filename):
    generate_salary_structure_chart()
    generate_tax_flow_chart()

    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom Clean Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#0284C7'),
        spaceAfter=12
    )
    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=10,
        spaceAfter=4
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12.5,
        textColor=colors.HexColor('#334155'),
        spaceAfter=5
    )
    formula_callout = ParagraphStyle(
        'FormulaCallout',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#0F172A')
    )
    table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#1E293B')
    )
    table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#FFFFFF')
    )

    story = []

    # Title
    story.append(Paragraph("Income Tax, Salary Structure & TDS Calculation", title_style))
    story.append(Paragraph("Simple Management Guide: How Salary Structure, Form 12B & Other Income Flow into Monthly TDS", subtitle_style))

    # SECTION 1: SALARY STRUCTURE EXPLAINED SIMPLY
    story.append(Paragraph("1. Understanding Salary Structure (The Foundation)", h1_style))
    story.append(Paragraph(
        "Before computing income tax, we must first understand how an employee's salary is built. "
        "A salary structure bridges the gap between total annual cost (<b>CTC</b>), monthly gross earnings, and net take-home pay:",
        body_style
    ))
    story.append(Image(CHART1_PATH, width=504, height=161))
    story.append(Spacer(1, 4))

    # Formula Box 1: Salary Structure
    sal_box = [
        [
            Paragraph("<b>Core Salary Structure Formulas:</b><br/>"
                      "• <b>Monthly Gross Salary</b> = Basic Pay + HRA + Special Allowance + Statutory Bonus<br/>"
                      "• <b>Annual CTC (Cost to Company)</b> = (Monthly Gross x 12) + Employer PF (12% of Basic) + Employer ESIC + Gratuity<br/>"
                      "• <b>Net In-Hand (Take-Home Pay)</b> = Monthly Gross - Employee PF (12%) - Professional Tax (PT) - <b>Monthly TDS (Tax)</b>",
                      formula_callout)
        ]
    ]
    t_sal = Table(sal_box, colWidths=[504])
    t_sal.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#2563EB')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_sal)
    story.append(Spacer(1, 10))

    # SECTION 2: THE 4-STEP TAX COMPUTATION PIPELINE
    story.append(Paragraph("2. The 4-Step Tax & Monthly TDS Calculation Flow", h1_style))
    story.append(Paragraph(
        "Here is the exact step-by-step logic the system executes to deduct the correct monthly tax (TDS) without year-end salary shock:",
        body_style
    ))
    story.append(Image(CHART2_PATH, width=504, height=141))
    story.append(Spacer(1, 4))

    # 4 Formulas Table
    formulas_data = [
        [
            Paragraph("Step", table_header),
            Paragraph("What It Does", table_header),
            Paragraph("Clear Mathematical Formula", table_header)
        ],
        [
            Paragraph("<b>Step 1</b><br/>Annual Gross", table_cell),
            Paragraph("Combines previous employer salary (Form 12B) with current salary and other income.", table_cell),
            Paragraph("<code>Total Gross = Prev_Salary + (Current_Monthly_Gross x Remaining_Months) + Other_Income</code>", table_cell)
        ],
        [
            Paragraph("<b>Step 2</b><br/>Taxable Income", table_cell),
            Paragraph("Subtracts standard statutory deduction and eligible tax deductions.", table_cell),
            Paragraph("<code>Net Taxable Income = Total Gross - Std_Deduction (Rs. 75,000) - Sec_80C_80D</code>", table_cell)
        ],
        [
            Paragraph("<b>Step 3</b><br/>Annual Tax", table_cell),
            Paragraph("Applies tax slab rates, deducts Sec 87A rebate, and adds 4% Health & Ed Cess.", table_cell),
            Paragraph("<code>Total Tax = (Slab_Tax - Sec_87A_Rebate) x 1.04 (Cess)</code>", table_cell)
        ],
        [
            Paragraph("<b>Step 4</b><br/>Monthly TDS", table_cell),
            Paragraph("Subtracts tax already paid and divides by remaining months in financial year.", table_cell),
            Paragraph("<b><code>Monthly TDS = (Total Tax - Prev_TDS - Current_YTD_TDS) / Remaining_Months</code></b>", table_cell)
        ]
    ]
    t_form = Table(formulas_data, colWidths=[70, 160, 274])
    t_form.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0284C7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')]),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t_form)
    story.append(Spacer(1, 10))

    # SECTION 3: REAL-WORLD NUMERICAL EXAMPLE
    story.append(Paragraph("3. Real-World Worked Example (Mid-Year Joiner with Rs. 12L CTC)", h1_style))
    story.append(Paragraph(
        "<b>Scenario:</b> An employee joins your company in <b>August 2026</b> with Rs. 12,00,000 CTC (Monthly Gross = Rs. 95,000). "
        "They worked at Company A from April to July (4 months), earned Rs. 3,80,000, and paid Rs. 15,000 TDS (captured via Form 12B). "
        "Here is how their monthly TDS is calculated under the <b>New Tax Regime</b>:",
        body_style
    ))

    example_data = [
        [
            Paragraph("Calculation Line Item", table_header),
            Paragraph("Amount (Rs.)", table_header),
            Paragraph("Plain-English Explanation", table_header)
        ],
        [
            Paragraph("1. Previous Employer Salary (Apr - Jul)", table_cell),
            Paragraph("Rs. 3,80,000", table_cell),
            Paragraph("Captured from previous employer's Form 12B / Form 16 Part B.", table_cell)
        ],
        [
            Paragraph("2. Current Employer Salary (Aug - Mar)", table_cell),
            Paragraph("Rs. 7,60,000", table_cell),
            Paragraph("8 months remaining x Rs. 95,000 monthly gross salary.", table_cell)
        ],
        [
            Paragraph("3. Other Income Declared (Savings/FD Interest)", table_cell),
            Paragraph("Rs. 20,000", table_cell),
            Paragraph("Bank interest declared by employee under Section 192(2B).", table_cell)
        ],
        [
            Paragraph("<b>4. Total Annual Gross Income</b>", table_cell),
            Paragraph("<b>Rs. 11,60,000</b>", table_cell),
            Paragraph("Sum of (1) + (2) + (3).", table_cell)
        ],
        [
            Paragraph("5. Less: Standard Deduction", table_cell),
            Paragraph("- Rs. 75,000", table_cell),
            Paragraph("Statutory standard deduction under New Tax Regime (Finance Act 2024).", table_cell)
        ],
        [
            Paragraph("<b>6. Net Taxable Income</b>", table_cell),
            Paragraph("<b>Rs. 10,85,000</b>", table_cell),
            Paragraph("Income on which slab tax is computed.", table_cell)
        ],
        [
            Paragraph("7. Slab Tax Computation:<br/>"
                      "• Rs. 0 to 3.0L: Nil<br/>"
                      "• Rs. 3.0L to 7.0L (Rs. 4.0L @ 5%): Rs. 20,000<br/>"
                      "• Rs. 7.0L to 10.0L (Rs. 3.0L @ 10%): Rs. 30,000<br/>"
                      "• Rs. 10.0L to 10.85L (Rs. 85k @ 15%): Rs. 12,750", table_cell),
            Paragraph("<br/><br/>Rs. 62,750", table_cell),
            Paragraph("Base income tax before cess.", table_cell)
        ],
        [
            Paragraph("8. Add: 4% Health & Education Cess", table_cell),
            Paragraph("+ Rs. 2,510", table_cell),
            Paragraph("4% statutory cess on base tax (Rs. 62,750 x 0.04).", table_cell)
        ],
        [
            Paragraph("<b>9. Total Annual Tax Liability</b>", table_cell),
            Paragraph("<b>Rs. 65,260</b>", table_cell),
            Paragraph("Total tax payable for the full financial year.", table_cell)
        ],
        [
            Paragraph("10. Less: TDS Paid at Previous Employer", table_cell),
            Paragraph("- Rs. 15,000", table_cell),
            Paragraph("Credit for tax already deducted by previous employer (Form 12B).", table_cell)
        ],
        [
            Paragraph("<b>11. Net Tax Remaining to Deduct</b>", table_cell),
            Paragraph("<b>Rs. 50,260</b>", table_cell),
            Paragraph("Total tax that our company must deduct over remaining months.", table_cell)
        ],
        [
            Paragraph("<b>12. Monthly TDS Deduction (Aug to Mar)</b>", table_cell),
            Paragraph("<b>Rs. 6,283 / mo</b>", table_cell),
            Paragraph("<b>Rs. 50,260 / 8 remaining months</b> = Exact, predictable monthly cut!", table_cell)
        ]
    ]
    t_ex = Table(example_data, colWidths=[180, 84, 240])
    t_ex.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')]),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BACKGROUND', (0,12), (-1,12), colors.HexColor('#DCFCE7')),  # Highlight final row
    ]))
    story.append(t_ex)
    story.append(Spacer(1, 10))

    # SECTION 4: HOW MODULES 10, 11 & 12 DELIVER THIS
    story.append(Paragraph("4. How Modules 10, 11 & 12 Deliver This in the System", h1_style))

    mod_summary = [
        [
            Paragraph("Module", table_header),
            Paragraph("How It Solves the Problem in Simple Words", table_header),
            Paragraph("Business Benefit to Company & Employees", table_header)
        ],
        [
            Paragraph("<b>Module 10: Previous Employer Income</b><br/><i>(Form 12B)</i>", table_cell),
            Paragraph("When a new employee joins mid-year, they upload their previous Form 16 / payslip and enter previous earnings & tax paid. HR verifies it with 1 click.", table_cell),
            Paragraph("<b>No Year-End Tax Shock:</b> Prevents deducting 50% of the employee's salary in March because earlier income wasn't tracked.", table_cell)
        ],
        [
            Paragraph("<b>Module 11: Other Income Declaration</b><br/><i>(Sec 192(2B))</i>", table_cell),
            Paragraph("Employees declare home loan interest (loss), savings interest, or FD interest with proof documents. HR approves it.", table_cell),
            Paragraph("<b>Accurate Tax Slabs:</b> Ensures employees receive their full legal deductions and tax benefits directly in their monthly payslip.", table_cell)
        ],
        [
            Paragraph("<b>Module 12: Tax Deduction Calculation</b><br/><i>(Engine & Simulator)</i>", table_cell),
            Paragraph("The payroll engine computes annual tax against slabs and divides it cleanly by remaining months. Includes a self-service tax calculator.", table_cell),
            Paragraph("<b>Zero Tax Inquiries:</b> Employees see an itemized tax breakdown on their portal, eliminating 90% of routine questions to HR.", table_cell)
        ]
    ]
    t_mod = Table(mod_summary, colWidths=[130, 194, 180])
    t_mod.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0F172A')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FFFFFF'), colors.HexColor('#F8FAFC')]),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_mod)
    story.append(Spacer(1, 12))

    # Sign-off box
    signoff_data = [
        [
            Paragraph("<b>Prepared By:</b><br/>Senior Software Engineering Team", table_cell),
            Paragraph("<b>Reviewed & Verified By:</b><br/>HR & Payroll Operations Head", table_cell),
            Paragraph("<b>Approved For Execution:</b><br/>Managing Director / CEO", table_cell)
        ]
    ]
    signoff_table = Table(signoff_data, colWidths=[168, 168, 168])
    signoff_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#94A3B8')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(signoff_table)

    doc.build(story, canvasmaker=SimpleNumberedCanvas)
    print(f"Simplified PDF generated successfully at: {filename}")

if __name__ == '__main__':
    target_path = r"C:\Hrms\Income_Tax_and_Investment_Plan_Executive_Presentation.pdf"
    build_simple_pdf(target_path)
    
    artifact_dir = r"C:\Users\kashs_p0smtrx\.gemini\antigravity\brain\74020b07-1ce0-416c-ab3c-869acc61af7f"
    if os.path.exists(artifact_dir):
        artifact_target = os.path.join(artifact_dir, "Income_Tax_and_Investment_Plan.pdf")
        shutil.copyfile(target_path, artifact_target)
        print(f"Copied to artifact dir: {artifact_target}")
