from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, flash
import cv2
import sqlite3
import numpy as np
import base64
from deepface import DeepFace
from ultralytics import YOLO
import smtplib
import time
from email.message import EmailMessage
import os

app = Flask(__name__)
app.secret_key = "laharika_project_secure_key_123"

# ---------------- ML MODEL ----------------
model = YOLO("yolov8n.pt")
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
current_status = "AWAKE"

UPLOAD_FOLDER = "static/faces"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- EMAIL CONFIG ----------------
SENDER_EMAIL = "drowsinessdetection4@gmail.com"
SENDER_PASSWORD = "rjdz zxxo rosb oykf" # Ensure this is your 16-character App Password
last_email_time = 0

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            username TEXT,
            password TEXT,
            gender TEXT,
            dob TEXT,
            family_email TEXT,
            face_encoding BLOB,
            status TEXT DEFAULT 'waiting'
        )
    ''')
    conn.commit()
    conn.close()

# ---------------- VIDEO STREAM ----------------
def generate_frames():
    global current_status
    cap = cv2.VideoCapture(0)
    drowsy_counter = 0

    while True:
        success, frame = cap.read()
        if not success:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        results = model.predict(frame, conf=0.5, verbose=False)
        eyes_detected = False

        for r in results:
            for box in r.boxes:
                label = model.names[int(box.cls[0])]
                if label == "person":
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    roi_gray = gray[y1:y2, x1:x2]
                    eyes = eye_cascade.detectMultiScale(roi_gray, 1.3, 5)
                    if len(eyes) > 0:
                        eyes_detected = True
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

        if not eyes_detected:
            drowsy_counter += 1
        else:
            drowsy_counter = 0

        current_status = "DROWSY" if drowsy_counter > 15 else "AWAKE"

        ret, buffer = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# ---------------- EMAIL ALERT ----------------
def send_alert_email(recipient_list, lat, lon):
    for receiver in recipient_list:
        if not receiver: continue 
        
        msg = EmailMessage()
        msg['Subject'] = "🚨 EMERGENCY: Drowsiness Alert!"
        msg['From'] = SENDER_EMAIL
        msg['To'] = receiver

        map_link = f"https://www.google.com/maps?q={lat},{lon}"
        msg.add_alternative(f"""
        <h2>Critical Alert!</h2>
        <p>Drowsiness has been detected for the user.</p>
        <p><strong>Current Location:</strong> <a href="{map_link}">View on Google Maps</a></p>
        """, subtype='html')

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
                smtp.send_message(msg)
                print(f"Alert sent to {receiver}")
        except Exception as e:
            print(f"Error sending to {receiver}: {e}")

# ---------------- ROUTES ----------------

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/registration', methods=['GET', 'POST'])
def registration():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        gender = request.form['gender']
        dob = request.form['dob']
        family_email = request.form['family_email'] # New field from form

        file = request.files['image']
        file_path = os.path.join(UPLOAD_FOLDER, email + ".jpg")
        file.save(file_path)

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (email, username, password, gender, dob, family_email)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email, username, password, gender, dob, family_email))
        conn.commit()
        conn.close()

        return redirect(url_for('login'))

    return render_template('registration.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email=? AND password=?', (email, password))
        user = cursor.fetchone()
        conn.close()

        if user:
            status = user[7] # Column index shifted because of family_email
            if status == "Active":
                session['email'] = email
                session['user'] = user[1]
                flash("Login Successful", "success")
                return redirect(url_for('main_project'))
            elif status == "waiting":
                flash("Waiting for admin approval", "warning")
            else:
                flash("User blocked by admin", "danger")
        else:
            flash("Invalid Email or Password", "danger")

    return render_template('login.html')

@app.route('/face_login', methods=['POST'])
def face_login():
    data = request.get_json()
    email = data.get('email')
    image_data = data.get('image')

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email=?', (email,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"status": "fail", "message": "User not found"})

    status = user[7]
    if status == "waiting":
        return jsonify({"status": "fail", "message": "Waiting for admin approval"})
    if status == "Blocked":
        return jsonify({"status": "fail", "message": "User blocked by admin"})

    header, encoded = image_data.split(",", 1)
    img_bytes = base64.b64decode(encoded)

    login_path = f"static/temp_{email}.jpg"
    with open(login_path, "wb") as f:
        f.write(img_bytes)

    registered_path = f"static/faces/{email}.jpg"

    if not os.path.exists(registered_path):
        return jsonify({"status": "fail", "message": "No registered face found"})

    try:
        result = DeepFace.verify(
            img1_path=registered_path,
            img2_path=login_path,
            model_name="SFace",
            detector_backend="opencv",
            enforce_detection=True
        )

        if os.path.exists(login_path):
            os.remove(login_path)

        if result["verified"]:
            session['user'] = email
            session['email'] = email
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "fail", "message": "Face not matched"})

    except Exception as e:
        return jsonify({"status": "fail", "message": str(e)})

@app.route('/main_project')
def main_project():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/update_location', methods=['POST'])
def update_location():
    data = request.json
    session['lat'] = data.get('lat')
    session['lon'] = data.get('lon')
    return jsonify({"status": "updated"})

@app.route('/status')
def status():
    global last_email_time

    if current_status == "DROWSY" and (time.time() - last_email_time > 60):
        lat = session.get('lat')
        lon = session.get('lon')

        if lat and lon and 'email' in session:
            conn = sqlite3.connect('database.db')
            cursor = conn.cursor()
            cursor.execute("SELECT family_email FROM users WHERE email=?", (session['email'],))
            row = cursor.fetchone()
            conn.close()

            family_email = row[0] if row else None
            recipients = [session['email'], family_email]
            
            send_alert_email(recipients, lat, lon)
            last_email_time = time.time()

    return jsonify({"status": current_status})

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ---------------- ADMIN ----------------
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin':
            session['admin'] = True
            return redirect(url_for('admin'))
    return render_template('admin_login.html')

@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users')
    users = cursor.fetchall()
    conn.close()
    return render_template('admin.html', users=users)


@app.route('/toggle_status/<email>', methods=['POST'])
def toggle_status(email):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if user:
        curr = user[0].strip().lower()

        print("Before:", curr)

        if curr == "waiting":
            new_status = "Active"
        elif curr == "active":
            new_status = "Blocked"
        elif curr == "blocked":
            new_status = "Active"
        else:
            new_status = "Active"

        print("After:", new_status)

        cursor.execute(
            "UPDATE users SET status = ? WHERE email = ?",
            (new_status, email)
        )
        conn.commit()
        print("After STATUS : ",new_status)
        print("EMAIL : ",email)
    conn.close()
    return redirect(url_for('admin'))


@app.route('/delete_user/<email>', methods=['POST'])
def delete_user(email):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    conn.close()

    image_path = f"static/faces/{email}.jpg"
    if os.path.exists(image_path):
        os.remove(image_path)

    return redirect(url_for('admin'))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)