
import pdfplumber
from docx import Document
import sqlite3
import os
import uuid
import re
import json

from functools import wraps
from datetime import datetime
from urllib.parse import quote_plus
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename

try:
    from werkzeug.security import generate_password_hash, check_password_hash
except ImportError:
    import hashlib, secrets
    def generate_password_hash(password):
        salt = secrets.token_hex(16)
        hash_val = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"{salt}${hash_val}"

    def check_password_hash(p_hash, password):
        if not p_hash or "$" not in p_hash:
            return False
        salt, hash_val = p_hash.split("$", 1)
        expected = hashlib.sha256((salt + password).encode()).hexdigest()
        return secrets.compare_digest(hash_val, expected)


# ==========================================
# 1. FLASK CONFIGURATION
# ==========================================

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "resume_analyzer_super_secret_session_2026_key")

DATABASE = "resume_analyzer.db"
UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {"pdf", "docx"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ==========================================
# 2. DATABASE INITIALIZATION
# ==========================================

def init_db():

    with sqlite3.connect(DATABASE) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'Student',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_criteria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_title TEXT NOT NULL,
                company_name TEXT,
                education TEXT,
                experience TEXT,
                required_skills TEXT NOT NULL,
                job_description TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS resume_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                filename TEXT NOT NULL,
                job_title TEXT,
                ats_score INTEGER NOT NULL,
                total_skills INTEGER NOT NULL,
                matched_skills TEXT NOT NULL,
                missing_skills TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Migration: ensure user_id column exists
        try:
            conn.execute("ALTER TABLE resume_history ADD COLUMN user_id INTEGER;")
        except sqlite3.OperationalError:
            pass


# Initialize tables even when Flask is started using flask run.
init_db()


# ==========================================
# 2.1 AUTHENTICATION HELPERS
# ==========================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

    return user


def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session or not get_current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# ==========================================
# 3. COURSE RECOMMENDATION DATABASE
# ==========================================

COURSE_MAP = {
    "python": "Python Programming Complete Course",
    "java": "Java Programming Complete Course",
    "javascript": "JavaScript Complete Course",
    "html": "HTML Web Development Course",
    "css": "CSS Complete Course",
    "react": "React JS Complete Course",
    "node.js": "Node.js Backend Development Course",
    "nodejs": "Node.js Backend Development Course",
    "flask": "Python Flask Web Development Course",
    "django": "Django Web Development Course",
    "sql": "SQL Database Complete Course",
    "mysql": "MySQL Database Course",
    "mongodb": "MongoDB Complete Course",
    "c": "C Programming Complete Course",
    "c++": "C++ Programming Complete Course",
    "data structures": "Data Structures and Algorithms Course",
    "dsa": "Data Structures and Algorithms Course",
    "algorithms": "Algorithms Complete Course",
    "oops": "Object Oriented Programming Course",
    "git": "Git and GitHub Complete Course",
    "github": "Git and GitHub Complete Course",
    "bootstrap": "Bootstrap Web Development Course",
    "spring boot": "Spring Boot Complete Course",
    "rest api": "REST API Development Course",
    "machine learning": "Machine Learning Complete Course",
    "artificial intelligence": "Artificial Intelligence Course",
    "problem solving": "Problem Solving Programming Course",
    "communication skills": "Communication Skills Course",
    "linux": "Linux Complete Course",
    "aws": "AWS Cloud Computing Course",
    "docker": "Docker Complete Course",
    "typescript": "TypeScript Complete Course"
}


# ==========================================
# 4. COURSE RECOMMENDATIONS
# ==========================================

def recommend_courses(missing_skills):

    recommendations = []

    for skill in missing_skills:

        skill_key = skill.lower().strip()

        course_title = COURSE_MAP.get(
            skill_key,
            skill.strip() + " Complete Learning Course"
        )

        search_query = quote_plus(course_title)

        youtube_url = (
            "https://www.youtube.com/results?search_query="
            + search_query
        )

        recommendations.append({
            "skill": skill,
            "title": course_title,
            "url": youtube_url,
            "platform": "YouTube",
            "description": (
                "Improve your " + skill +
                " skills with this recommended course."
            )
        })

    return recommendations[:8]


# ==========================================
# 5. RESUME TEXT EXTRACTION
# ==========================================

def extract_resume_text(file_path):

    text = ""

    if file_path.lower().endswith(".pdf"):

        with pdfplumber.open(file_path) as pdf:

            for page in pdf.pages:

                page_text = page.extract_text()

                if page_text:
                    text += page_text + "\n"

    elif file_path.lower().endswith(".docx"):

        doc = Document(file_path)

        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"

    return text.strip()


# ==========================================
# 6. FILE VALIDATION
# ==========================================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# ==========================================
# 7. AUTHENTICATION & PROFILE ROUTES
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if "user_id" in session and get_current_user():
        return redirect(url_for("dashboard"))

    error_message = None

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "Student").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:
            error_message = "Please fill all required fields."
        elif len(password) < 6:
            error_message = "Password must be at least 6 characters long."
        else:
            with sqlite3.connect(DATABASE) as conn:
                conn.row_factory = sqlite3.Row
                existing = conn.execute(
                    "SELECT id FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

                if existing:
                    error_message = "An account with this email already exists. Please log in."
                else:
                    pwd_hash = generate_password_hash(password)
                    created_at = datetime.now().strftime("%d %b %Y")

                    cursor = conn.execute("""
                        INSERT INTO users (name, email, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (name, email, pwd_hash, role, created_at))

                    new_user_id = cursor.lastrowid

                    # Assign previous orphan records if any
                    conn.execute(
                        "UPDATE resume_history SET user_id = ? WHERE user_id IS NULL",
                        (new_user_id,)
                    )

                    session["user_id"] = new_user_id
                    session["user_name"] = name
                    session["user_email"] = email
                    session["user_role"] = role

                    return redirect(url_for("dashboard"))

    return render_template("register.html", error_message=error_message)


@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session and get_current_user():
        return redirect(url_for("dashboard"))

    error_message = None
    success_message = request.args.get("message")

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            error_message = "Please enter both email and password."
        else:
            with sqlite3.connect(DATABASE) as conn:
                conn.row_factory = sqlite3.Row
                user = conn.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_email"] = user["email"]
                session["user_role"] = user["role"]

                # Assign any orphan history records to this user
                with sqlite3.connect(DATABASE) as conn:
                    conn.execute(
                        "UPDATE resume_history SET user_id = ? WHERE user_id IS NULL",
                        (user["id"],)
                    )

                return redirect(url_for("dashboard"))
            else:
                error_message = "Invalid email or password. Please try again."

    return render_template(
        "login.html",
        error_message=error_message,
        success_message=success_message
    )


@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for(
        "login",
        message="You have been logged out successfully."
    ))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():

    user = get_current_user()
    error_message = None
    success_message = None

    if request.method == "POST":

        action = request.form.get("action")

        if action == "update_profile":

            new_name = request.form.get("name", "").strip()
            new_role = request.form.get("role", "").strip()

            if not new_name or not new_role:
                error_message = "Name and role cannot be empty."
            else:
                with sqlite3.connect(DATABASE) as conn:
                    conn.execute(
                        "UPDATE users SET name = ?, role = ? WHERE id = ?",
                        (new_name, new_role, user["id"])
                    )
                session["user_name"] = new_name
                session["user_role"] = new_role
                user = get_current_user()
                success_message = "Profile details updated successfully!"

        elif action == "change_password":

            current_pwd = request.form.get("current_password", "")
            new_pwd = request.form.get("new_password", "")

            if not check_password_hash(user["password_hash"], current_pwd):
                error_message = "Incorrect current password."
            elif len(new_pwd) < 6:
                error_message = "New password must be at least 6 characters long."
            else:
                new_hash = generate_password_hash(new_pwd)
                with sqlite3.connect(DATABASE) as conn:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (new_hash, user["id"])
                    )
                success_message = "Password updated successfully!"

    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row

        user_history = conn.execute("""
            SELECT * FROM resume_history
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user["id"],)).fetchall()

        stats = conn.execute("""
            SELECT
                COUNT(*) AS total,
                AVG(ats_score) AS average,
                MAX(ats_score) AS best
            FROM resume_history
            WHERE user_id = ?
        """, (user["id"],)).fetchone()

    total_resumes = stats["total"] or 0
    average_score = round(stats["average"]) if stats["average"] is not None else 0
    best_score = round(stats["best"]) if stats["best"] is not None else 0

    return render_template(
        "profile.html",
        current_user=user,
        user_history=user_history,
        total_resumes=total_resumes,
        average_score=average_score,
        best_score=best_score,
        success_message=success_message,
        error_message=error_message
    )


