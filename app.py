import os
import psycopg2
import requests # <--- Добавили библиотеку для запросов
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from argon2 import PasswordHasher

app = Flask(__name__)

# --- НАСТРОЙКИ ---
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key_for_dev')
DATABASE_URL = os.environ.get('DATABASE_URL')

# !!! ПРИДУМАЙТЕ СВОЮ УНИКАЛЬНУЮ ТЕМУ !!!
# Это как пароль. Только те, кто подписан на эту тему, получат уведомления.
# Используйте латинские буквы и цифры.
NTFY_TOPIC = 'myaapmess' 

# Сюда вставьте ссылку на ваш сайт на Render (чтобы при клике открывался чат)
# Например: 'https://my-chat.onrender.com'
SITE_URL = 'https://google.com' 

ph = PasswordHasher()

# --- ФУНКЦИЯ УВЕДОМЛЕНИЙ NTFY ---
def send_ntfy_notification(sender_name, message_text):
    """Отправляет пуш-уведомление через ntfy.sh (через JSON)"""
    try:
        requests.post(
            "https://ntfy.sh/",
            json={
                "topic": NTFY_TOPIC,  # Ваша секретная тема
                "message": message_text,
                "title": f"Новое от {sender_name}",
                "priority": 4,        # 4 = High priority
                "click": 'https://mysecondmes-2.onrender.com',
                "tags": ["message"]
            },
            timeout=1
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")

# --- БАЗА ДАННЫХ ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(sender_id) REFERENCES users(id)
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка БД: {e}")

if DATABASE_URL:
    init_db()

# --- МАРШРУТЫ PWA ---
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

# --- ГЛАВНЫЕ МАРШРУТЫ ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session.get('username'))

@app.route('/get_messages')
def get_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    after_id = request.args.get('after_id', 0)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT messages.id, users.username, messages.content, messages.timestamp, messages.sender_id
        FROM messages 
        JOIN users ON messages.sender_id = users.id 
        WHERE messages.id > %s
        ORDER BY messages.timestamp ASC
    ''', (after_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    messages = []
    for row in rows:
        messages.append({
            'id': row[0],
            'username': row[1],
            'content': row[2],
            'timestamp': row[3].strftime('%H:%M'),
            'is_mine': (row[4] == session['user_id'])
        })
    return jsonify(messages)

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    content = data.get('content')

    if content and content.strip():
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Сохраняем сообщение
        cursor.execute("INSERT INTO messages (sender_id, content) VALUES (%s, %s)", 
                       (session['user_id'], content))
        conn.commit()
        
        # 2. Получаем имя отправителя
        cursor.execute("SELECT username FROM users WHERE id = %s", (session['user_id'],))
        sender_name = cursor.fetchone()[0]
        
        # 3. Отправляем уведомление ВСЕМ подписчикам темы NTFY
        # В реальном приложении тут можно проверить, кому именно слать, но пока шлем всем
        send_ntfy_notification(sender_name, content)
        
        cursor.close()
        conn.close()
        return jsonify({'status': 'ok'})
    
    return jsonify({'status': 'error', 'message': 'Empty content'})

@app.route('/delete/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE id = %s AND sender_id = %s", 
                   (msg_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('index'))

# --- АВТОРИЗАЦИЯ ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = ph.hash(password)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", 
                           (username, password_hash))
            conn.commit()
            cursor.close()
            conn.close()
            flash('Регистрация успешна! Теперь войдите.')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Такой логин уже занят.')
        except Exception as e:
            flash(f'Ошибка: {e}')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and ph.verify(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            return redirect(url_for('index'))
        flash('Неверный логин или пароль')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
