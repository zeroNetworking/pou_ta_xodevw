"""
PDF Report Generator — services/pdf_report.py

Generates a professional monthly financial report with full Greek support.
Uses DejaVu Sans TTF (pre-installed on most Linux distros) for proper
rendering of accented Greek characters (ά, έ, ή, ί, ό, ύ, ώ).

If DejaVu is not found, falls back to Noto Sans or FreeSans.

Contents:
  - Header with month name and generation date
  - Summary stats (income, expenses, balance)
  - Expense breakdown by category (horizontal bar chart)
  - Fixed expenses payment status
  - Full transaction list
  - Footer with page numbers
"""

import io
import os
import glob
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import HorizontalBarChart


# ══════════════════════════════════════════════════════════════════
# Greek-capable Font Registration
# ══════════════════════════════════════════════════════════════════

# Search paths for TTF fonts on common Linux distros
_FONT_SEARCH_PATHS = [
    # Arch / Manjaro
    '/usr/share/fonts/TTF/',
    '/usr/share/fonts/truetype/',
    '/usr/share/fonts/noto/',
    '/usr/share/fonts/dejavu/',
    # Debian / Ubuntu
    '/usr/share/fonts/truetype/dejavu/',
    '/usr/share/fonts/truetype/noto/',
    '/usr/share/fonts/truetype/freefont/',
    # Fedora / RHEL
    '/usr/share/fonts/dejavu-sans-fonts/',
    '/usr/share/fonts/google-noto-sans-fonts/',
    # Generic
    '/usr/share/fonts/',
    '/usr/local/share/fonts/',
    os.path.expanduser('~/.local/share/fonts/'),
    os.path.expanduser('~/.fonts/'),
]

# Font families to try, in preference order
_FONT_CANDIDATES = [
    # (regular, bold, name_prefix)
    ('DejaVuSans.ttf',        'DejaVuSans-Bold.ttf',        'DejaVu'),
    ('NotoSans-Regular.ttf',  'NotoSans-Bold.ttf',          'Noto'),
    ('FreeSans.ttf',          'FreeSansBold.ttf',           'Free'),
]

FONT_REG  = 'Greek'       # registered name for regular weight
FONT_BOLD = 'Greek-Bold'  # registered name for bold weight
_font_registered = False


def _find_font(filename: str) -> str:
    """Searches common font directories for a TTF file. Returns path or ''."""
    for base in _FONT_SEARCH_PATHS:
        full = os.path.join(base, filename)
        if os.path.isfile(full):
            return full
        # Also search subdirectories one level deep
        for match in glob.glob(os.path.join(base, '*', filename)):
            if os.path.isfile(match):
                return match
    return ''


def _register_greek_fonts():
    """Registers the first available Greek-capable TTF font pair."""
    global _font_registered
    if _font_registered:
        return

    for reg_file, bold_file, label in _FONT_CANDIDATES:
        reg_path  = _find_font(reg_file)
        bold_path = _find_font(bold_file)
        if reg_path:
            pdfmetrics.registerFont(TTFont(FONT_REG, reg_path))
            if bold_path:
                pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path))
            else:
                # Fall back to regular for bold if bold variant not found
                pdfmetrics.registerFont(TTFont(FONT_BOLD, reg_path))
            _font_registered = True
            return

    # Last resort: use Helvetica (will show ■ for accented Greek)
    # This shouldn't happen on any modern Linux with fonts installed


def _fn(bold=False) -> str:
    """Returns the font name to use (Greek-capable or fallback)."""
    _register_greek_fonts()
    if _font_registered:
        return FONT_BOLD if bold else FONT_REG
    return 'Helvetica-Bold' if bold else 'Helvetica'


# ══════════════════════════════════════════════════════════════════
# Brand Colors
# ══════════════════════════════════════════════════════════════════

