from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import sqlite3
from datetime import datetime, date
import os, calendar, hashlib, secrets, re
from functools import wraps

app = Flask(__name__)
app.secret_key = 'finance_app_secret_key_2026_xK9#mP'
DB_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

INCOME_CATEGORIES = ['Μισθός', 'Revolut / Άλλες Τράπεζες', 'Άλλα έσοδα']

EXPENSE_TREE = {
    'Σπίτι & Λογαριασμοί':          ['Ενοίκιο','Κοινόχρηστα','Ηλεκτρικό Ρεύμα','Ύδρευση','Internet / Τηλέφωνο'],
    'Σούπερ Μάρκετ':                 ['Τρόφιμα','Καθαριστικά','Είδη Παντοπωλείου'],
    'Φαγητό & Καφέδες Έξω':         ['Delivery / Takeaway','Φούρνος','Καφέδες','Εστιατόρια'],
    'Μετακινήσεις & Όχημα':         ['Βενζίνη','Service','Ασφάλεια','Τέλη Κυκλοφορίας','Διόδια / Εισιτήρια'],
    'Διασκέδαση & Ταξίδια':         ['Ποτό / Σινεμά','Ταξίδια / Διακοπές','Δώρα'],
    'Αγορές & Προσωπική Φροντίδα':  ['Ρούχα / Παπούτσια','Κουρείο / Κομμωτήριο','Είδη Υγιεινής'],
    'Υγεία & Φαρμακείο':            ['Γιατροί','Εξετάσεις','Φάρμακα'],
    'Εκπαίδευση & Πανεπιστήμιο':   ['Βιβλία','Φωτοτυπίες','Δίδακτρα / Σεμινάρια'],
    'Συνδρομές & Gym':              ['Netflix / Spotify','Γυμναστήριο','Cloud Storage'],
    'Κατοικίδια':                    ['Τροφή κατοικιδίου','Κτηνίατρος'],
    'Τραπεζικά & Revolut':          ['Προμήθειες','Έξοδα Εμβασμάτων'],
    'Αποταμίευση & Επενδύσεις':    ['Moneybox','Μετοχές / Crypto','Κουμπαράς'],
    'Διάφορα / Έκτακτα':            ['Έκτακτο Έξοδο','Άλλο'],
}

CAT_COLORS = {
    'Σπίτι & Λογαριασμοί':'#4A90D9',
    'Σούπερ Μάρκετ':'#27AE60',
    'Φαγητό & Καφέδες Έξω':'#E74C3C',
    'Μετακινήσεις & Όχημα':'#E67E22',
    'Διασκέδαση & Ταξίδια':'#9B59B6',
    'Αγορές & Προσωπική Φροντίδα':'#F06292',
    'Υγεία & Φαρμακείο':'#E91E63',
    'Εκπαίδευση & Πανεπιστήμιο':'#1ABC9C',
    'Συνδρομές & Gym':'#3498DB',
    'Κατοικίδια':'#8D6E63',
    'Τραπεζικά & Revolut':'#1A5276',
    'Αποταμίευση & Επενδύσεις':'#2ECC71',
    'Διάφορα / Έκτακτα':'#95A5A6',
}

