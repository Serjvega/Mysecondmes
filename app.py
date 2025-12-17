import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, flash, session
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

app = Flask(__name__)
# В продакшене секретный ключ тоже лучше брать из переменных окружения,
# но для учебного примера оставим так или добавим fallback.
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_dev')

ph = PasswordHasher()

# Получаем ссылку на базу данных из переменной окружения
# Если переменной нет (например, локально), программа упадет с ошибкой — это нормально для продакшена
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """Создает подключение к PostgreSQL"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    """Создает таблицы, если их нет."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Создание таблицы users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    
    # Создание таблицы messages
    # В Postgres автоинкремент это SERIAL
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

# Инициализируем БД только если мы не просто импортируем файл, а запускаем его
# Но для Render удобнее вызывать это явно. В реальных проектах используют миграции.
# Мы вызовем это внутри if __name__ == '__main__' для локального теста,
# но на Render нам придется надеяться, что первый запрос создаст таблицы, 
# или вызвать это перед первым запросом.
try:
    if DATABASE_URL:
        init_db()
except Exception as e:
    print(f"Ошибка инициализации БД (возможно, еще не настроен URL): {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        content = request.form.get('content')
        if content and content.strip():
            conn = get_db_connection()
            cursor = conn.cursor()
            # ВАЖНО: В Postgres используем %s вместо ?
            cursor.execute("INSERT INTO messages (sender_id, content) VALUES (%s, %s)", 
                           (session['user_id'], content))
            conn.commit()
            cursor.close()
            conn.close()
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT messages.id, users.username, messages.content, messages.timestamp, messages.sender_id
        FROM messages 
        JOIN users ON messages.sender_id = users.id 
        ORDER BY messages.timestamp ASC
    ''')
    messages = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('index.html', username=session.get('username'), messages=messages)

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
    # Этот блок срабатывает только при локальном запуске python app.py
    # На Render будет работать gunicorn, который не использует этот блок
    app.run(debug=True)