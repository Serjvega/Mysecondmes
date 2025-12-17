import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from argon2 import PasswordHasher

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_dev')

ph = PasswordHasher()
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

# ... (Функция init_db и ее вызов остаются без изменений, пропускаю для краткости) ...
# Если вы копируете весь файл, не забудьте оставить блок init_db, если он у вас там был. 
# Но на Render база уже создана, так что это не критично.

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # При первом входе просто отдаем пустую страницу с каркасом
    # Сообщения подгрузятся через JS мгновенно
    return render_template('index.html', username=session.get('username'), user_id=session.get('user_id'))

# --- НОВЫЙ МАРШРУТ: API ДЛЯ ПОЛУЧЕНИЯ СООБЩЕНИЙ ---
@app.route('/get_messages')
def get_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    # Получаем параметр after_id (какое последнее сообщение видел пользователь)
    after_id = request.args.get('after_id', 0)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Берем только те сообщения, которые новее, чем after_id
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

    # Превращаем данные из базы в список словарей (JSON)
    messages = []
    for row in rows:
        # row[3] - это datetime объект. Превращаем его в строку "ЧЧ:ММ"
        time_str = row[3].strftime('%H:%M')
        
        messages.append({
            'id': row[0],
            'username': row[1],
            'content': row[2],
            'timestamp': time_str,
            'sender_id': row[4],
            'is_mine': (row[4] == session['user_id']) # Флаг: мое ли это сообщение
        })

    return jsonify(messages)

# --- ОБНОВЛЕННЫЙ МАРШРУТ ОТПРАВКИ ---
@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() # Получаем данные от JS
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
    
    # Теперь при удалении мы просто возвращаемся на главную
    # (В идеале удаление тоже делать через JS, но пока оставим так)
    return redirect(url_for('index'))

# ... (Маршруты register, login, logout остаются старыми) ...
@app.route('/register', methods=['GET', 'POST'])
def register():
    # Вставьте сюда старый код регистрации
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_hash = ph.hash(password)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, password_hash))
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
    # Вставьте сюда старый код входа
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