GREEK_MONTHS = {
    1:'Ιανουάριος',2:'Φεβρουάριος',3:'Μάρτιος',4:'Απρίλιος',
    5:'Μάιος',6:'Ιούνιος',7:'Ιούλιος',8:'Αύγουστος',
    9:'Σεπτέμβριος',10:'Οκτώβριος',11:'Νοέμβριος',12:'Δεκέμβριος'
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS months (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_closed INTEGER DEFAULT 0,
        closed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, year, month),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        subcategory TEXT,
        type TEXT NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        transaction_date TEXT NOT NULL,
        late_entry INTEGER DEFAULT 0,
        late_entry_note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(month_id) REFERENCES months(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        amount REAL DEFAULT 0,
        UNIQUE(user_id, category),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS fixed_expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        amount REAL DEFAULT 0,
        category TEXT,
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS fixed_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixed_expense_id INTEGER NOT NULL,
        month_id INTEGER NOT NULL,
        paid INTEGER DEFAULT 0,
        paid_at TEXT,
        UNIQUE(fixed_expense_id, month_id)
    )''')
    for tbl,col,defn in [('transactions','subcategory','TEXT'),
                          ('transactions','late_entry','INTEGER DEFAULT 0'),
                          ('transactions','late_entry_note','TEXT')]:
        try: c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {defn}")
        except: pass
    conn.commit()
    conn.close()

def hash_password(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200000).hex()

def validate_password(pw):
    return (len(pw)>=8 and re.search(r'[A-Z]',pw) and
            re.search(r'[0-9]',pw) and re.search(r'[^A-Za-z0-9]',pw))

def validate_username(u):
    return 8<=len(u)<=12 and bool(re.match(r'^[A-Za-z0-9_]+$',u))

def current_user_id():
    return session.get('user_id')

def login_required(f):
    @wraps(f)
    def dec(*a,**k):
        if not current_user_id():
            return redirect(url_for('login'))
        return f(*a,**k)
    return dec

def get_month_stats(month_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE month_id=? AND type='income'",(month_id,))
    ti = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE month_id=? AND type='expense'",(month_id,))
    te = c.fetchone()[0]
    c.execute("""SELECT category, SUM(amount) as total FROM transactions
                 WHERE month_id=? AND type='expense' GROUP BY category ORDER BY total DESC LIMIT 1""",(month_id,))
    top = c.fetchone()
    conn.close()
    return {'total_income':round(ti,2),'total_expense':round(te,2),'balance':round(ti-te,2),
            'top_expense_category':top['category'] if top else None,
            'top_expense_amount':round(top['total'],2) if top else 0}

def can_edit_closed_month(m):
    if not m['is_closed']: return True
    if not m['closed_at']: return False
    return (date.today()-datetime.fromisoformat(m['closed_at']).date()).days<=5

def auto_close_expired_months(uid):
    now = datetime.now()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM months WHERE is_closed=0 AND user_id=?",(uid,))
    for m in c.fetchall():
        ld = calendar.monthrange(m['year'],m['month'])[1]
        if now > datetime(m['year'],m['month'],ld,23,59,59):
            c.execute("UPDATE months SET is_closed=1,closed_at=? WHERE id=?",
                      (datetime(m['year'],m['month'],ld,23,59,59).isoformat(),m['id']))
    conn.commit()
    conn.close()

def check_new_month_needed(uid):
    today=date.today()
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT id FROM months WHERE user_id=? AND year=? AND month=?",(uid,today.year,today.month))
    ex=c.fetchone()
    c.execute("SELECT COUNT(*) FROM months WHERE user_id=? AND is_closed=1",(uid,))
    hc=c.fetchone()[0]>0
    conn.close()
    return (not ex) and hc

def build_alerts(expense_by_cat, budgets, stats):
    alerts=[]
    for row in expense_by_cat:
        cat=row['category']
        if cat in budgets and budgets[cat]>0:
            spent,limit=row['total'],budgets[cat]
            pct=(spent/limit)*100
            if pct>=100:
                alerts.append({'level':'danger','msg':f"🚨 Υπέρβαση budget '{cat}': {spent:.2f}€ / {limit:.2f}€ ({pct:.0f}%)"})
            elif pct>=90:
                alerts.append({'level':'warning','msg':f"⚠️ Σχεδόν στο όριο '{cat}': {spent:.2f}€ / {limit:.2f}€ ({pct:.0f}%)"})
            elif pct>=75:
                alerts.append({'level':'info','msg':f"📊 75%+ budget '{cat}': {spent:.2f}€ / {limit:.2f}€ ({pct:.0f}%)"})
    if stats['total_income']>0:
        bp=(stats['total_expense']/stats['total_income'])*100
        if bp>=100:
            alerts.append({'level':'danger','msg':f"🚨 Τα έξοδα ξεπέρασαν τα έσοδα! ({stats['total_expense']:.2f}€ > {stats['total_income']:.2f}€)"})
        elif bp>=90:
            rem=stats['total_income']-stats['total_expense']
            alerts.append({'level':'warning','msg':f"⚠️ {bp:.0f}% των εσόδων χρησιμοποιήθηκε — απομένουν {rem:.2f}€"})
    return alerts

# ─── Auth routes ───────────────────────────────────────────────
@app.route('/login',methods=['GET','POST'])
def login():
    if current_user_id(): return redirect(url_for('index'))
    error=None
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        conn=get_db(); c=conn.cursor()
        c.execute("SELECT * FROM users WHERE username=?",(username,))
        user=c.fetchone(); conn.close()
        if user and hash_password(password,user['salt'])==user['password_hash']:
            session['user_id']=user['id']; session['username']=user['username']
            return redirect(url_for('index'))
        error='Λάθος όνομα χρήστη ή κωδικός.'
    return render_template('login.html',error=error)

@app.route('/register',methods=['GET','POST'])
def register():
    if current_user_id(): return redirect(url_for('index'))
    errors=[]
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        confirm=request.form.get('confirm','')
        if not validate_username(username): errors.append('Username: 8–12 χαρακτήρες (γράμματα, αριθμοί, _).')
        if not validate_password(password): errors.append('Κωδικός: 8+, κεφαλαίο, αριθμό, σύμβολο.')
        if password!=confirm: errors.append('Οι κωδικοί δεν ταιριάζουν.')
        if not errors:
            salt=secrets.token_hex(16)
            conn=get_db(); c=conn.cursor()
            try:
                c.execute("INSERT INTO users (username,password_hash,salt) VALUES (?,?,?)",
                          (username,hash_password(password,salt),salt))
                conn.commit(); uid=c.lastrowid; conn.close()
                session['user_id']=uid; session['username']=username
                return redirect(url_for('index'))
            except sqlite3.IntegrityError:
                conn.close(); errors.append('Το username χρησιμοποιείται ήδη.')
    return render_template('register.html',errors=errors)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

# ─── Main routes ───────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    uid=current_user_id()
    auto_close_expired_months(uid)
    suggest=check_new_month_needed(uid)
    today=date.today()
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year DESC,month DESC",(uid,))
    months=c.fetchall(); conn.close()
    current_month=next((m for m in months if m['year']==today.year and m['month']==today.month),None)
    return render_template('index.html',months=months,current_month=current_month,
        greek_months=GREEK_MONTHS,today=today,all_months=months,
        suggest_new_month=suggest,next_month=today.month,next_year=today.year,
        now=datetime.now(),username=session.get('username'))

@app.route('/new_month',methods=['POST'])
@login_required
def new_month():
    uid=current_user_id(); data=request.json
    year=int(data.get('year',date.today().year))
    month=int(data.get('month',date.today().month))
    name=f"{GREEK_MONTHS[month]} {year}"
    conn=get_db(); c=conn.cursor()
    try:
        c.execute("INSERT INTO months (user_id,year,month,name) VALUES (?,?,?,?)",(uid,year,month,name))
        conn.commit(); mid=c.lastrowid; conn.close()
        return jsonify({'success':True,'month_id':mid,'name':name})
    except sqlite3.IntegrityError:
        c.execute("SELECT id FROM months WHERE user_id=? AND year=? AND month=?",(uid,year,month))
        ex=c.fetchone(); conn.close()
        if ex: return jsonify({'success':False,'error':'Ο μήνας υπάρχει ήδη','month_id':ex['id']})
        return jsonify({'success':False,'error':'Σφάλμα'})

@app.route('/delete_month/<int:mid>',methods=['DELETE'])
@login_required
def delete_month(mid):
    uid=current_user_id(); conn=get_db(); c=conn.cursor()
    c.execute("SELECT id FROM months WHERE id=? AND user_id=?",(mid,uid))
    if not c.fetchone(): conn.close(); return jsonify({'success':False})
    c.execute("DELETE FROM fixed_payments WHERE month_id=?",(mid,))
    c.execute("DELETE FROM transactions WHERE month_id=?",(mid,))
    c.execute("DELETE FROM months WHERE id=?",(mid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/month/<int:month_id>')
@login_required
def month_detail(month_id):
    uid=current_user_id()
    auto_close_expired_months(uid)
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM months WHERE id=? AND user_id=?",(month_id,uid))
    month=c.fetchone()
    if not month: conn.close(); return redirect(url_for('index'))
    c.execute("SELECT * FROM transactions WHERE month_id=? ORDER BY transaction_date DESC,id DESC",(month_id,))
    transactions=c.fetchall()
    c.execute("SELECT * FROM budgets WHERE user_id=?",(uid,))
    budgets={b['category']:b['amount'] for b in c.fetchall()}
    c.execute("""SELECT category,SUM(amount) as total FROM transactions
                 WHERE month_id=? AND type='expense' GROUP BY category ORDER BY total DESC""",(month_id,))
    expense_by_cat=c.fetchall()
    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year DESC,month DESC",(uid,))
    all_months=c.fetchall()
    c.execute("SELECT * FROM months WHERE user_id=? AND is_closed=1 ORDER BY year DESC,month DESC LIMIT 6",(uid,))
    closed_months=c.fetchall()
    # Fixed expenses + payment status for this month
    c.execute("SELECT * FROM fixed_expenses WHERE user_id=? ORDER BY sort_order,id",(uid,))
    fixed_expenses=c.fetchall()
    fixed_status={}
    for fe in fixed_expenses:
        c.execute("SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?",(fe['id'],month_id))
        fp=c.fetchone()
        fixed_status[fe['id']]={'paid':bool(fp and fp['paid']),'paid_at':fp['paid_at'] if fp else None}
    conn.close()
    stats=get_month_stats(month_id)
    alerts=build_alerts(expense_by_cat,budgets,stats)
    editable=can_edit_closed_month(month)
    days_since_close=None
    if month['is_closed'] and month['closed_at']:
        days_since_close=(date.today()-datetime.fromisoformat(month['closed_at']).date()).days
    return render_template('month.html',
        month=month,transactions=transactions,stats=stats,
        income_categories=INCOME_CATEGORIES,expense_tree=EXPENSE_TREE,cat_colors=CAT_COLORS,
        expense_by_cat=expense_by_cat,budgets=budgets,alerts=alerts,
        all_months=all_months,closed_months=closed_months,
        fixed_expenses=fixed_expenses,fixed_status=fixed_status,
        greek_months=GREEK_MONTHS,editable=editable,days_since_close=days_since_close,
        now=datetime.now(),username=session.get('username'))

@app.route('/add_transaction',methods=['POST'])
@login_required
def add_transaction():
    uid=current_user_id(); data=request.json
    month_id=data['month_id']
    conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM months WHERE id=? AND user_id=?",(month_id,uid))
    month=c.fetchone()
    if not month: conn.close(); return jsonify({'success':False,'error':'Δεν βρέθηκε'})
    late=int(data.get('late_entry',0))
    if month['is_closed'] and not can_edit_closed_month(month) and not late:
        conn.close(); return jsonify({'success':False,'error':'Μη επεξεργάσιμος μήνας'})
    c.execute("""INSERT INTO transactions
                 (month_id,category,subcategory,type,amount,description,transaction_date,late_entry,late_entry_note)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
              (month_id,data['category'],data.get('subcategory',''),data['type'],
               float(data['amount']),data.get('description',''),
               data.get('date',date.today().isoformat()),late,data.get('late_entry_note','')))
    conn.commit(); tid=c.lastrowid; conn.close()
    return jsonify({'success':True,'id':tid})

@app.route('/delete_transaction/<int:tid>',methods=['DELETE'])
@login_required
def delete_transaction(tid):
    conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM transactions WHERE id=?",(tid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/edit_transaction/<int:tid>',methods=['PUT'])
@login_required
def edit_transaction(tid):
    data=request.json; conn=get_db(); c=conn.cursor()
    c.execute("""UPDATE transactions SET category=?,subcategory=?,type=?,amount=?,description=?,transaction_date=?
                 WHERE id=?""",
              (data['category'],data.get('subcategory',''),data['type'],float(data['amount']),
               data.get('description',''),data['date'],tid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/close_month/<int:mid>',methods=['POST'])
@login_required
def close_month(mid):
    conn=get_db(); c=conn.cursor()
    c.execute("UPDATE months SET is_closed=1,closed_at=? WHERE id=?",
              (datetime.now().isoformat(),mid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/set_budget',methods=['POST'])
@login_required
def set_budget():
    uid=current_user_id(); data=request.json; conn=get_db(); c=conn.cursor()
    c.execute("INSERT OR REPLACE INTO budgets (user_id,category,amount) VALUES (?,?,?)",
              (uid,data['category'],float(data['amount'])))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── Fixed expenses CRUD ───────────────────────────────────────
@app.route('/fixed_expenses',methods=['GET'])
@login_required
def get_fixed_expenses():
    uid=current_user_id(); conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM fixed_expenses WHERE user_id=? ORDER BY sort_order,id",(uid,))
    rows=[dict(r) for r in c.fetchall()]; conn.close()
    return jsonify(rows)

@app.route('/fixed_expenses',methods=['POST'])
@login_required
def add_fixed_expense():
    uid=current_user_id(); data=request.json; conn=get_db(); c=conn.cursor()
    c.execute("INSERT INTO fixed_expenses (user_id,label,amount,category) VALUES (?,?,?,?)",
              (uid,data['label'],float(data.get('amount',0)),data.get('category','')))
    conn.commit(); fid=c.lastrowid; conn.close()
    return jsonify({'success':True,'id':fid})

@app.route('/fixed_expenses/<int:fid>',methods=['DELETE'])
@login_required
def delete_fixed_expense(fid):
    uid=current_user_id(); conn=get_db(); c=conn.cursor()
    c.execute("DELETE FROM fixed_payments WHERE fixed_expense_id=?",(fid,))
    c.execute("DELETE FROM fixed_expenses WHERE id=? AND user_id=?",(fid,uid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/fixed_payment',methods=['POST'])
@login_required
def toggle_fixed_payment():
    uid = current_user_id()
    data = request.json
    fid  = data['fixed_expense_id']
    mid  = data['month_id']
    paid = int(data.get('paid', 1))

    conn = get_db()
    c = conn.cursor()

    # Get the fixed expense details
    c.execute("SELECT * FROM fixed_expenses WHERE id=? AND user_id=?", (fid, uid))
    fe = c.fetchone()
    if not fe:
        conn.close()
        return jsonify({'success': False, 'error': 'Δεν βρέθηκε'})

    # Check existing payment record
    c.execute("SELECT * FROM fixed_payments WHERE fixed_expense_id=? AND month_id=?", (fid, mid))
    existing = c.fetchone()

    if paid and fe['amount'] and fe['amount'] > 0:
        # Auto-add transaction if amount is set and marking as paid
        cat = fe['category'] if fe['category'] else 'Διάφορα / Έκτακτα'
        c.execute("""INSERT INTO transactions
                     (month_id, category, subcategory, type, amount, description, transaction_date)
                     VALUES (?,?,?,?,?,?,?)""",
                  (mid, cat, '', 'expense', fe['amount'],
                   f"[Σταθερό] {fe['label']}", date.today().isoformat()))

    elif not paid and existing and fe['amount'] and fe['amount'] > 0:
        # Remove auto-added transaction when un-marking
        c.execute("""DELETE FROM transactions
                     WHERE month_id=? AND description=? AND amount=? AND type='expense'""",
                  (mid, f"[Σταθερό] {fe['label']}", fe['amount']))

    # Upsert payment status
    c.execute("""INSERT INTO fixed_payments (fixed_expense_id, month_id, paid, paid_at)
                 VALUES (?,?,?,?)
                 ON CONFLICT(fixed_expense_id, month_id)
                 DO UPDATE SET paid=excluded.paid, paid_at=excluded.paid_at""",
              (fid, mid, paid, datetime.now().isoformat() if paid else None))

    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/month_stats/<int:mid>')
@login_required
def api_month_stats(mid):
    return jsonify(get_month_stats(mid))

@app.route('/api/now')
def api_now():
    now=datetime.now()
    return jsonify({'time':now.strftime('%H:%M:%S'),'month':GREEK_MONTHS[now.month]})

@app.route('/analytics')
@login_required
def analytics():
    uid=current_user_id(); conn=get_db(); c=conn.cursor()
    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year,month",(uid,))
    months=c.fetchall()
    analytics_data=[{**dict(m),**get_month_stats(m['id'])} for m in months]
    c.execute("SELECT COALESCE(SUM(t.amount),0) FROM transactions t JOIN months m ON t.month_id=m.id WHERE m.user_id=? AND t.type='income'",(uid,))
    total_income=c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(t.amount),0) FROM transactions t JOIN months m ON t.month_id=m.id WHERE m.user_id=? AND t.type='expense'",(uid,))
    total_expense=c.fetchone()[0]
    c.execute("""SELECT t.category,SUM(t.amount) as total FROM transactions t
                 JOIN months m ON t.month_id=m.id WHERE m.user_id=? AND t.type='expense'
                 GROUP BY t.category ORDER BY total DESC LIMIT 5""",(uid,))
    top_cats=c.fetchall()
    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year DESC,month DESC",(uid,))
    all_months=c.fetchall(); conn.close()
    suggestions=[]
    if top_cats: suggestions.append(f"Ξοδεύεις πιο πολύ σε '{top_cats[0]['category']}' ({top_cats[0]['total']:.2f}€)")
    if len(analytics_data)>=2:
        last,prev=analytics_data[-1],analytics_data[-2]
        if last['total_expense']>prev['total_expense']*1.1:
            suggestions.append(f"Τα έξοδα αυξήθηκαν κατά {last['total_expense']-prev['total_expense']:.2f}€")
    avg_expense=total_expense/len(analytics_data) if analytics_data else 0
    return render_template('analytics.html',
        analytics_data=analytics_data,total_income=round(total_income,2),
        total_expense=round(total_expense,2),total_balance=round(total_income-total_expense,2),
        top_categories=top_cats,suggestions=suggestions,avg_expense=round(avg_expense,2),
        cat_colors=CAT_COLORS,all_months=all_months,greek_months=GREEK_MONTHS,
        now=datetime.now(),username=session.get('username'))

@app.route('/calendar')
@app.route('/calendar/<int:year>/<int:month_num>')
@login_required
def calendar_view(year=None, month_num=None):
    uid = current_user_id()
    today = date.today()
    if year is None:
        year = today.year
    if month_num is None:
        month_num = today.month

    # Υπολογισμός prev/next μήνα
    if month_num == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month_num - 1
    if month_num == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month_num + 1

    # Ημέρες του μήνα
    first_weekday, days_in_month = calendar.monthrange(year, month_num)
    # Ελληνικό: εβδομάδα ξεκινά Δευτέρα (0=Δευ ... 6=Κυρ)
    # first_weekday είναι ήδη 0=Δευ με calendar module

    # Φέρνουμε κινήσεις του μήνα για αυτόν τον χρήστη
    conn = get_db()
    c = conn.cursor()
    c.execute("""SELECT t.* FROM transactions t
                 JOIN months m ON t.month_id = m.id
                 WHERE m.user_id=? AND m.year=? AND m.month=?
                 ORDER BY t.transaction_date, t.id""",
              (uid, year, month_num))
    transactions = c.fetchall()

    # Ομαδοποίηση ανά ημέρα
    days_data = {}
    for t in transactions:
        try:
            d = datetime.fromisoformat(t['transaction_date']).day
        except Exception:
            continue
        if d not in days_data:
            days_data[d] = {'income': 0.0, 'expense': 0.0, 'transactions': []}
        days_data[d]['transactions'].append(dict(t))
        if t['type'] == 'income':
            days_data[d]['income'] += t['amount']
        else:
            days_data[d]['expense'] += t['amount']

    # Βρίσκουμε αν υπάρχει month_id για αυτόν τον μήνα
    c.execute("SELECT id FROM months WHERE user_id=? AND year=? AND month=?",
              (uid, year, month_num))
    month_row = c.fetchone()
    month_id = month_row['id'] if month_row else None

    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year DESC, month DESC", (uid,))
    all_months = c.fetchall()
    conn.close()

    return render_template('calendar.html',
        year=year, month_num=month_num,
        month_name=GREEK_MONTHS[month_num],
        first_weekday=first_weekday,
        days_in_month=days_in_month,
        days_data=days_data,
        today=today,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        month_id=month_id,
        all_months=all_months,
        greek_months=GREEK_MONTHS,
        now=datetime.now(),
        username=session.get('username'))

@app.route('/search')
@login_required
def search():
    uid=current_user_id(); q=request.args.get('q','')
    conn=get_db(); c=conn.cursor()
    c.execute("""SELECT t.*,m.name as month_name FROM transactions t
                 JOIN months m ON t.month_id=m.id
                 WHERE m.user_id=? AND (t.category LIKE ? OR t.subcategory LIKE ? OR t.description LIKE ?)
                 ORDER BY t.transaction_date DESC""",(uid,f'%{q}%',f'%{q}%',f'%{q}%'))
    results=c.fetchall()
    c.execute("SELECT * FROM months WHERE user_id=? ORDER BY year DESC,month DESC",(uid,))
    all_months=c.fetchall(); conn.close()
    return render_template('search.html',results=results,query=q,
                           all_months=all_months,greek_months=GREEK_MONTHS,
                           now=datetime.now(),username=session.get('username'))

if __name__=='__main__':
    init_db()
    app.run(debug=True,port=5000)