# ==========================================
# 8. DASHBOARD ROUTE WITH LIVE STATISTICS
# ==========================================

def get_dashboard_statistics(user_id=None):

    with sqlite3.connect(DATABASE) as conn:

        conn.row_factory = sqlite3.Row

        if user_id:
            total_resumes = conn.execute("""
                SELECT COUNT(*) AS total
                FROM resume_history
                WHERE user_id = ?
            """, (user_id,)).fetchone()["total"] or 0

            avg_score = conn.execute("""
                SELECT AVG(ats_score) AS average
                FROM resume_history
                WHERE user_id = ?
            """, (user_id,)).fetchone()["average"]

            all_skill_rows = conn.execute("""
                SELECT matched_skills
                FROM resume_history
                WHERE user_id = ?
            """, (user_id,)).fetchall()
        else:
            total_resumes = 0
            avg_score = 0
            all_skill_rows = []

        average_score = (
            round(avg_score)
            if avg_score is not None
            else 0
        )

    unique_skills = set()

    for row in all_skill_rows:

        try:
            skills = json.loads(row["matched_skills"])

            for skill in skills:
                if skill and skill.strip():
                    unique_skills.add(skill.strip().lower())

        except (TypeError, ValueError):
            continue

    skills_identified = len(unique_skills)

    return {
        "total_resumes": total_resumes,
        "average_score": average_score,
        "skills_identified": skills_identified
    }