COLOR_PRIMARY   = colors.HexColor('#141414')
COLOR_INCOME    = colors.HexColor('#1a6b3c')
COLOR_EXPENSE   = colors.HexColor('#8b1a1a')
COLOR_POSITIVE  = colors.HexColor('#1a6b3c')
COLOR_NEGATIVE  = colors.HexColor('#c0392b')
COLOR_MUTED     = colors.HexColor('#999999')
COLOR_BORDER    = colors.HexColor('#e8e8e8')
COLOR_BG        = colors.HexColor('#f7f7f7')
COLOR_SURFACE   = colors.white

PALETTE_13 = [
    '#E74C3C', '#27AE60', '#F39C12', '#E67E22', '#9B59B6',
    '#F06292', '#E91E63', '#1ABC9C', '#3498DB', '#8D6E63',
    '#1A5276', '#2ECC71', '#95A5A6',
]

CAT_ORDER = [
    'Σπίτι & Λογαριασμοί', 'Σούπερ Μάρκετ', 'Φαγητό & Καφέδες Έξω',
    'Μετακινήσεις & Όχημα', 'Διασκέδαση & Ταξίδια', 'Αγορές & Προσωπική Φροντίδα',
    'Υγεία & Φαρμακείο', 'Εκπαίδευση & Πανεπιστήμιο', 'Συνδρομές & Gym',
    'Κατοικίδια', 'Τραπεζικά & Revolut', 'Αποταμίευση & Επενδύσεις', 'Διάφορα / Έκτακτα',
]


def _cat_color(name: str) -> colors.HexColor:
    """Returns the chart color for a category name."""
    try:
        idx = CAT_ORDER.index(name)
        return colors.HexColor(PALETTE_13[idx % 13])
    except ValueError:
        h = 0
        for c in name:
            h = ord(c) + ((h << 5) - h)
        return colors.HexColor(PALETTE_13[abs(h) % 13])


# ══════════════════════════════════════════════════════════════════
# Paragraph Styles (all using Greek font)
# ══════════════════════════════════════════════════════════════════

def _styles():
    """Returns a dict of ParagraphStyles using the registered Greek-capable font."""
    return {
        'title': ParagraphStyle(
            'ReportTitle',
            fontSize=22, fontName=_fn(bold=True),
            textColor=COLOR_PRIMARY, spaceAfter=4, leading=28,
        ),
        'subtitle': ParagraphStyle(
            'ReportSubtitle',
            fontSize=10, fontName=_fn(),
            textColor=COLOR_MUTED, spaceAfter=0,
        ),
        'section': ParagraphStyle(
            'SectionHeading',
            fontSize=11, fontName=_fn(bold=True),
            textColor=COLOR_PRIMARY, spaceBefore=14, spaceAfter=6,
        ),
        'normal': ParagraphStyle(
            'Normal2',
            fontSize=9, fontName=_fn(),
            textColor=COLOR_PRIMARY, leading=13,
        ),
        'normal_bold': ParagraphStyle(
            'NormalBold',
            fontSize=9, fontName=_fn(bold=True),
            textColor=COLOR_PRIMARY, leading=13,
        ),
        'small': ParagraphStyle(
            'Small',
            fontSize=8, fontName=_fn(),
            textColor=COLOR_MUTED, leading=11,
        ),
        'mono': ParagraphStyle(
            'Mono',
            fontSize=8.5, fontName=_fn(),
            textColor=COLOR_PRIMARY,
        ),
        'income_val': ParagraphStyle(
            'IncomeVal',
            fontSize=9, fontName=_fn(bold=True),
            textColor=COLOR_INCOME, alignment=TA_RIGHT,
        ),
        'expense_val': ParagraphStyle(
            'ExpenseVal',
            fontSize=9, fontName=_fn(bold=True),
            textColor=COLOR_EXPENSE, alignment=TA_RIGHT,
        ),
        'right': ParagraphStyle(
            'Right',
            fontSize=9, fontName=_fn(),
            textColor=COLOR_PRIMARY, alignment=TA_RIGHT,
        ),
    }


# ══════════════════════════════════════════════════════════════════
# Report Sections
# ══════════════════════════════════════════════════════════════════

