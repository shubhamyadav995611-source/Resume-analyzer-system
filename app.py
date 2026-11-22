
import pdfplumber
from docx import Document
import sqlite3
import os
import uuid
import re
import json
import time
import secrets
import smtplib
import ssl
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from functools import wraps
from datetime import datetime
from urllib.parse import quote_plus
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename

# Helper to automatically load environment configuration (.env with fallback to .env.example)
def load_env_file():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base_dir, ".env")
    # If .env does not exist, fall back to .env.example
    if not os.path.exists(env_path):
        alt_path = os.path.join(base_dir, ".env.example")
        if os.path.exists(alt_path):
            env_path = alt_path

    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k:
                            os.environ[k] = v
        except Exception as e:
            print(f"[ENV WARNING] Could not load {env_path}: {e}")

load_env_file()

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                otp_code TEXT NOT NULL,
                purpose TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_otps ON email_otps(email, purpose, used);")

        # Migration: ensure user_id column exists
        try:
            conn.execute("ALTER TABLE resume_history ADD COLUMN user_id INTEGER;")
        except sqlite3.OperationalError:
            pass


# Initialize tables even when Flask is started using flask run.
init_db()


# ==========================================
# 2.1 AUTHENTICATION & EMAIL OTP HELPERS
# ==========================================

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "Resume Analyzer")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

def is_valid_email(email):
    """Strict RFC compliant email address format verification."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if len(email) > 254 or "@" not in email:
        return False
    parts = email.split("@")
    if len(parts) != 2:
        return False
    domain = parts[1]
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        return False
    tld = domain.split(".")[-1]
    if len(tld) < 2:
        return False
    return bool(EMAIL_REGEX.match(email))

def mask_email(email):
    """Mask email for privacy e.g. shubhamyadav995611@gmail.com -> s***1@gmail.com"""
    if not email or "@" not in email:
        return email or ""
    user_part, domain = email.strip().split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "***"
    else:
        masked_user = user_part[0] + "***" + user_part[-1]
    return f"{masked_user}@{domain}"

def generate_and_save_otp(email, purpose):
    """
    Generates a secure 6-digit OTP, stores it in email_otps table,
    and returns otp_code.
    """
    email = email.strip().lower()
    otp_code = f"{secrets.randbelow(900000) + 100000}"
    expires_at = int(time.time()) + 600  # 10 minutes expiry
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DATABASE) as conn:
        # Invalidate previous un-used OTPs for this email and purpose
        conn.execute("""
            UPDATE email_otps SET used = 1 
            WHERE email = ? AND purpose = ? AND used = 0
        """, (email, purpose))

        conn.execute("""
            INSERT INTO email_otps (email, otp_code, purpose, expires_at, used, created_at)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (email, otp_code, purpose, expires_at, created_at))

    return otp_code

def verify_otp_code(email, purpose, entered_otp):
    """
    Verifies that entered_otp matches the latest valid, unexpired, unused OTP.
    Returns (True, None) or (False, "Error message")
    """
    if not entered_otp or len(entered_otp.strip()) != 6:
        return False, "Please enter the complete 6-digit verification code."

    email = email.strip().lower()
    now = int(time.time())
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        record = conn.execute("""
            SELECT * FROM email_otps 
            WHERE email = ? AND purpose = ? AND used = 0 AND expires_at > ?
            ORDER BY id DESC LIMIT 1
        """, (email, purpose, now)).fetchone()

        if not record:
            return False, "OTP code has expired or is invalid. Please request a new code."

        if record["otp_code"] != entered_otp.strip():
            return False, "Incorrect OTP code. Please check and try again."

        # Mark OTP as used
        conn.execute("UPDATE email_otps SET used = 1 WHERE id = ?", (record["id"],))

    return True, None