@app.route("/api/stats")
@login_required
def api_stats():

    user_id = session.get("user_id")
    stats = get_dashboard_statistics(user_id)

    return jsonify({
        "success": True,
        "total_resumes": stats["total_resumes"],
        "average_score": stats["average_score"],
        "skills_identified": stats["skills_identified"]
    })


@app.route("/")
@login_required
def dashboard():

    user_id = session.get("user_id")
    current_user = get_current_user()

    if not current_user:
        session.clear()
        return redirect(url_for("login"))

    stats = get_dashboard_statistics(user_id)

    with sqlite3.connect(DATABASE) as conn:

        conn.row_factory = sqlite3.Row

        recent_history = conn.execute("""
            SELECT *
            FROM resume_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 5
        """, (user_id,)).fetchall()

        latest_row = conn.execute("""
            SELECT *
            FROM resume_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,)).fetchone()

    latest_analysis = None
    latest_matched = []
    latest_missing = []
    recommended_courses = []

    if latest_row:

        try:
            latest_matched = json.loads(latest_row["matched_skills"])
        except (TypeError, ValueError):
            latest_matched = []

        try:
            latest_missing = json.loads(latest_row["missing_skills"])
        except (TypeError, ValueError):
            latest_missing = []

        latest_analysis = {
            "id": latest_row["id"],
            "filename": latest_row["filename"],
            "job_title": latest_row["job_title"],
            "ats_score": latest_row["ats_score"],
            "total_skills": latest_row["total_skills"],
            "matched_skills": latest_matched,
            "missing_skills": latest_missing,
            "created_at": latest_row["created_at"]
        }

        recommended_courses = recommend_courses(latest_missing)

    return render_template(
        "dashboard.html",
        current_user=current_user,
        total_resumes=stats["total_resumes"],
        average_score=stats["average_score"],
        skills_identified=stats["skills_identified"],
        recent_history=recent_history,
        latest_analysis=latest_analysis,
        latest_matched_skills=latest_matched,
        latest_missing_skills=latest_missing,
        recommended_courses=recommended_courses
    )


# ==========================================
# 8. JOB CRITERIA ROUTE
# ==========================================

@app.route("/job-criteria", methods=["GET", "POST"])
@login_required
def job_criteria():

    success_message = None
    error_message = None

    if request.method == "POST":

        job_title = request.form.get(
            "jobTitle", ""
        ).strip()

        company_name = request.form.get(
            "companyName", ""
        ).strip()

        education = request.form.get(
            "education", ""
        ).strip()

        experience = request.form.get(
            "experience", ""
        ).strip()

        required_skills = request.form.get(
            "requiredSkills", ""
        ).strip()

        job_description = request.form.get(
            "jobDescription", ""
        ).strip()

        if not job_title or not required_skills or not job_description:

            error_message = "Please fill all required fields!"

        else:

            try:

                with sqlite3.connect(DATABASE) as conn:

                    conn.execute("""
                        INSERT INTO job_criteria
                        (
                            job_title,
                            company_name,
                            education,
                            experience,
                            required_skills,
                            job_description
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        job_title,
                        company_name,
                        education,
                        experience,
                        required_skills,
                        job_description
                    ))

                success_message = (
                    "Job Criteria saved successfully!"
                )

            except sqlite3.Error as e:

                error_message = "Database error: " + str(e)

    with sqlite3.connect(DATABASE) as conn:

        conn.row_factory = sqlite3.Row

        saved_criteria = conn.execute("""
            SELECT *
            FROM job_criteria
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

    return render_template(
        "job_criteria.html",
        success_message=success_message,
        error_message=error_message,
        saved_criteria=saved_criteria
    )


# ==========================================
# 9. RESUME ANALYSIS ROUTE
# ==========================================

@app.route("/analyze", methods=["POST"])
@login_required
def analyze_resume():

    user_id = session.get("user_id")

    if "resume" not in request.files:

        return jsonify({
            "error": "Resume file not received!"
        }), 400

    resume = request.files["resume"]

    if resume.filename == "":

        return jsonify({
            "error": "Please select a resume!"
        }), 400

    if not allowed_file(resume.filename):

        return jsonify({
            "error": "Only PDF and DOCX files are allowed!"
        }), 400

    original_name = secure_filename(resume.filename)

    if not original_name:

        return jsonify({
            "error": "Invalid resume filename!"
        }), 400

    extension = original_name.rsplit(".", 1)[1].lower()

    unique_filename = str(uuid.uuid4()) + "." + extension

    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        unique_filename
    )

    resume.save(file_path)

    try:

        # Extract resume text

        resume_text = extract_resume_text(file_path)

        if not resume_text:

            return jsonify({
                "error": "No readable text found in resume!"
            }), 400

        # Fetch latest job criteria

        with sqlite3.connect(DATABASE) as conn:

            conn.row_factory = sqlite3.Row

            job = conn.execute("""
                SELECT *
                FROM job_criteria
                ORDER BY id DESC
                LIMIT 1
            """).fetchone()

        if job is None:

            return jsonify({
                "error": "Please save Job Criteria first!"
            }), 400

        # Extract required skills

        required_skills = [
            skill.strip()
            for skill in re.split(
                r"[,;\n]+",
                job["required_skills"]
            )
            if skill.strip()
        ]

        # Remove duplicate skills

        required_skills = list(dict.fromkeys(required_skills))

        # Compare resume skills

        resume_lower = resume_text.lower()

        matched_skills = []
        missing_skills = []

        for skill in required_skills:

            pattern = (
                r"(?<!\w)"
                + re.escape(skill.lower())
                + r"(?!\w)"
            )

            if re.search(pattern, resume_lower):

                matched_skills.append(skill)

            else:

                missing_skills.append(skill)

        # Calculate ATS score

        total_skills = len(required_skills)

        ats_score = (
            round(
                (len(matched_skills) / total_skills) * 100
            )
            if total_skills > 0 else 0
        )

        # Generate course recommendations

        recommended_courses = recommend_courses(
            missing_skills
        )

        analysis_time = datetime.now().strftime("%d %b %Y, %I:%M %p")

        # Save successful analysis to database

        with sqlite3.connect(DATABASE) as conn:

            cursor = conn.execute("""
                INSERT INTO resume_history
                (
                    user_id,
                    filename,
                    job_title,
                    ats_score,
                    total_skills,
                    matched_skills,
                    missing_skills,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                original_name,
                job["job_title"],
                ats_score,
                total_skills,
                json.dumps(matched_skills),
                json.dumps(missing_skills),
                analysis_time
            ))

            new_history_id = cursor.lastrowid

        # Get updated statistics for live dashboard sync

        updated_stats = get_dashboard_statistics(user_id)

        # Send complete result to frontend

        return jsonify({

            "success": True,

            "message": "Resume analysis completed successfully!",

            "id": new_history_id,

            "filename": original_name,

            "job_title": job["job_title"],

            "ats_score": ats_score,

            "total_skills": total_skills,

            "matched_count": len(matched_skills),

            "missing_count": len(missing_skills),

            "matched_skills": matched_skills,

            "missing_skills": missing_skills,

            "recommended_courses": recommended_courses,

            "total_resumes": updated_stats["total_resumes"],

            "average_score": updated_stats["average_score"],

            "skills_identified": updated_stats["skills_identified"],

            "created_at": analysis_time

        }), 200

    except Exception as e:

        print("Resume Analysis Error:", str(e))

        return jsonify({

            "error": "Resume analysis failed!",

            "details": str(e)

        }), 500


