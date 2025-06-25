from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, send_file
)
import sqlite3
import os
from flask_wtf.csrf import CSRFError
from io import BytesIO
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib import colors
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm
from wtforms import SubmitField

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your_default_secret_key')
csrf = CSRFProtect(app)

# CSRF error handler
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('The form is invalid or expired. Please try again.', 'danger')
    return redirect(url_for('login'))

@app.context_processor
def inject_csrf_token():
    from flask_wtf.csrf import generate_csrf
    return dict(csrf_token=lambda: f'<input type="hidden" name="csrf_token" value="{generate_csrf()}">')

class LogoutForm(FlaskForm):
    submit = SubmitField('Logout')

def get_db_connection():
    db_path = os.path.join('data', 'database.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def draw_table(p, approvals, y_start):
    row_height = 20
    headers = ["Department", "Approval", "Date"]
    col_positions = [50, 300, 450]
    table_left = col_positions[0]
    table_right = col_positions[-1] + 100
    data_rows = max(len(approvals), 6)
    total_rows = data_rows + 1
    padded_approvals = list(approvals) + [{'faculty_id': None, 'cleared': None, 'approval_date': None}] * (data_rows - len(approvals))

    for i in range(total_rows + 1):
        y_line = y_start - i * row_height
        p.line(table_left, y_line, table_right, y_line)

    for x in col_positions + [table_right]:
        p.line(x, y_start, x, y_start - total_rows * row_height)

    p.setFont("Helvetica-Bold", 12)
    for i, header in enumerate(headers):
        p.drawString(col_positions[i] + 5, y_start - 15, header)

    p.setFont("Helvetica", 12)
    for idx, approval in enumerate(padded_approvals):
        y_row = y_start - ((idx + 1) * row_height) - 15
        # faculty_id might be None if padded row; try to get department name
        role = approval.get('role') or ""
        if not role and approval.get('faculty_id'):
            # You can fetch faculty role from DB if needed, or leave blank
            role = ""
        status = "Approved" if approval['cleared'] else "Not Approved" if approval['cleared'] is False else "-"
        date_str = "-"
        if approval['approval_date']:
            try:
                date_obj = datetime.strptime(approval['approval_date'], '%Y-%m-%d')
                date_str = date_obj.strftime('%d %b %Y')
            except Exception:
                date_str = str(approval['approval_date'])
        p.drawString(col_positions[0] + 5, y_row, role)
        p.drawString(col_positions[1] + 5, y_row, status)
        p.drawString(col_positions[2] + 5, y_row, date_str)

    return y_start - (total_rows * row_height)

def get_summary_counts(faculty_id):
    conn = get_db_connection()
    try:
        total_students = conn.execute('SELECT COUNT(*) FROM student').fetchone()[0] or 0
        cleared_students = conn.execute(
            'SELECT COUNT(DISTINCT student_id) FROM student_clearance WHERE faculty_id = ? AND cleared = 1',
            (faculty_id,)
        ).fetchone()[0] or 0
        pending_students = total_students - cleared_students
        return {
            'total': total_students,
            'cleared': cleared_students,
            'pending': pending_students,
            'cleared_percent': (cleared_students * 100 / total_students) if total_students > 0 else 0,
            'pending_percent': (pending_students * 100 / total_students) if total_students > 0 else 0
        }
    finally:
        conn.close()

def check_and_update_clearance_status(student_id):
    conn = get_db_connection()
    faculties = conn.execute('SELECT id FROM faculty').fetchall()
    clearance_map = {c['faculty_id']: c for c in conn.execute(
        'SELECT faculty_id, cleared, due_amount FROM student_clearance WHERE student_id = ?', (student_id,)
    ).fetchall()}

    all_cleared = True
    total_due = 0
    for faculty in faculties:
        fid = faculty['id']
        clearance = clearance_map.get(fid)
        if clearance:
            due = clearance['due_amount'] or 0
            total_due += due
            if due == 0 and clearance['cleared'] != 1:
                conn.execute('UPDATE student_clearance SET cleared = 1, approval_date = ? WHERE student_id = ? AND faculty_id = ?',
                             (datetime.now().strftime('%Y-%m-%d'), student_id, fid))
            elif due > 0 and clearance['cleared'] == 1:
                conn.execute('UPDATE student_clearance SET cleared = 0, approval_date = NULL WHERE student_id = ? AND faculty_id = ?',
                             (student_id, fid))
            if due > 0:
                all_cleared = False
        else:
            conn.execute('INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount) VALUES (?, ?, 1, 0)',
                         (student_id, fid))
    conn.commit()
    conn.close()
    return all_cleared and total_due == 0

password_reset_tokens = {}

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        faculty = conn.execute('SELECT * FROM faculty WHERE username = ?', (username,)).fetchone()
        student = conn.execute('SELECT * FROM student WHERE roll_number = ?', (username,)).fetchone()
        conn.close()

        if faculty and check_password_hash(faculty['password'], password):
            session.update({'role': 'faculty', 'username': faculty['username'], 'faculty_id': faculty['id'], 'department': faculty['role']})
            flash('Login successful.', 'success')
            return redirect(url_for('faculty_dashboard'))
        elif student and check_password_hash(student['password'], password):
            session.update({'role': 'student', 'student_id': student['id'], 'student_name': student['name'],
                            'student_roll': student['roll_number'], 'student_dept': student['department']})
            flash('Student login successful.', 'success')
            return redirect(url_for('student_dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        conn = get_db_connection()
        faculty = conn.execute('SELECT * FROM faculty WHERE email = ?', (email,)).fetchone()
        student = conn.execute('SELECT * FROM student WHERE email = ?', (email,)).fetchone()
        conn.close()

        user_type, user_id = ('faculty', faculty['id']) if faculty else ('student', student['id']) if student else (None, None)

        if user_type:
            token = secrets.token_urlsafe(32)
            password_reset_tokens[token] = {'user_type': user_type, 'user_id': user_id, 'expires_at': datetime.now() + timedelta(hours=1)}
            print(f"Password reset link for {email}: {url_for('reset_password', token=token, _external=True)}")

        flash(f'If the email {email} exists, a reset link has been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_data = password_reset_tokens.get(token)
    if not token_data or datetime.now() > token_data['expires_at']:
        flash('Invalid or expired password reset token.', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        if not new_password or new_password != confirm_password:
            flash('Passwords must match and not be empty.', 'warning')
            return render_template('reset_password.html', token=token)
        hashed_password = generate_password_hash(new_password)
        conn = get_db_connection()
        if token_data['user_type'] == 'faculty':
            conn.execute('UPDATE faculty SET password = ? WHERE id = ?', (hashed_password, token_data['user_id']))
        else:
            conn.execute('UPDATE student SET password = ? WHERE id = ?', (hashed_password, token_data['user_id']))
        conn.commit()
        conn.close()
        del password_reset_tokens[token]
        flash('Password reset successfully. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)

@app.route('/faculty_dashboard', methods=['GET', 'POST'])
def faculty_dashboard():
    if session.get('role') != 'faculty':
        flash("Please log in as faculty.", "warning")
        return redirect(url_for('login'))

    faculty_id = int(session['faculty_id'])
    conn = get_db_connection()
    faculty = conn.execute('SELECT * FROM faculty WHERE id = ?', (faculty_id,)).fetchone()

    if request.method == 'POST':
        cleared_ids = request.form.getlist('cleared_ids')
        all_student_ids = request.form.getlist('all_student_ids')

        today = datetime.now().strftime('%d-%m-%Y')

        for sid in all_student_ids:
            sid = int(sid)  # ensure it's an integer
            if str(sid) in cleared_ids:
                conn.execute('''
                    UPDATE student_clearance
                    SET cleared = 1, due_amount = 0, approval_date = ?
                    WHERE student_id = ? AND faculty_id = ?
                ''', (today, sid, faculty_id))
            else:
                conn.execute('''
                    UPDATE student_clearance
                    SET cleared = 0, approval_date = NULL
                    WHERE student_id = ? AND faculty_id = ?
                ''', (sid, faculty_id))

        conn.commit()

        for sid in cleared_ids:
            check_and_update_clearance_status(int(sid))

        conn.close()
        flash("Clearance status updated.", "success")
        return redirect(url_for('faculty_dashboard'))

    # GET method continues unchanged...


    filter_type = request.args.get('filter_type', '').lower()
    selected_department = request.args.get('department', None)
    search_query = request.args.get('search_query', '').strip()

    departments = [row['department'] for row in conn.execute(
        'SELECT DISTINCT department FROM student ORDER BY department'
    ).fetchall()]

    base_query = '''
        SELECT s.id, s.name, s.department, s.roll_number, sc.cleared, sc.due_amount
        FROM student s
        JOIN student_clearance sc ON s.id = sc.student_id
        WHERE sc.faculty_id = ?
    '''
    params = [faculty_id]

    if filter_type == 'cleared':
        base_query += ' AND sc.cleared = 1'
    elif filter_type == 'pending':
        base_query += ' AND sc.cleared = 0'

    if selected_department:
        base_query += ' AND s.department = ?'
        params.append(selected_department)

    if search_query:
        base_query += ' AND (LOWER(s.name) LIKE ? OR LOWER(s.roll_number) LIKE ?)'
        like_pattern = f'%{search_query.lower()}%'
        params.extend([like_pattern, like_pattern])

    base_query += ' ORDER BY s.name COLLATE NOCASE'

    students = conn.execute(base_query, params).fetchall()
    students = [dict(row) for row in students]

    stats = get_summary_counts(faculty_id)
    logout_form = LogoutForm()
    conn.close()

    return render_template('faculty_dashboard.html',
                           faculty=faculty,
                           students=students,
                           stats=stats,
                           logout_form=logout_form,
                           departments=departments,
                           selected_department=selected_department,
                           search_query=search_query,
                           filter_type=filter_type)

# ... your existing imports and code ...
@app.route('/student_dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        flash("Please log in as student.", "warning")
        return redirect(url_for('login'))

    student_id = session['student_id']
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM student WHERE id = ?', (student_id,)).fetchone()
    clearances = conn.execute('''
        SELECT sc.*, f.role as department_name
        FROM student_clearance sc
        LEFT JOIN faculty f ON sc.faculty_id = f.id
        WHERE sc.student_id = ?
    ''', (student_id,)).fetchall()
    conn.close()

    pending_fees = {}
    all_cleared = True
    for c in clearances:
        dept = c['department_name'] or "Unknown Department"
        due = c['due_amount'] or 0
        if due > 0:
            pending_fees[dept] = due
            all_cleared = False
        elif c['cleared'] != 1:
            all_cleared = False

    logout_form = LogoutForm()

    return render_template('student_dashboard.html',
                           student=student,
                           clearances=clearances,
                           pending_fees=pending_fees,
                           is_cleared=all_cleared,
                           logout_form=logout_form)
# Paragraph styles
styles = getSampleStyleSheet()
justified_style = ParagraphStyle(
    name='Justify',
    parent=styles['Normal'],
    fontName="Helvetica",
    fontSize=12,
    leading=18,  # 1.5 line spacing
    alignment=TA_JUSTIFY,
)

def draw_paragraph(p, text, x, y, width):
    para = Paragraph(text, justified_style)
    w, h = para.wrap(width, 500)
    para.drawOn(p, x, y - h)
    return y - h

from datetime import datetime
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

def draw_table(p, approvals, y_start):
    data = [['Department', 'Status', 'Date']]

    for approval in approvals:
        department = approval.get('department') or approval.get('role') or 'Unknown'
        status = approval.get('status', '-')
        date = approval.get('date') or datetime.now().strftime("%d-%m-%Y")
        data.append([department, status, date])

    table = Table(data, colWidths=[200, 150, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))

    w, h = table.wrapOn(p, 0, 0)
    table.drawOn(p, 50, y_start - h)
    return y_start - h


def generate_certificate_pdf(student, approvals):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Image path for logo and watermark
    header_img_path = os.path.join('static', 'images', 'logo.png')

    # --- Watermark (centered logo with transparency) ---
    try:
        watermark = ImageReader(header_img_path)
        watermark_width = 300
        watermark_height = 300
        watermark_x = (width - watermark_width) / 2
        watermark_y = (height - watermark_height) / 2

        # Set transparency if supported
        if hasattr(p, 'setFillAlpha'):
            p.setFillAlpha(0.18)  # 18% opacity

        p.drawImage(
            watermark,
            watermark_x,
            watermark_y,
            width=watermark_width,
            height=watermark_height,
            preserveAspectRatio=True,
            mask='auto'
        )

        # Reset to full opacity
        if hasattr(p, 'setFillAlpha'):
            p.setFillAlpha(1)

    except Exception as e:
        print("Watermark logo failed to load:", e)


    # Header with logo beside center-aligned text block
    header_img_path = os.path.join('static', 'images', 'logo.png')
    try:
       header = ImageReader(header_img_path)

       # Logo size and vertical position
       logo_width = 97
       logo_height = 97
       logo_y = height - 126

       # Centered text Y positions
       line1_y = height - 60
       line2_y = height - 80
       line3_y = height - 100

       # Estimate text block width to position logo to the left of center
       estimated_text_block_width = 320  # Adjust as needed
       text_block_start_x = (width / 2) - (estimated_text_block_width / 2)
       logo_x = text_block_start_x - logo_width - 10  # 10 px gap from text

       # Draw logo to the left of centered text
       p.drawImage(header, logo_x, logo_y, width=logo_width, height=logo_height, preserveAspectRatio=True, mask='auto')

       # Draw center-aligned header text
       p.setFont("Helvetica", 9)
       p.drawCentredString(width / 2, line1_y, "Srishyla Educational Trust (R), Bheemasamudra.")
       p.setFont("Helvetica-Bold", 12)
       p.drawCentredString(width / 2, line2_y, "GM UNIVERSITY")
       p.setFont("Helvetica", 9)
       p.drawCentredString(width / 2, line3_y, "Post Box No. 4, P. B. Road, Davanagere – 577 006 KARNATAKA | INDIA")

    except Exception:
       # Fallback: only center text if logo fails
       p.setFont("Helvetica", 9)
       p.drawCentredString(width / 2, height - 60, "Srishyla Educational Trust (R), Bheemasamudra.")
       p.setFont("Helvetica-Bold", 12)
       p.drawCentredString(width / 2, height - 80, "GM UNIVERSITY")
       p.setFont("Helvetica", 9)
       p.drawCentredString(width / 2, height - 100, "Post Box No. 4, P. B. Road, Davanagere – 577 006 KARNATAKA | INDIA")

    # Date
    p.setFont("Helvetica", 10)
    p.drawRightString(width - 50, height - 120, datetime.now().strftime('Date: %d.%m.%Y'))

    # Certificate Title
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, height - 160, "No Due Certificate")

    # Student Info
    p.setFont("Helvetica", 12)
    p.drawString(50, height - 200, f"Name: {student['name']}")
    p.drawString(50, height - 220, f"Department: {student['department']}")
    p.drawString(50, height - 240, f"Roll Number: {student['roll_number']}")

    # Intro paragraph
    y = height - 270
    left_margin = 50
    right_margin = width - 50
    max_width = right_margin - left_margin
    intro_para = (
        f"We hereby certify that the student named {student['name']} has initiated and completed the no-due "
        "clearance process as part of the exit procedure from the university. As per the institutional guidelines, "
        "approvals were obtained from the concerned departments to ensure all academic, administrative, and financial "
        "responsibilities were fulfilled."
    )
    y = draw_paragraph(p, intro_para, left_margin, y, max_width)

    # Approval Table with border
    y -= 20
    y = draw_table(p, approvals, y)

    # Final section - with bullets and justification
    
    he_she_line = "He/She has:"
    y = draw_paragraph(p, he_she_line, left_margin, y - 10, max_width)

    # Bulleted list
    points = [
        "Cleared all outstanding dues across various departments.",
        "Returned all university property and equipment provided during the course of study.",
        "Fulfilled all academic, administrative, and disciplinary responsibilities."
    ]
    for point in points:
        bullet_para = Paragraph(f"• {point}", justified_style)
        w, h = bullet_para.wrap(max_width, 500)
        bullet_para.drawOn(p, left_margin + 10, y - h)
        y -= h + 5

    # Final paragraph
    final_para = (
        "There are no pending obligations, liabilities, or complaints against the student as per our records. "
        "We acknowledge their sincere efforts, responsible conduct, and valuable contribution during their academic "
        "journey at the university. Their dedication and discipline have been commendable and are greatly appreciated. "
        "We extend our best wishes to them for continued success and excellence in all future endeavors."
    )
    y -= 10
    y = draw_paragraph(p, final_para, left_margin, y, max_width)

    # Signature
    p.setFont("Helvetica-Bold", 12)
    p.drawString(width - 120, y - 40, "Signature")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer



@app.route('/generate_pdf/<int:student_id>')
def generate_pdf(student_id):
    if session.get('role') not in ['faculty', 'student']:
        flash("Unauthorized access", "danger")
        return redirect(url_for('login'))

    if session.get('role') == 'student' and session.get('student_id') != student_id:
        flash("You are not authorized to access this PDF.", "danger")
        return redirect(url_for('student_dashboard'))

    conn = get_db_connection()

    # Fetch student
    student = conn.execute('SELECT * FROM student WHERE id = ?', (student_id,)).fetchone()
    if not student:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for('student_dashboard'))

    # Fetch clearances
    clearances_raw = conn.execute('''
        SELECT sc.cleared, sc.approval_date, f.role 
        FROM student_clearance sc
        LEFT JOIN faculty f ON sc.faculty_id = f.id
        WHERE sc.student_id = ?
    ''', (student_id,)).fetchall()
    conn.close()

    # Construct isolated approvals list
    approvals = []
    for row in clearances_raw:
        if row['cleared']:  # Only set date if cleared is True
            try:
                parsed_date = datetime.strptime(row['approval_date'], "%d-%m-%Y")
                approval_date = parsed_date.strftime("%d-%m-%Y")
            except (ValueError, TypeError):
                approval_date = '-'  # fallback if date is malformed or None
        else:
            approval_date = '-'

        approvals.append({
            'department': row['role'] or 'Unknown',
            'status': "Approved" if row['cleared'] else "Not Approved",
            'date': approval_date
        })

    pdf_buffer = generate_certificate_pdf(student, approvals)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{student['roll_number']}_no_due_certificate.pdf"
    )

@app.route('/approve_clearance/<int:student_id>/<int:faculty_id>', methods=['POST'])
def approve_clearance(student_id, faculty_id):
    if session.get('role') != 'faculty':
        flash("Unauthorized access", "danger")
        return redirect(url_for('login'))

    conn = get_db_connection()

    # Check if already approved with a date
    existing = conn.execute('''
        SELECT cleared, approval_date 
        FROM student_clearance 
        WHERE student_id = ? AND faculty_id = ?
    ''', (student_id, faculty_id)).fetchone()

    if existing and existing['cleared'] and existing['approval_date']:
        # Already approved — do not change the approval_date
        conn.execute('''
            UPDATE student_clearance
            SET due_amount = 0
            WHERE student_id = ? AND faculty_id = ?
        ''', (student_id, faculty_id))
    else:
        # First-time approval or no valid date — set current date
        today = datetime.now().strftime("%d-%m-%Y")
        conn.execute('''
            UPDATE student_clearance
            SET cleared = 1,
                due_amount = 0,
                approval_date = ?
            WHERE student_id = ? AND faculty_id = ?
        ''', (today, student_id, faculty_id))

    conn.commit()
    conn.close()
    flash("Clearance approved successfully.", "success")
    return redirect(url_for('faculty_dashboard'))





@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
