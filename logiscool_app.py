import csv
import io
import sqlite3
from collections import defaultdict
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from datetime import datetime

app = FastAPI(title="Logiscool Catch-up Tracker")

DB_FILE = "logiscool.db"

# --- Database Setup ---
def init_db():
    """Initializes the SQLite database with students and catchups tables."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create the students table if it doesn't exist
    c.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )""")
    # Create the catchups table, including the new 'lesson_missed' column
    c.execute("""CREATE TABLE IF NOT EXISTS catchups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        date TEXT,
        lesson_missed TEXT,
        FOREIGN KEY (student_id) REFERENCES students(id)
    )""")
    # Add the 'lesson_missed' column if it doesn't already exist from a previous run
    try:
        c.execute("ALTER TABLE catchups ADD COLUMN lesson_missed TEXT")
    except sqlite3.OperationalError:
        # This error is expected if the column already exists
        pass
    conn.commit()
    conn.close()

init_db()

# --- Models ---
class Student(BaseModel):
    name: str

class CatchUp(BaseModel):
    student_id: int
    date: str
    lesson_missed: str

# --- API Routes ---
@app.post("/students")
def add_student(student: Student):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO students (name) VALUES (?)", (student.name,))
    conn.commit()
    conn.close()
    return {"message": "Student added"}

@app.get("/students")
def list_students():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name FROM students")
    students = [{"id": row[0], "name": row[1]} for row in c.fetchall()]
    conn.close()
    return students

@app.post("/catchups")
def add_catchup(catchup: CatchUp):
    """Records a new catch-up with the student ID, date, and lesson missed."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO catchups (student_id, date, lesson_missed) VALUES (?, ?, ?)",
              (catchup.student_id, catchup.date, catchup.lesson_missed))
    conn.commit()
    conn.close()
    return {"message": "Catch-up recorded"}

@app.get("/catchups/by_name/{student_name}")
def list_catchups_by_name(student_name: str):
    """Lists all catch-ups for a specific student, including the lesson missed."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM students WHERE name=?", (student_name,))
    student_id = c.fetchone()
    if not student_id:
        conn.close()
        return []

    c.execute("SELECT date, lesson_missed FROM catchups WHERE student_id=?", (student_id[0],))
    data = c.fetchall()
    conn.close()
    result = []
    for i, row in enumerate(data, start=1):
        charge = "Free" if i <= 2 else "Charge"
        result.append({"catchup_no": i, "date": row[0], "lesson_missed": row[1], "charge": charge})
    return result

@app.get("/catchups/all")
def list_all_catchups():
    """Returns all catch-ups grouped by month, including the lesson missed."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT s.name, c.date, c.student_id, c.lesson_missed FROM students s JOIN catchups c ON s.id = c.student_id ORDER BY c.date")
    all_catchups = c.fetchall()
    conn.close()

    monthly_catchups = defaultdict(list)
    for name, date_str, student_id, lesson_missed in all_catchups:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        month_key = date_obj.strftime('%Y-%m')
        monthly_catchups[month_key].append((name, date_str, student_id, lesson_missed))
    
    return monthly_catchups

@app.get("/catchups/download/by_name/{student_name}")
def download_catchups_by_name(student_name: str):
    """Generates a CSV report for a student, including the lesson missed."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM students WHERE name=?", (student_name,))
    student_id = c.fetchone()
    if not student_id:
        conn.close()
        return StreamingResponse(io.StringIO("Student not found."), media_type="text/plain")
    
    c.execute("SELECT date, lesson_missed FROM catchups WHERE student_id=?", (student_id[0],))
    data = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Catch-up Tracker Report for {student_name}"])
    writer.writerow(["Catch-up Number", "Date", "Lesson Missed", "Status"])
    
    for i, row in enumerate(data, start=1):
        charge_status = "Free" if i <= 2 else "Charge"
        writer.writerow([i, row[0], row[1], charge_status])
    
    output.seek(0)
    
    headers = {
        "Content-Disposition": f"attachment; filename=catchups_report_{student_name.replace(' ', '_')}.csv"
    }

    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)

