import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from argon2 import PasswordHasher

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
# Секретный ключ для сессий. В продакшене берется из настроек Render.
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key_for_dev')

# Ссылка на базу данных Neon.tech
DATABASE_URL = os.environ.get('DATABASE_URL')

ph = PasswordHasher()

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def get_db_connection():
    """Создает подключение к PostgreSQL"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    """Создает таблицы при первом запуске"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        
        # Таблица сообщений
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
        print("База данных успешно инициализирована.")
    except Exception as e:
        print(f"Ошибка при инициализации БД: {e}")

# Пытаемся создать таблицы при старте приложения (важно для Render)
if DATABASE_URL:
    init_db()

# --- PWA МАРШРУТЫ (обслуживание файлов манифеста и service worker) ---
@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')


# --- ОСНОВНЫЕ МАРШРУТЫ ---

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # Отдаем пустой шаблон, сообщения подгрузятся через JS
    return render_template('index.html', username=session.get('username'))

# API: Получение новых сообщений (JSON)
@app.route('/get_messages')
def get_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    after_id = request.args.get('after_id', 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Забираем сообщения, которые новее, чем after_id
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
        # row[3] - это объект datetime, форматируем его в строку "ЧЧ:ММ"
        time_str = row[3].strftime('%H:%M')
        
        messages.append({
            'id': row[0],
            'username': row[1],
            'content': row[2],
            'timestamp': time_str,
            'is_mine': (row[4] == session['user_id']) # True, если сообщение мое
        })

    return jsonify(messages)

# API: Отправка сообщения (JSON)
@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    content = data.get('content')

    if content and content.strip():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO messages (sender_id, content) VALUES (%s, %s)", 
                       (session['user_id'], content))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'ok'})
    
    return jsonify({'status': 'error', 'message': 'Empty content'})

# Удаление сообщения
@app.route('/delete/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Удаляем, только если сообщение принадлежит текущему пользователю
    cursor.execute("DELETE FROM messages WHERE id = %s AND sender_id = %s", 
                   (msg_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    
    # Редирект обратно на главную
    return redirect(url_for('index'))

# --- АВТОРИЗАЦИЯ И РЕГИСТРАЦИЯ ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Хэшируем пароль
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