def _stat_cards_table(stats: dict) -> Table:
    """Renders 3 summary boxes: income / expenses / balance."""
    balance   = stats['balance']
    bal_color = COLOR_POSITIVE if balance >= 0 else COLOR_NEGATIVE
    bal_sign  = '+' if balance >= 0 else ''

    def card(label, value, val_color):
        return [
            Paragraph(label, ParagraphStyle(
                'CL', fontSize=8, fontName=_fn(),
                textColor=COLOR_MUTED, alignment=TA_CENTER,
            )),
            Paragraph(value, ParagraphStyle(
                'CV', fontSize=14, fontName=_fn(bold=True),
                textColor=val_color, alignment=TA_CENTER, spaceBefore=2,
            )),
        ]

    data = [[
        card('ΣΥΝΟΛΟ ΕΣΟΔΩΝ',  f"+{stats['total_income']:.2f} €",  COLOR_INCOME),
        card('ΣΥΝΟΛΟ ΕΞΟΔΩΝ',  f"-{stats['total_expense']:.2f} €", COLOR_EXPENSE),
        card('ΥΠΟΛΟΙΠΟ',       f"{bal_sign}{balance:.2f} €",       bal_color),
    ]]

    col_w = (A4[0] - 4 * cm) / 3
    t = Table(data, colWidths=[col_w, col_w, col_w])
    t.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, -1), COLOR_BG),
        ('BOX',          (0, 0), (0, 0),   0.5, COLOR_BORDER),
        ('BOX',          (1, 0), (1, 0),   0.5, COLOR_BORDER),
        ('BOX',          (2, 0), (2, 0),   0.5, COLOR_BORDER),
        ('TOPPADDING',   (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 10),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _category_chart(expense_by_cat: list, page_width: float) -> Drawing:
    """Horizontal bar chart of expense amounts per category."""
    if not expense_by_cat:
        return None

    cats       = expense_by_cat[:10]
    labels     = [row['category'] for row in cats]
    values     = [row['total']    for row in cats]
    bar_colors = [_cat_color(l) for l in labels]

    n      = len(cats)
    height = max(n * 22 + 50, 100)
    width  = page_width - 4 * cm

    drawing = Drawing(width, height)
    chart   = HorizontalBarChart()

    chart.x      = 160
    chart.y      = 20
    chart.width  = width - 180
    chart.height = height - 40
    chart.data   = [values]
    chart.reversePlotOrder = 1

    chart.bars[0].fillColor = colors.HexColor('#E74C3C')
    for i, col in enumerate(bar_colors):
        chart.bars[(0, i)].fillColor = col

    chart.valueAxis.valueMin        = 0
    chart.valueAxis.valueMax        = max(values) * 1.1 if values else 1
    chart.valueAxis.labelTextFormat = '%.0f'
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.labels.fillColor = COLOR_MUTED
    chart.valueAxis.labels.fontName  = _fn()

    chart.categoryAxis.categoryNames   = labels
    chart.categoryAxis.labels.fontSize  = 8
    chart.categoryAxis.labels.fillColor = COLOR_PRIMARY
    chart.categoryAxis.labels.fontName  = _fn()
    chart.categoryAxis.labels.dx        = -5
    chart.categoryAxis.labels.textAnchor = 'end'

    drawing.add(chart)
    return drawing


def _category_table(expense_by_cat: list, stats: dict, styles: dict) -> Table:
    """Category totals table with percentages."""
    header = [
        Paragraph('Κατηγορία', styles['small']),
        Paragraph('Σύνολο', ParagraphStyle(
            'SR2', fontSize=8, fontName=_fn(), textColor=COLOR_MUTED, alignment=TA_RIGHT)),
        Paragraph('%', ParagraphStyle(
            'SC2', fontSize=8, fontName=_fn(), textColor=COLOR_MUTED, alignment=TA_RIGHT)),
    ]
    rows = [header]
    total_exp = stats['total_expense'] or 1

    for row in expense_by_cat:
        pct = (row['total'] / total_exp) * 100
        rows.append([
            Paragraph(row['category'], styles['normal']),
            Paragraph(f"{row['total']:.2f}", ParagraphStyle(
                'ER', fontSize=9, fontName=_fn(bold=True),
                textColor=COLOR_EXPENSE, alignment=TA_RIGHT)),
            Paragraph(f"{pct:.1f}%", ParagraphStyle(
                'PR', fontSize=8.5, fontName=_fn(),
                textColor=COLOR_MUTED, alignment=TA_RIGHT)),
        ])

    t = Table(rows, colWidths=[9 * cm, 3 * cm, 2 * cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  COLOR_BG),
        ('LINEBELOW',     (0, 0), (-1, 0),  0.8, COLOR_PRIMARY),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [COLOR_SURFACE, colors.HexColor('#fafafa')]),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _transactions_table(transactions: list, styles: dict) -> Table:
    """Full transaction list as a styled table."""
    header = [
        Paragraph('Ημερομηνία', styles['small']),
        Paragraph('Κατηγορία / Υποκατηγορία', styles['small']),
        Paragraph('Περιγραφή', styles['small']),
        Paragraph('Ποσό', ParagraphStyle(
            'SHR', fontSize=8, fontName=_fn(),
            textColor=COLOR_MUTED, alignment=TA_RIGHT,
        )),
    ]
    rows = [header]

    for t in transactions:
        is_income = t['type'] == 'income'
        val_color = COLOR_INCOME if is_income else COLOR_EXPENSE
        sign      = '+' if is_income else '-'

        cat_text = t['category']
        if t.get('subcategory'):
            cat_text += f" / {t['subcategory']}"
        if t.get('late_entry'):
            cat_text += ' [Καθυστερημένη]'

        rows.append([
            Paragraph(str(t['transaction_date']), styles['mono']),
            Paragraph(cat_text, styles['normal']),
            Paragraph(t.get('description') or '—', styles['small']),
            Paragraph(
                f"{sign}{t['amount']:.2f}",
                ParagraphStyle(
                    'AR', fontSize=9, fontName=_fn(bold=True),
                    textColor=val_color, alignment=TA_RIGHT,
                )
            ),
        ])

    col_widths = [2.4 * cm, 6.5 * cm, 5.5 * cm, 2.2 * cm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  COLOR_BG),
        ('LINEBELOW',     (0, 0), (-1, 0),  0.8, COLOR_PRIMARY),
        ('TOPPADDING',    (0, 0), (-1, 0),  5),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  5),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [COLOR_SURFACE, colors.HexColor('#fafafa')]),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return tbl


