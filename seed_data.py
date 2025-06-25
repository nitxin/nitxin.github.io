import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

# Ensure the 'data' directory exists
os.makedirs('data', exist_ok=True)

# Connect to database in 'data' folder
db_path = os.path.join('data', 'database.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Drop existing tables
cursor.execute("DROP TABLE IF EXISTS student_clearance")
cursor.execute("DROP TABLE IF EXISTS faculty")
cursor.execute("DROP TABLE IF EXISTS student")

# Create tables
cursor.execute('''
CREATE TABLE faculty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL
)
''')

cursor.execute('''
CREATE TABLE student (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    roll_number TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
)
''')

cursor.execute('''
CREATE TABLE student_clearance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    faculty_id INTEGER NOT NULL,
    cleared INTEGER NOT NULL DEFAULT 0,
    due_amount REAL DEFAULT 0,
    approval_date TEXT DEFAULT NULL,
    FOREIGN KEY (student_id) REFERENCES student(id),
    FOREIGN KEY (faculty_id) REFERENCES faculty(id)
)
''')

# Insert faculty users
faculty_users = [
    ('admin', 'admin123', 'HOD'),
    ('john', 'john123', 'Fee department'),
    ('jane', 'jane123', 'Exam department'),
    ('michael', 'michael123', 'Transport department'),
    ('emily', 'emily123', 'labotary'),
    ('william', 'william123', 'library')
]

for username, password, role in faculty_users:
    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO faculty (username, password, role) VALUES (?, ?, ?)",
        (username, hashed_pw, role)
    )

# Insert students
students = [
    ('Alice Johnson', 'Computer Science', 'CS001', 'pass123'),
    ('Bob Smith', 'Mechanical Engineering', 'ME002', 'pass234'),
    ('Charlie Brown', 'Electrical Engineering', 'EE003', 'pass345')
]

for name, dept, roll, password in students:
    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO student (name, department, roll_number, password) VALUES (?, ?, ?, ?)",
        (name, dept, roll, hashed_pw)
    )

# Fetch inserted student and faculty IDs
cursor.execute("SELECT id FROM student WHERE roll_number = 'CS001'")
alice_id = cursor.fetchone()[0]

cursor.execute("SELECT id FROM student WHERE roll_number = 'ME002'")
bob_id = cursor.fetchone()[0]

cursor.execute("SELECT id FROM student WHERE roll_number = 'EE003'")
charlie_id = cursor.fetchone()[0]

cursor.execute("SELECT id, role FROM faculty")
faculties = cursor.fetchall()

# Current date for approved entries
today = datetime.now().strftime("%d-%m-%Y")

# Insert sample clearance data for students
for faculty_id, role in faculties:
    # --- Alice ---
    if role == 'Fee department':
        # Alice has fee due
        cursor.execute(
            '''INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount)
               VALUES (?, ?, ?, ?)''',
            (alice_id, faculty_id, 0, 100)
        )
    else:
        cursor.execute(
            '''INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount, approval_date)
               VALUES (?, ?, ?, ?, ?)''',
            (alice_id, faculty_id, 1, 0, today)
        )

    # --- Bob: all cleared ---
    cursor.execute(
        '''INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount, approval_date)
           VALUES (?, ?, ?, ?, ?)''',
        (bob_id, faculty_id, 1, 0, today)
    )

    # --- Charlie: multiple dues ---
    if role in ['library', 'Transport department']:
        cursor.execute(
            '''INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount)
               VALUES (?, ?, ?, ?)''',
            (charlie_id, faculty_id, 0, 150)
        )
    else:
        cursor.execute(
            '''INSERT INTO student_clearance (student_id, faculty_id, cleared, due_amount, approval_date)
               VALUES (?, ?, ?, ?, ?)''',
            (charlie_id, faculty_id, 1, 0, today)
        )


conn.commit()
conn.close()

print("✅ Database seeded with faculty, students, and clearance records including approval dates.")