def send_otp_email(recipient_email, otp_code, purpose="login"):
    """
    Sends a 6-digit OTP to the recipient email via Gmail SMTP.
    Returns (is_sent: bool, message: str)
    """
    load_env_file()

    purpose_titles = {
        "login": "Login Verification Code",
        "register": "Registration Verification Code",
        "reset_password": "Password Reset Code",
    }
    title = purpose_titles.get(purpose, "Verification Code")

    server_host = os.environ.get("SMTP_SERVER", "smtp.gmail.com").strip()
    server_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip()
    sender_name = os.environ.get("SMTP_FROM_NAME", "Resume Analyzer").strip()
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    if not smtp_user or not smtp_pass or "your_" in smtp_user.lower() or "your_" in smtp_pass.lower():
        print("[SMTP ERROR] SMTP credentials missing or incomplete in environment/.env.")
        return False, "SMTP credentials are not configured. Please add your Gmail address and 16-character App Password to .env."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{otp_code} is your {title} - Resume Analyzer"
        msg["From"] = f"{sender_name} <{smtp_user}>"
        msg["To"] = recipient_email

        text_content = (
            f"Hello,\n\n"
            f"Your Resume Analyzer {title.lower()} is: {otp_code}\n\n"
            f"This code will expire in 10 minutes. Please do not share it with anyone.\n\n"
            f"If you did not request this code, please ignore this email.\n\n"
            f"- Resume Analyzer Team"
        )

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>{title}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; margin: 0; padding: 30px 15px;">
          <div style="max-width: 520px; margin: 0 auto; background: #131b2e; border-radius: 16px; border: 1px solid #1f2d4d; padding: 36px 32px; color: #f1f5f9; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <div style="text-align: center; margin-bottom: 24px;">
              <span style="font-size: 26px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px;">Resume<span style="color: #7565f5;">Analyzer</span></span>
            </div>
            <div style="background: rgba(117, 101, 245, 0.1); border-left: 4px solid #7565f5; padding: 12px 16px; border-radius: 6px; margin-bottom: 20px;">
              <h2 style="font-size: 18px; margin: 0; color: #c4b5fd;">{title}</h2>
            </div>
            <p style="font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 16px;">
              Hello,<br>You requested verification for your account associated with <strong style="color: #e2e8f0;">{recipient_email}</strong>. Use the one-time code below to proceed:
            </p>
            <div style="background: #0d1424; border: 2px dashed #7565f5; border-radius: 12px; padding: 22px; text-align: center; margin: 28px 0;">
              <span style="font-size: 34px; font-weight: 800; letter-spacing: 9px; color: #a78bfa; font-family: monospace;">{otp_code}</span>
            </div>
            <p style="font-size: 13px; color: #cbd5e1; margin-bottom: 8px;">
              &#9203; This code is valid for <strong>10 minutes</strong>.
            </p>
            <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-bottom: 24px;">
              Security Notice: Never share this OTP with anyone. If you didn't request this verification code, please ignore this email or change your account password.
            </p>
            <div style="border-top: 1px solid #1e293b; padding-top: 18px; font-size: 11px; color: #475569; text-align: center;">
              &copy; 2026 Resume Analyzer &bull; AI Powered Resume & ATS Optimization
            </div>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(server_host, server_port, timeout=15) as server:
            if use_tls:
                server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            refused = server.sendmail(smtp_user, recipient_email, msg.as_string())

            if refused:
                refused_details = refused.get(recipient_email, next(iter(refused.values())))
                code, resp_text = refused_details if isinstance(refused_details, tuple) and len(refused_details) == 2 else (None, str(refused_details))
                print(f"[SMTP ERROR] Recipient rejected by server ({recipient_email}): code {code} - {resp_text}")
                return False, f"Email delivery was rejected for {recipient_email} (code {code})."

        print("[SMTP SUCCESS] Email sent successfully")
        return True, "Email sent successfully"

    except smtplib.SMTPAuthenticationError as e:
        print(f"[SMTP ERROR] Authentication failed: {e.smtp_code} - {e.smtp_error}")
        return False, "Gmail SMTP authentication failed. Please check your Gmail address and 16-character App Password."
    except smtplib.SMTPRecipientsRefused as e:
        print(f"[SMTP ERROR] All recipients refused: {e.recipients}")
        return False, "Recipient email was rejected by the mail server."
    except smtplib.SMTPSenderRefused as e:
        print(f"[SMTP ERROR] Sender refused: {e.smtp_code} - {e.smtp_error}")
        return False, "Sender address was refused by the mail server."
    except smtplib.SMTPDataError as e:
        print(f"[SMTP ERROR] SMTP data error: {e.smtp_code} - {e.smtp_error}")
        return False, f"Mail server data error (code {e.smtp_code})."
    except smtplib.SMTPConnectError as e:
        print(f"[SMTP ERROR] Connection error: {e.smtp_code} - {e.smtp_error}")
        return False, f"Could not connect to SMTP server ({server_host}:{server_port})."
    except smtplib.SMTPServerDisconnected as e:
        print(f"[SMTP ERROR] Server disconnected unexpectedly: {e}")
        return False, "SMTP server disconnected unexpectedly."
    except smtplib.SMTPHeloError as e:
        print(f"[SMTP ERROR] Handshake rejected: {e.smtp_code} - {e.smtp_error}")
        return False, "SMTP handshake rejected."
    except (TimeoutError, socket.timeout) as e:
        print(f"[SMTP ERROR] Connection timed out: {e}")
        return False, "Connection to SMTP server timed out. Please check your network."
    except smtplib.SMTPException as e:
        print(f"[SMTP ERROR] SMTP exception: {type(e).__name__} - {e}")
        return False, f"SMTP error: {e}"
    except Exception as e:
        print(f"[SMTP ERROR] Unexpected error: {type(e).__name__} - {e}")
        return False, f"Unexpected error while sending email: {e}"

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
    success_message = request.args.get("message")

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "Student").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:
            error_message = "Please fill all required fields."
        elif not is_valid_email(email):
            error_message = "Please enter a valid email address (e.g., name@example.com)."
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
                    otp = generate_and_save_otp(email, "register")
                    sent, msg = send_otp_email(email, otp, "register")

                    if not sent:
                        error_message = f"Failed to send verification email: {msg}"
                    else:
                        pwd_hash = generate_password_hash(password)
                        session["pending_auth"] = {
                            "purpose": "register",
                            "name": name,
                            "email": email,
                            "role": role,
                            "password_hash": pwd_hash
                        }
                        return redirect(url_for("verify_otp", message=f"A 6-digit verification code has been sent to {email}. Please enter it below to complete registration."))

    return render_template(
        "register.html",
        error_message=error_message,
        success_message=success_message
    )