# ==========================================
# 10. DELETE ANALYSIS HISTORY
# ==========================================

@app.route("/delete-history/<int:history_id>", methods=["POST", "DELETE"])
@login_required
def delete_history(history_id):

    user_id = session.get("user_id")

    try:

        with sqlite3.connect(DATABASE) as conn:
            conn.execute(
                "DELETE FROM resume_history WHERE id = ? AND user_id = ?",
                (history_id, user_id)
            )

            conn.row_factory = sqlite3.Row
            remaining_count = conn.execute(
                "SELECT COUNT(*) AS total FROM resume_history WHERE user_id = ?",
                (user_id,)
            ).fetchone()["total"]

        stats = get_dashboard_statistics(user_id)

        return jsonify({
            "success": True,
            "message": "Analysis record deleted successfully!",
            "deleted_id": history_id,
            "total_resumes": stats["total_resumes"],
            "average_score": stats["average_score"],
            "skills_identified": stats["skills_identified"],
            "remaining_count": remaining_count
        }), 200

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "Failed to delete record: " + str(e)
        }), 500


@app.route("/clear-history", methods=["POST", "DELETE"])
@login_required
def clear_all_history():

    user_id = session.get("user_id")

    try:

        with sqlite3.connect(DATABASE) as conn:
            conn.execute(
                "DELETE FROM resume_history WHERE user_id = ?",
                (user_id,)
            )

        stats = get_dashboard_statistics(user_id)

        return jsonify({
            "success": True,
            "message": "All resume analysis history cleared!",
            "total_resumes": stats["total_resumes"],
            "average_score": stats["average_score"],
            "skills_identified": stats["skills_identified"],
            "remaining_count": 0
        }), 200

    except Exception as e:

        return jsonify({
            "success": False,
            "error": "Failed to clear history: " + str(e)
        }), 500


# ==========================================
# 11. FILE SIZE ERROR HANDLING
# ==========================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "error": "File size should not exceed 5 MB!"
    }), 413


# ==========================================
# 11. RUN APPLICATION
# ==========================================

if __name__ == "__main__":

    app.run(debug=True)
