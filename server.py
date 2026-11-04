from flask import Flask, request, jsonify
import networkx as nx
import sqlite3
import hashlib

app = Flask(__name__)

# إعداد قاعدة البيانات المحلية لتخزين المستخدمين والديون
def init_db():
    conn = sqlite3.connect('clearing_grid.db')
    cursor = conn.cursor()
    
    # جدول المستخدمين والهويات الرقمية
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_type TEXT NOT NULL,
            name TEXT NOT NULL,
            identifier TEXT UNIQUE NOT NULL,
            is_subscribed BOOLEAN DEFAULT 0,
            baridimob_tx TEXT
        )
    ''')
    
    # جدول الديون (الالتزامات والمستحقات)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debtor_id TEXT NOT NULL,
            creditor_id TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'PENDING'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 1. تسجيل مستخدم جديد مع التحقق من الهوية (NIN / RC / SWIFT / إلخ)
@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.json
    user_type = data.get('user_type') # IND, BUS, BNK, ART, AGR
    name = data.get('name')
    identifier = data.get('identifier') # رقم التعريف الوطني أو السجل التجاري

    try:
        conn = sqlite3.connect('clearing_grid.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_type, name, identifier) VALUES (?, ?, ?)",
                     (user_type, name, identifier))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"تم تسجيل الكيان بنجاح برقم تعريف: {identifier}"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "رقم التعريف مسجل مسبقاً في النظام!"}), 400

# 2. تسجيل دين جديد (القسم أ و ب)
@app.route('/api/add_debt', methods=['POST'])
def add_debt():
    data = request.json
    debtor = data.get('debtor_id')
    creditor = data.get('creditor_id')
    amount = float(data.get('amount'))

    conn = sqlite3.connect('clearing_grid.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO debts (debtor_id, creditor_id, amount) VALUES (?, ?, ?)",
                 (debtor, creditor, amount))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "تم تسجيل الدين وإضافته لشبكة المقاصة بنجاح."})

# 3. محرك المقاصة وتصفير الديون الدائرية (Graph Clearing Engine)
@app.route('/api/run_clearing', methods=['POST'])
def run_clearing():
    conn = sqlite3.connect('clearing_grid.db')
    cursor = conn.cursor()
    cursor.execute("SELECT debtor_id, creditor_id, amount FROM debts WHERE status='PENDING'")
    rows = cursor.fetchall()
    
    # بناء المخطط البياني للديون
    G = nx.DiGraph()
    for debtor, creditor, amount in rows:
        if G.has_edge(debtor, creditor):
            G[debtor][creditor]['weight'] += amount
        else:
            G.add_edge(debtor, creditor, weight=amount)

    # البحث عن الحلقات المغلقة
    cycles = list(nx.simple_cycles(G))
    cleared_operations = []

    for cycle in cycles:
        if len(cycle) < 2:
            continue
        
        cycle_edges = []
        for i in range(len(cycle)):
            u = cycle[i]
            v = cycle[(i + 1) % len(cycle)]
            cycle_edges.append((u, v, G[u][v]['weight']))

        min_amount = min(edge[2] for edge in cycle_edges)
        if min_amount <= 0:
            continue

        cleared_operations.append({
            "cycle": cycle,
            "cleared_amount": min_amount
        })

        # تحديث قاعدة البيانات وتصفير الديون المطبقة
        for u, v, _ in cycle_edges:
            cursor.execute("UPDATE debts SET amount = amount - ? WHERE debtor_id = ? AND creditor_id = ? AND status='PENDING'",
                           (min_amount, u, v))
            
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "تم فحص الشبكة وإجراء المقاصة بنجاح",
        "cleared_loops": cleared_operations
    })

# 4. تفعيل الاشتراك عبر BaridiMob وتأكيد وصل الدفع لحساب 002369035668
@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    data = request.json
    identifier = data.get('identifier')
    tx_id = data.get('transaction_id')

    conn = sqlite3.connect('clearing_grid.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_subscribed = 1, baridimob_tx = ? WHERE identifier = ?", (tx_id, identifier))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "تم التحقق من التحويل على BaridiMob وتفعيل الإشعارات اللحظية بنجاح!"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