def _fixed_expenses_table(fixed_expenses: list, fixed_payment_status: dict,
                           styles: dict) -> Table:
    """Fixed expenses payment status table."""
    header = [
        Paragraph('Σταθερό Έξοδο', styles['small']),
        Paragraph('Κατηγορία',      styles['small']),
        Paragraph('Ποσό', ParagraphStyle(
            'SR', fontSize=8, fontName=_fn(),
            textColor=COLOR_MUTED, alignment=TA_RIGHT)),
        Paragraph('Κατάσταση', ParagraphStyle(
            'SC', fontSize=8, fontName=_fn(),
            textColor=COLOR_MUTED, alignment=TA_CENTER)),
    ]
    rows = [header]

    for fe in fixed_expenses:
        status = fixed_payment_status.get(fe['id'], {})
        paid   = status.get('paid', False)

        status_text  = 'Πληρώθηκε' if paid else 'Εκκρεμεί'
        status_color = COLOR_INCOME if paid else COLOR_EXPENSE

        rows.append([
            Paragraph(fe['label'], styles['normal']),
            Paragraph(fe.get('category') or '—', styles['small']),
            Paragraph(f"{fe['amount']:.2f}" if fe.get('amount') else '—',
                      ParagraphStyle('FAR', fontSize=9, fontName=_fn(),
                                     textColor=COLOR_PRIMARY, alignment=TA_RIGHT)),
            Paragraph(status_text,
                      ParagraphStyle('FAC', fontSize=8.5, fontName=_fn(bold=True),
                                     textColor=status_color, alignment=TA_CENTER)),
        ])

    col_widths = [5.5 * cm, 4.5 * cm, 2.2 * cm, 4.4 * cm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  COLOR_BG),
        ('LINEBELOW',     (0, 0), (-1, 0),  0.8, COLOR_PRIMARY),
        ('TOPPADDING',    (0, 0), (-1, 0),  5),
        ('BOTTOMPADDING', (0, 0), (-1, 0),  5),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [COLOR_SURFACE, colors.HexColor('#fafafa')]),
        ('LINEBELOW',     (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


# ══════════════════════════════════════════════════════════════════
# Main PDF Generator
# ══════════════════════════════════════════════════════════════════

def generate_month_pdf(month: dict, transactions: list, stats: dict,
                        expense_by_cat: list, fixed_expenses: list,
                        fixed_payment_status: dict) -> bytes:
    """
    Generates the complete monthly PDF report with full Greek support.
    Returns the PDF as bytes (ready to send as a Flask Response).
    """
    buffer = io.BytesIO()
    page_w, page_h = A4

    # Ensure fonts are registered before anything else
    _register_greek_fonts()

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_fn(), 7)
        canvas.setFillColor(COLOR_MUTED)
        canvas.drawString(
            2 * cm, 1.2 * cm,
            f"Που τα ξοδεύω — {month['name']} — Εξαγωγή: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        canvas.drawRightString(
            page_w - 2 * cm, 1.2 * cm,
            f"Σελίδα {doc.page}"
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Που τα ξοδεύω — {month['name']}",
        author='Που τα ξοδεύω',
    )

    s     = _styles()
    story = []

    # ── Header ────────────────────────────────────────────────
    story.append(Paragraph('Που τα ξοδεύω', s['subtitle']))
    story.append(Paragraph(month['name'], s['title']))
    status_txt = 'Κλειστός μήνας' if month['is_closed'] else 'Ενεργός μήνας'
    story.append(Paragraph(status_txt, s['subtitle']))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width='100%', thickness=1, color=COLOR_BORDER))
    story.append(Spacer(1, 0.4 * cm))

    # ── Summary Stats ──────────────────────────────────────────
    story.append(Paragraph('Συνοπτικά Αποτελέσματα', s['section']))
    story.append(_stat_cards_table(stats))
    story.append(Spacer(1, 0.3 * cm))

    if stats.get('top_expense_category'):
        story.append(Paragraph(
            f"Κορυφαία κατηγορία εξόδων: <b>{stats['top_expense_category']}</b> "
            f"— {stats['top_expense_amount']:.2f} €",
            s['small']
        ))
    story.append(Spacer(1, 0.3 * cm))

    # ── Category Chart + Table ────────────────────────────────
    if expense_by_cat:
        story.append(HRFlowable(width='100%', thickness=0.4, color=COLOR_BORDER))
        story.append(Paragraph('Έξοδα ανά Κατηγορία', s['section']))

        chart = _category_chart(expense_by_cat, page_w)
        if chart:
            story.append(chart)
            story.append(Spacer(1, 0.2 * cm))

        story.append(_category_table(expense_by_cat, stats, s))

    # ── Fixed Expenses ────────────────────────────────────────
    if fixed_expenses:
        story.append(Spacer(1, 0.3 * cm))
        story.append(HRFlowable(width='100%', thickness=0.4, color=COLOR_BORDER))
        story.append(Paragraph('Σταθερά Μηνιαία Έξοδα', s['section']))
        story.append(_fixed_expenses_table(fixed_expenses, fixed_payment_status, s))

    # ── Transaction List ──────────────────────────────────────
    if transactions:
        story.append(Spacer(1, 0.3 * cm))
        story.append(HRFlowable(width='100%', thickness=0.4, color=COLOR_BORDER))
        story.append(Paragraph(
            f'Αναλυτικές Κινήσεις ({len(transactions)} εγγραφές)',
            s['section']
        ))
        story.append(_transactions_table(transactions, s))
    else:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph('Δεν υπάρχουν κινήσεις για αυτόν τον μήνα.', s['small']))

    # Build PDF
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.read()