@app.get("/catchups/download/all")
def download_all_catchups():
    """Generates a comprehensive CSV report of all catch-ups, including lesson missed."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT s.name, c.date, c.lesson_missed FROM students s JOIN catchups c ON s.id = c.student_id ORDER BY c.date")
    data = c.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Catch-up Tracker - Full Report"])
    writer.writerow([])

    monthly_data = defaultdict(list)
    for student_name, catchup_date, lesson_missed in data:
        month_key = datetime.strptime(catchup_date, '%Y-%m-%d').strftime('%Y-%m')
        monthly_data[month_key].append((student_name, catchup_date, lesson_missed))
    
    for month_key, entries in monthly_data.items():
        month_name = datetime.strptime(month_key, '%Y-%m').strftime('%B %Y')
        writer.writerow([f"Month: {month_name}"])
        writer.writerow(["Student Name", "Catch-up Date", "Lesson Missed", "Status"])
        
        student_catchup_count = defaultdict(int)
        for student_name, catchup_date, lesson_missed in entries:
            student_catchup_count[student_name] += 1
            charge_status = "Free" if student_catchup_count[student_name] <= 2 else "Charge"
            writer.writerow([student_name, catchup_date, lesson_missed, charge_status])
        writer.writerow([])

    output.seek(0)
    
    headers = {
        "Content-Disposition": "attachment; filename=all_catchups_monthly_report.csv"
    }

    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)

# --- Frontend ---
@app.get("/", response_class=HTMLResponse)
def home():
    current_month_name = datetime.now().strftime('%B')
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Logiscool Catch-up Tracker</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
            :root {{
                --primary-color: #00AEEF;
                --secondary-color: #ED0973;
                --normal-green: #28a745;
                --playful-pink: #FF69B4;
                --playful-blue: #00BFFF;
                --sidebar-bg: #0047AB;
                --text-color: #2D2D2D;
                --card-bg: #fff;
                --dashboard-bg: #f5f7fa;
                --text-light: #aaa;
            }}

            body {{
                font-family: 'Poppins', sans-serif;
                background-color: var(--dashboard-bg);
                margin: 0;
                display: flex;
                min-height: 100vh;
                color: var(--text-color);
            }}

            .sidebar {{
                width: 250px;
                background-color: var(--sidebar-bg);
                color: #fff;
                display: flex;
                flex-direction: column;
                padding: 20px;
                box-shadow: 2px 0 5px rgba(0, 0, 0, 0.1);
            }}
            .sidebar-header {{
                display: flex;
                align-items: center;
                margin-bottom: 30px;
            }}
            .sidebar-header img {{
                width: 50px;
                height: 50px;
                border-radius: 50%;
                margin-right: 15px;
                border: 2px solid #fff;
            }}
            .sidebar-header h3 {{
                margin: 0;
                font-size: 1.2rem;
                color: #fff;
                display: flex;
                align-items: center;
            }}
            .rubiks-cube-icon {{
                margin-right: 10px;
            }}
            .sidebar-nav a {{
                display: flex;
                align-items: center;
                padding: 12px 15px;
                text-decoration: none;
                color: #fff;
                border-radius: 8px;
                margin-bottom: 10px;
                transition: background-color 0.3s, color 0.3s;
            }}
            .sidebar-nav a:hover, .sidebar-nav a.active {{
                background-color: #1a64bd;
            }}
            .sidebar-nav i {{
                margin-right: 15px;
                font-size: 1.2rem;
            }}

            .main-content {{
                flex-grow: 1;
                display: flex;
                flex-direction: column;
            }}
            .top-bar {{
                background-color: var(--card-bg);
                padding: 15px 30px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            }}
            .dashboard-header {{
                font-size: 1.5rem;
                font-weight: 600;
            }}
            .user-info {{
                display: flex;
                align-items: center;
            }}
            .user-info i {{
                margin-right: 10px;
                font-size: 1.2rem;
                color: var(--text-light);
            }}
            .month-nav {{
                display: flex;
                align-items: center;
                font-weight: 600;
                cursor: pointer;
            }}
            .month-nav button {{
                background: none;
                border: none;
                color: var(--primary-color);
                font-size: 1rem;
                cursor: pointer;
                transition: transform 0.2s;
            }}
            .month-nav button:hover {{
                transform: scale(1.1);
            }}
            .month-nav span {{
                margin: 0 10px;
                color: var(--text-color);
            }}
            .dashboard-cards {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 20px;
                padding: 30px;
            }}
            .card {{
                background-color: var(--card-bg);
                padding: 25px;
                border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
                color: #fff;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
            }}
            .card-1 {{ background-color: #1281c7; }}
            .card-2 {{ background-color: var(--normal-green); }}
            .card-title {{
                font-size: 1.2rem;
                font-weight: 600;
                margin-bottom: 5px;
            }}
            .card-value {{
                font-size: 2.5rem;
                font-weight: 700;
                margin: 0;
            }}
            .card-link {{
                text-decoration: none;
                color: #fff;
                font-size: 0.9rem;
                margin-top: 15px;
                display: inline-block;
            }}
            .card-link i {{
                margin-left: 5px;
            }}

            .content-area {{
                padding: 0 30px 30px;
                display: grid;
                gap: 20px;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            }}
            .analytics-card {{
                background-color: var(--card-bg);
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05);
            }}
            .analytics-card h3 {{
                color: var(--text-color);
                border-bottom: 2px solid var(--text-light);
                padding-bottom: 10px;
                margin-bottom: 20px;
            }}
            .form-card {{
                grid-column: 1 / -1;
            }}
            .form-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 15px;
                align-items: flex-end;
            }}
            .form-group {{
                display: flex;
                flex-direction: column;
            }}
            .form-group label {{
                font-size: 0.9rem;
                margin-bottom: 5px;
                color: var(--text-light);
            }}
            .form-container input, .form-container button {{
                padding: 12px;
                border-radius: 8px;
                border: 1px solid #ddd;
                font-size: 1rem;
            }}
            .form-container button {{
                background-color: var(--primary-color);
                color: white;
                cursor: pointer;
                transition: background-color 0.3s;
                border: none;
            }}
            .form-container button:hover {{
                background-color: #008cc9;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 15px;
                text-align: left;
                border-bottom: 1px solid #f0f4f8;
            }}
            th {{
                background-color: var(--primary-color);
                color: white;
                font-weight: 600;
                text-transform: uppercase;
            }}
            tr:nth-child(even) {{
                background-color: #f3f9ff;
            }}
            tr:hover {{
                background-color: #e0f2fe;
            }}
        </style>
        <!-- Font Awesome for icons -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    </head>
    <body>

        <div class="sidebar">
            <div class="sidebar-header">
                <svg class="rubiks-cube-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="2" y="10" width="7" height="7" fill="#0051BA" stroke="black" stroke-width="1.5"/>
                    <rect x="9" y="10" width="6" height="7" fill="#FFD500" stroke="black" stroke-width="1.5"/>
                    <rect x="15" y="10" width="7" height="7" fill="#C41E3A" stroke="black" stroke-width="1.5"/>
                    <rect x="2" y="3" width="7" height="7" fill="#FFFFFF" stroke="black" stroke-width="1.5"/>
                    <rect x="9" y="3" width="6" height="7" fill="#009B48" stroke="black" stroke-width="1.5"/>
                    <rect x="15" y="3" width="7" height="7" fill="#FF5800" stroke="black" stroke-width="1.5"/>
                </svg>
                <h3>Logiscool Tracker</h3>
            </div>
            <div class="sidebar-nav">
                <div style="font-size: 0.8rem; color: var(--text-light); margin-bottom: 10px;">DASHBOARD</div>
                <a href="#" class="active"><i class="fas fa-home"></i>Home</a>
                <a href="#" onclick="getStudents()"><i class="fas fa-user-friends"></i>Students</a>
                <a href="#" onclick="getCatchups()"><i class="fas fa-file-alt"></i>All Catchups</a>
                <a href="#" onclick="downloadAllCatchups()"><i class="fas fa-download"></i>Download Report</a>
            </div>
        </div>

        <div class="main-content">
            <div class="top-bar">
                <div class="dashboard-header">Dashboard</div>
                <div class="user-info">
                    <i class="fas fa-bell"></i>
                    <i class="fas fa-cog"></i>
                    <div class="month-nav">
                        <button onclick="changeMonth(-1)"><i class="fas fa-chevron-left"></i></button>
                        <span id="currentMonthDisplay">{current_month_name}</span>
                        <button onclick="changeMonth(1)"><i class="fas fa-chevron-right"></i></button>
                    </div>
                </div>
            </div>

            <div class="dashboard-cards">
                <div class="card card-1">
                    <div>
                        <h4 class="card-title">Total Students</h4>
                        <p class="card-value" id="totalStudentsValue">0</p>
                    </div>
                    <a href="#" class="card-link" onclick="getStudents()">View Students <i class="fas fa-arrow-right"></i></a>
                </div>
                <div class="card card-2">
                    <div>
                        <h4 class="card-title">Total Catch-ups</h4>
                        <p class="card-value" id="totalCatchupsValue">0</p>
                    </div>
                    <a href="#" class="card-link" onclick="getCatchups()">View Catch-ups <i class="fas fa-arrow-right"></i></a>
                </div>
            </div>

            <div class="content-area">
                <div class="analytics-card" id="recordCatchupCard">
                    <h3>Record a Catch-up</h3>
                    <div class="form-container">
                        <div class="form-group">
                            <label for="studentId">Student ID</label>
                            <input id="studentId" type="number" placeholder="e.g., 1">
                        </div>
                        <div class="form-group">
                            <label for="date">Date</label>
                            <input id="date" type="date">
                        </div>
                        <div class="form-group">
                            <label for="lessonMissed">Lesson Missed</label>
                            <input id="lessonMissed" type="text" placeholder="e.g., Python 1, Lesson 5">
                        </div>
                        <button onclick="addCatchup()">Add Catch-up</button>
                    </div>
                </div>

                <div class="analytics-card" id="trackCatchupsCard">
                    <h3>Track & Download</h3>
                    <div class="form-container">
                        <div class="form-group">
                            <label for="catchupStudentName">Student Name</label>
                            <input id="catchupStudentName" type="text" placeholder="e.g., John Doe">
                        </div>
                        <button onclick="getCatchupsForStudentByName()">View</button>
                        <button class="download-btn" onclick="downloadCatchupsForStudentByName()">Download CSV</button>
                    </div>
                    <table id="catchupsTable" style="display:none;">
                        <thead>
                            <tr><th>Catch-up #</th><th>Date</th><th>Lesson Missed</th><th>Status</th></tr>
                        </thead>
                        <tbody id="catchupsBody"></tbody>
                    </table>
                </div>

                <div class="analytics-card form-card" id="addStudentCard">
                    <h3>Student Management</h3>
                    <div class="form-container">
                        <div class="form-group">
                            <label for="studentName">Student Name</label>
                            <input id="studentName" placeholder="Enter student name">
                        </div>
                        <button onclick="addStudent()">Add Student</button>
                        <button onclick="getStudents()">View All Students</button>
                    </div>
                    <table id="studentsTable" style="display:none;">
                        <thead>
                            <tr><th>ID</th><th>Name</th></tr>
                        </thead>
                        <tbody id="studentsBody"></tbody>
                    </table>
                </div>
            </div>
            <div class="analytics-card form-card" id="monthlyCatchupsContainer" style="display:none;">
                <h3>Monthly Catch-up Report</h3>
                <table id="monthlyCatchupsTable">
                    <thead>
                        <tr><th>Student Name</th><th>Catch-up Date</th><th>Lesson Missed</th><th>Status</th></tr>
                    </thead>
                    <tbody id="monthlyCatchupsBody"></tbody>
                </table>
            </div>
        </div>

        <script>
            let currentMonth = new Date().getMonth();
            let currentYear = new Date().getFullYear();

            async function updateDashboardMetrics() {{
                const students = await getStudentsData();
                const catchups = await getAllCatchupsData();
                document.getElementById("totalStudentsValue").textContent = students.length;
                
                let totalCatchupsCount = 0;
                
                for (const month in catchups) {{
                    catchups[month].forEach(c => {{
                        totalCatchupsCount++;
                    }});
                }}
                
                document.getElementById("totalCatchupsValue").textContent = totalCatchupsCount;
            }}

            async function getStudentsData() {{
                const res = await fetch("/students");
                return res.json();
            }}

            async function getAllCatchupsData() {{
                const res = await fetch("/catchups/all");
                return res.json();
            }}
            
            async function addStudent() {{
                let name = document.getElementById("studentName").value;
                if (!name) {{
                    let customAlert = document.createElement("div");
                    customAlert.innerHTML = "Please enter a name.";
                    customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                    document.body.appendChild(customAlert);
                    setTimeout(() => customAlert.remove(), 2000);
                    return;
                }}
                await fetch("/students", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{"name": name}})
                }});
                let customAlert = document.createElement("div");
                customAlert.innerHTML = "Student added successfully!";
                customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                document.body.appendChild(customAlert);
                setTimeout(() => customAlert.remove(), 2000);
                document.getElementById("studentName").value = "";
                updateDashboardMetrics();
                getStudents();
            }}

            async function getStudents() {{
                const data = await getStudentsData();
                let tbody = document.getElementById("studentsBody");
                tbody.innerHTML = "";
                data.forEach(s => {{
                    tbody.innerHTML += `<tr><td>${{s.id}}</td><td>${{s.name}}</td></tr>`;
                }});
                document.getElementById("studentsTable").style.display = "table";
            }}

            async function addCatchup() {{
                let studentId = document.getElementById("studentId").value;
                let date = document.getElementById("date").value;
                let lessonMissed = document.getElementById("lessonMissed").value;
                if (!studentId || !date || !lessonMissed) {{
                    let customAlert = document.createElement("div");
                    customAlert.innerHTML = "Please fill in all fields.";
                    customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                    document.body.appendChild(customAlert);
                    setTimeout(() => customAlert.remove(), 2000);
                    return;
                }}
                await fetch("/catchups", {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{"student_id": parseInt(studentId), "date": date, "lesson_missed": lessonMissed}})
                }});
                let customAlert = document.createElement("div");
                customAlert.innerHTML = "Catch-up recorded successfully!";
                customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                document.body.appendChild(customAlert);
                setTimeout(() => customAlert.remove(), 2000);
                document.getElementById("date").value = "";
                document.getElementById("lessonMissed").value = "";
                updateDashboardMetrics();
            }}

            async function getCatchupsForStudentByName() {{
                let studentName = document.getElementById("catchupStudentName").value;
                if (!studentName) {{
                    let customAlert = document.createElement("div");
                    customAlert.innerHTML = "Please enter a Student Name to view catch-ups.";
                    customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                    document.body.appendChild(customAlert);
                    setTimeout(() => customAlert.remove(), 2000);
                    return;
                }}
                let res = await fetch("/catchups/by_name/" + encodeURIComponent(studentName));
                let data = await res.json();
                let tbody = document.getElementById("catchupsBody");
                tbody.innerHTML = "";
                if (data.length === 0) {{
                    tbody.innerHTML = `<tr><td colspan="4">No catch-ups found for this student.</td></tr>`;
                }} else {{
                    data.forEach(c => {{
                        tbody.innerHTML += `<tr><td>${{c.catchup_no}}</td><td>${{c.date}}</td><td>${{c.lesson_missed}}</td><td>${{c.charge}}</td></tr>`;
                    }});
                }}
                document.getElementById("catchupsTable").style.display = "table";
            }}

            async function getCatchups() {{
                await displayMonthlyCatchups();
            }}

            async function changeMonth(direction) {{
                currentMonth += direction;
                if (currentMonth > 11) {{
                    currentMonth = 0;
                    currentYear++;
                }} else if (currentMonth < 0) {{
                    currentMonth = 11;
                    currentYear--;
                }}

                const monthDate = new Date(currentYear, currentMonth);
                document.getElementById("currentMonthDisplay").textContent = monthDate.toLocaleString('default', {{ month: 'long' }});
                await displayMonthlyCatchups();
            }}

            async function displayMonthlyCatchups() {{
                const monthlyData = await getAllCatchupsData();
                const tbody = document.getElementById("monthlyCatchupsBody");
                tbody.innerHTML = "";

                const monthKey = `${{currentYear}}-${{String(currentMonth + 1).padStart(2, '0')}}`;
                
                if (monthlyData[monthKey] && monthlyData[monthKey].length > 0) {{
                    const studentCatchupCount = {{}};
                    monthlyData[monthKey].forEach(c => {{
                        const name = c[0];
                        const date = c[1];
                        const lessonMissed = c[3];
                        studentCatchupCount[name] = (studentCatchupCount[name] || 0) + 1;
                        const status = studentCatchupCount[name] <= 2 ? "Free" : "Charge";
                        tbody.innerHTML += `<tr><td>${{name}}</td><td>${{date}}</td><td>${{lessonMissed}}</td><td>${{status}}</td></tr>`;
                    }});
                }} else {{
                    tbody.innerHTML = `<tr><td colspan="4">No catch-ups found for ${{document.getElementById('currentMonthDisplay').textContent}}</td></tr>`;
                }}
                document.getElementById("monthlyCatchupsContainer").style.display = "block";
            }}

            function downloadCatchupsForStudentByName() {{
                let studentName = document.getElementById("catchupStudentName").value;
                if (!studentName) {{
                    let customAlert = document.createElement("div");
                    customAlert.innerHTML = "Please enter a Student Name to download the CSV.";
                    customAlert.style.cssText = "position:fixed;top:50%;left:50%;transform:translate(-50%, -50%);background-color:white;padding:20px;border-radius:10px;box-shadow:0 0 10px rgba(0,0,0,0.5);z-index:1000;";
                    document.body.appendChild(customAlert);
                    setTimeout(() => customAlert.remove(), 2000);
                    return;
                }}
                window.open("/catchups/download/by_name/" + encodeURIComponent(studentName), "_blank");
            }}

            function downloadAllCatchups() {{
                window.open("/catchups/download/all", "_blank");
            }}
            
            document.addEventListener("DOMContentLoaded", updateDashboardMetrics);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