@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session and get_current_user():
        return redirect(url_for("dashboard"))

    error_message = None
    success_message = request.args.get("message")
    info_message = request.args.get("info")

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        login_type = request.form.get("login_type", "password_otp")

        if not email:
            error_message = "Please enter your email address."
        elif not is_valid_email(email):
            error_message = "Please enter a valid email address (e.g., name@example.com)."
        else:
            with sqlite3.connect(DATABASE) as conn:
                conn.row_factory = sqlite3.Row
                user = conn.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

            if not user:
                error_message = "No account found with this email. Please check your email or register."
            else:
                if login_type == "password_otp":
                    if not password:
                        error_message = "Please enter your password."
                    elif not check_password_hash(user["password_hash"], password):
                        error_message = "Invalid password. Please try again or use Forgot Password."

                if not error_message:
                    # Credentials verified, send real 2FA OTP to registered email
                    otp = generate_and_save_otp(email, "login")
                    sent, msg = send_otp_email(email, otp, "login")

                    if not sent:
                        error_message = f"Failed to send login verification code: {msg}"
                    else:
                        session["pending_auth"] = {
                            "purpose": "login",
                            "user_id": user["id"],
                            "name": user["name"],
                            "email": user["email"],
                            "role": user["role"]
                        }
                        return redirect(url_for("verify_otp", message=f"Verification code sent to {email}. Enter the 6-digit OTP to continue."))

    return render_template(
        "login.html",
        error_message=error_message,
        success_message=success_message,
        info_message=info_message
    )


@app.route("/login-otp", methods=["POST"])
def login_with_otp_request():

    if "user_id" in session and get_current_user():
        return redirect(url_for("dashboard"))

    email = request.form.get("email", "").strip().lower()

    if not email:
        return render_template("login.html", error_message="Please enter your email address.")

    if not is_valid_email(email):
        return render_template("login.html", error_message="Please enter a valid email address.", email=email)

    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if not user:
        return render_template("login.html", error_message="No account found with this email. Please check your email or register.", email=email)

    otp = generate_and_save_otp(email, "login")
    sent, msg = send_otp_email(email, otp, "login")

    if not sent:
        return render_template("login.html", error_message=f"Failed to send OTP code: {msg}", email=email)

    session["pending_auth"] = {
        "purpose": "login",
        "user_id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"]
    }

    return redirect(url_for("verify_otp", message=f"A 6-digit login verification code has been sent to {email}."))


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():

    pending = session.get("pending_auth")
    if not pending or not pending.get("email"):
        return redirect(url_for("login"))

    email = pending["email"]
    purpose = pending.get("purpose", "login")
    masked = mask_email(email)

    error_message = request.args.get("error")
    success_message = request.args.get("message")

    if request.method == "POST":
        entered_otp = request.form.get("otp", "").strip()

        is_valid, err_msg = verify_otp_code(email, purpose, entered_otp)
        if not is_valid:
            error_message = err_msg
        else:
            if purpose == "register":
                created_at = datetime.now().strftime("%d %b %Y")
                with sqlite3.connect(DATABASE) as conn:
                    cursor = conn.execute("""
                        INSERT INTO users (name, email, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        pending["name"],
                        pending["email"],
                        pending["password_hash"],
                        pending.get("role", "Student"),
                        created_at
                    ))
                    new_user_id = cursor.lastrowid
                    conn.execute(
                        "UPDATE resume_history SET user_id = ? WHERE user_id IS NULL",
                        (new_user_id,)
                    )

                session["user_id"] = new_user_id
                session["user_name"] = pending["name"]
                session["user_email"] = pending["email"]
                session["user_role"] = pending.get("role", "Student")

            elif purpose == "login":
                user_id = pending["user_id"]
                with sqlite3.connect(DATABASE) as conn:
                    conn.execute(
                        "UPDATE resume_history SET user_id = ? WHERE user_id IS NULL",
                        (user_id,)
                    )

                session["user_id"] = user_id
                session["user_name"] = pending["name"]
                session["user_email"] = pending["email"]
                session["user_role"] = pending["role"]

            session.pop("pending_auth", None)
            return redirect(url_for("dashboard"))

    return render_template(
        "verify_otp.html",
        masked_email=masked,
        email=email,
        purpose=purpose,
        error_message=error_message,
        success_message=success_message
    )


@app.route("/resend-otp", methods=["POST"])
def resend_otp():

    pending = session.get("pending_auth")
    if not pending or not pending.get("email"):
        return redirect(url_for("login"))

    email = pending["email"]
    purpose = pending.get("purpose", "login")

    otp = generate_and_save_otp(email, purpose)
    sent, msg = send_otp_email(email, otp, purpose)

    if not sent:
        return redirect(url_for("verify_otp", error=f"Failed to resend code: {msg}"))

    return redirect(url_for("verify_otp", message="A fresh 6-digit verification code has been sent to your email."))


@app.route("/cancel-auth")
def cancel_auth():

    session.pop("pending_auth", None)
    return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if "user_id" in session and get_current_user():
        return redirect(url_for("dashboard"))

    error_message = None
    success_message = request.args.get("message")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            error_message = "Please enter your registered email address."
        elif not is_valid_email(email):
            error_message = "Please enter a valid email address (e.g., name@example.com)."
        else:
            with sqlite3.connect(DATABASE) as conn:
                conn.row_factory = sqlite3.Row
                user = conn.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

            if not user:
                error_message = "No account found with this email. Please check your email or create a new account."
            else:
                otp = generate_and_save_otp(email, "reset_password")
                sent, msg = send_otp_email(email, otp, "reset_password")

                if not sent:
                    error_message = f"Failed to send reset code: {msg}"
                else:
                    session["pending_reset_email"] = email
                    return redirect(url_for("reset_password", message="Password reset code has been sent to your registered email."))

    return render_template(
        "forgot_password.html",
        error_message=error_message,
        success_message=success_message
    )


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    email = session.get("pending_reset_email")
    if not email:
        return redirect(url_for("forgot_password"))

    masked = mask_email(email)
    error_message = request.args.get("error")
    success_message = request.args.get("message")

    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        new_pwd = request.form.get("new_password", "")
        confirm_pwd = request.form.get("confirm_password", "")

        if not otp or not new_pwd or not confirm_pwd:
            error_message = "Please fill all required fields."
        elif len(new_pwd) < 6:
            error_message = "New password must be at least 6 characters long."
        elif new_pwd != confirm_pwd:
            error_message = "New password and Confirm password do not match."
        else:
            is_valid, err_msg = verify_otp_code(email, "reset_password", otp)
            if not is_valid:
                error_message = err_msg
            else:
                new_hash = generate_password_hash(new_pwd)
                with sqlite3.connect(DATABASE) as conn:
                    conn.execute(
                        "UPDATE users SET password_hash = ? WHERE email = ?",
                        (new_hash, email)
                    )

                session.pop("pending_reset_email", None)

                return redirect(url_for(
                    "login",
                    message="Password reset successfully! You can now log in with your new password."
                ))

    return render_template(
        "reset_password.html",
        masked_email=masked,
        email=email,
        error_message=error_message,
        success_message=success_message
    )


@app.route("/resend-reset-otp", methods=["POST"])
def resend_reset_otp():

    email = session.get("pending_reset_email")
    if not email:
        return redirect(url_for("forgot_password"))

    otp = generate_and_save_otp(email, "reset_password")
    sent, msg = send_otp_email(email, otp, "reset_password")

    if not sent:
        return redirect(url_for("reset_password", error=f"Failed to resend reset code: {msg}"))

    return redirect(url_for("reset_password", message="A fresh reset code has been sent to your email."))


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
