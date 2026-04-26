import os
from flask import Flask, request, jsonify, render_template_string, redirect, send_file, session
import sqlite3
import random
import string
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pagla_license_server_key_2026")

# ================= 🔐 ADMIN CREDENTIALS =================
# Railway Environment Variables থেকে ইউজারনেম/পাসওয়ার্ড নিবে, না পেলে ডিফল্টটা ব্যবহার করবে।
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")

# ================= 🔧 RAILWAY CLOUD SETUP =================
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "master_licenses.db")
UPDATE_FOLDER = os.path.join(DATA_DIR, "updates")
os.makedirs(UPDATE_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS licenses 
                    (id INTEGER PRIMARY KEY, key TEXT UNIQUE, shop_name TEXT, 
                     expiry_date TIMESTAMP, domain TEXT, status TEXT DEFAULT 'Active')''')
    try: conn.execute("ALTER TABLE licenses ADD COLUMN phone TEXT")
    except: pass
    try: conn.execute("ALTER TABLE licenses ADD COLUMN address TEXT")
    except: pass

    conn.execute('''CREATE TABLE IF NOT EXISTS sys_settings (id INTEGER PRIMARY KEY, latest_version TEXT)''')
    if not conn.execute("SELECT * FROM sys_settings").fetchone():
        conn.execute("INSERT INTO sys_settings (id, latest_version) VALUES (1, '1.0')")
        
    conn.execute('''CREATE TABLE IF NOT EXISTS fraud_logs
                    (id INTEGER PRIMARY KEY, key TEXT, attempted_domain TEXT, 
                     actual_domain TEXT, attempt_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit(); conn.close()

init_db()

# ================= 🛡️ LOGIN SYSTEM =================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ""
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['logged_in'] = True
            return redirect('/')
        else:
            error = "ভুল ইউজারনেম বা পাসওয়ার্ড!"
            
    html = f"""
    <html><head><title>Admin Login</title>
    <style>
        body {{ font-family: sans-serif; background: #f4f6f9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .login-box {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); text-align: center; width: 300px; }}
        input {{ width: 100%; padding: 10px; margin: 10px 0; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }}
        button {{ width: 100%; padding: 10px; background: #1155cc; color: white; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; }}
        button:hover {{ background: #0b409c; }}
        .error {{ color: red; margin-bottom: 10px; font-weight: bold; }}
    </style>
    </head><body>
        <div class="login-box">
            <h2 style="color:#1155cc;">Master Panel Login</h2>
            {{% if error %}}<div class="error">{{{{ error }}}}</div>{{% endif %}}
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
        </div>
    </body></html>
    """
    return render_template_string(html, error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')


# ================= 🚀 AUTO UPDATE APIs =================
@app.route('/check_update', methods=['POST'])
def check_update():
    conn = get_db(); st = conn.execute("SELECT latest_version FROM sys_settings WHERE id=1").fetchone()
    current_released_version = st['latest_version'] if st else "1.0"; conn.close()
    if os.path.exists(os.path.join(UPDATE_FOLDER, "update.zip")):
        return jsonify({"latest_version": current_released_version, "download_url": request.host_url.rstrip('/') + "/download_update"})
    return jsonify({"latest_version": "1.0", "download_url": ""})

@app.route('/download_update', methods=['GET'])
def download_update():
    file_path = os.path.join(UPDATE_FOLDER, "update.zip")
    if os.path.exists(file_path): return send_file(file_path, as_attachment=True)
    return "Update file not found!", 404

@app.route('/publish_release', methods=['POST'])
@login_required
def publish_release():
    v = request.form.get('version')
    file = request.files.get('update_zip')
    if file and file.filename.endswith('.zip'): file.save(os.path.join(UPDATE_FOLDER, "update.zip"))
    if v:
        conn = get_db(); conn.execute("UPDATE sys_settings SET latest_version=? WHERE id=1", (v,)); conn.commit(); conn.close()
    return redirect('/')

# ================= 🌐 MASTER PANEL UI =================
@app.route('/')
@login_required
def dashboard():
    search = request.args.get('search', '').strip()
    filter_days = request.args.get('filter')
    
    # Session থেকে নতুন key বের করে মুছে ফেলা হচ্ছে (যাতে ২য় বার রিলোডে না দেখায়)
    new_key = session.pop('new_generated_key', None)
    new_shop = session.pop('new_generated_shop', None)

    conn = get_db()
    
    query = "SELECT * FROM licenses WHERE 1=1"
    params = []
    
    if search:
        query += " AND phone LIKE ?"
        params.append(f"%{search}%")
        
    if filter_days:
        end_date = datetime.now() + timedelta(days=int(filter_days))
        query += " AND expiry_date <= ?"
        params.append(end_date)
        
    query += " ORDER BY expiry_date ASC"
    
    licenses_raw = conn.execute(query, params).fetchall()
    st = conn.execute("SELECT latest_version FROM sys_settings WHERE id=1").fetchone()
    current_version = st['latest_version'] if st else "1.0"
    fraud_count = conn.execute("SELECT COUNT(*) as c FROM fraud_logs").fetchone()['c']
    conn.close()

    active_licenses = []
    expired_licenses = []
    
    for l in licenses_raw:
        l_dict = dict(l)
        exp_date = datetime.strptime(str(l['expiry_date']).split('.')[0], "%Y-%m-%d %H:%M:%S")
        l_dict['expiry_str'] = exp_date.strftime("%Y-%m-%d")
        
        if datetime.now() > exp_date:
            l_dict['is_expired'] = True
            expired_licenses.append(l_dict)
        else:
            l_dict['is_expired'] = False
            active_licenses.append(l_dict)

    html = f"""
    <html><head><title>SaaS Master Panel</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body{{font-family: 'Segoe UI', sans-serif; background:#f4f6f9; padding: 20px;}} 
        .card{{background:white; padding:20px; border-radius:12px; box-shadow:0 4px 15px rgba(0,0,0,0.05); margin-bottom:20px;}} 
        table{{width: 100%; border-collapse: collapse; background:white; box-shadow:0 4px 15px rgba(0,0,0,0.05); margin-bottom:30px; border-radius:8px; overflow:hidden;}} 
        th, td{{border-bottom: 1px solid #e1e5eb; padding: 12px; text-align: left;}} 
        th{{background: #1155cc; color:white; font-weight: 600;}} 
        .btn{{padding: 8px 15px; text-decoration: none; color: white; border-radius: 6px; font-weight:bold; display:inline-flex; align-items:center; gap:5px; border:none; cursor:pointer; font-size:14px; transition:0.2s;}}
        .btn:hover{{opacity:0.8;}}
        input, select{{padding:10px; border: 1px solid #ccc; border-radius: 6px; width: 100%; box-sizing: border-box;}}
        .grid-2{{display: grid; grid-template-columns: 1fr 1fr; gap: 20px;}}
        .top-nav{{display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;}}
        .alert-card{{background: #fdf5f5; border-left: 5px solid #e74a3b; padding: 15px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center;}}
        .new-key-box {{ background: #e8f5e9; border: 2px dashed #27ae60; padding: 20px; margin-bottom: 20px; border-radius: 8px; text-align: center; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(39, 174, 96, 0.4); }} 70% {{ box-shadow: 0 0 0 10px rgba(39, 174, 96, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(39, 174, 96, 0); }} }}
    </style></head>
    <body>
        <div class="top-nav">
            <h2 style="color:#1155cc; margin:0;"><i class="fas fa-crown" style="color:#f1c40f;"></i> Master Control Panel</h2>
            <div>
                <a href="/fraud_logs" class="btn" style="background:#e74a3b; font-size: 16px; padding:10px 20px; margin-right: 10px;">
                    <i class="fas fa-shield-alt"></i> Alerts <span style="background:white; color:red; padding:2px 8px; border-radius:10px; margin-left:5px; font-weight:bold;">{fraud_count}</span>
                </a>
                <a href="/logout" class="btn" style="background:#34495e; font-size: 16px; padding:10px 20px;"><i class="fas fa-sign-out-alt"></i> Logout</a>
            </div>
        </div>
        
        {{% if new_key %}}
        <div class="new-key-box">
            <h2 style="color:#27ae60; margin-top:0;"><i class="fas fa-check-circle"></i> New License Created!</h2>
            <p style="font-size: 18px; margin-bottom: 5px;">Client/Shop: <b>{{{{ new_shop }}}}</b></p>
            <p style="font-size: 20px; margin: 0;">License Key: <br>
                <input type="text" value="{{{{ new_key }}}}" id="copyKey" style="text-align:center; font-size:24px; font-weight:bold; color:#c0392b; width:50%; margin-top:10px;" readonly>
            </p>
            <small style="color:#555;">(Please copy this key now. It will disappear if you refresh the page)</small>
        </div>
        {{% endif %}}
        
        <div class="grid-2">
            <div class="card" style="border-top: 5px solid #27ae60;">
                <h3 style="margin-top:0; color:#27ae60;"><i class="fas fa-key"></i> Create New License</h3>
                <form action="/create" method="POST" style="display:flex; flex-direction:column; gap:10px;">
                    <div style="display:flex; gap:10px;">
                        <input type="text" name="shop_name" placeholder="Client Shop Name" required>
                        <input type="text" name="phone" placeholder="Phone Number (e.g. 017...)" required>
                    </div>
                    <div style="display:flex; gap:10px;">
                        <input type="text" name="address" placeholder="Address / Location" style="flex:2;">
                        <select name="days" style="flex:1;" required>
                            <option value="7">1 Week Trial</option>
                            <option value="90">3 Months</option>
                            <option value="180">6 Months</option>
                            <option value="365" selected>1 Year</option>
                        </select>
                    </div>
                    <button type="submit" class="btn" style="background:#27ae60; width:100%; justify-content:center; font-size:16px;"><i class="fas fa-plus-circle"></i> Generate License Key</button>
                </form>
            </div>
            
            <div class="card" style="border-top: 5px solid #f39c12;">
                <h3 style="margin-top:0; color:#d35400;"><i class="fas fa-search"></i> Search & Filters</h3>
                <form action="/" method="GET" style="display:flex; gap:10px; margin-bottom:15px;">
                    <input type="text" name="search" placeholder="Search by Phone Number..." value="{search}" style="margin:0;">
                    <button type="submit" class="btn" style="background:#1155cc;"><i class="fas fa-search"></i> Search</button>
                    <a href="/" class="btn" style="background:#95a5a6;"><i class="fas fa-times"></i> Clear</a>
                </form>
                
                <b style="color:#555;">Upcoming Expiry Filters:</b>
                <div style="display:flex; gap:10px; margin-top:10px;">
                    <a href="/?filter=3" class="btn" style="background:#e74a3b;"><i class="fas fa-filter"></i> 3 Days</a>
                    <a href="/?filter=7" class="btn" style="background:#e67e22;"><i class="fas fa-filter"></i> 7 Days</a>
                    <a href="/?filter=14" class="btn" style="background:#f1c40f; color:black;"><i class="fas fa-filter"></i> 14 Days</a>
                </div>
            </div>
        </div>

        <h3 style="color:#c0392b; margin-top:20px; border-bottom:2px solid #c0392b; padding-bottom:10px;"><i class="fas fa-exclamation-circle"></i> Expired Accounts Alert</h3>
        {{% if expired_licenses %}}
            {{% for l in expired_licenses %}}
            <div class="alert-card">
                <div>
                    <h4 style="margin:0; color:#c0392b;">{{{{ l.shop_name }}}}</h4>
                    <span style="font-size:20px; font-weight:bold; color:#333;"><i class="fas fa-phone-alt" style="color:#27ae60;"></i> {{{{ l.phone }}}}</span><br>
                    <small style="color:#777;"><i class="fas fa-map-marker-alt"></i> {{{{ l.address or 'N/A' }}}}</small>
                </div>
                <div style="text-align:center;">
                    <code style="background:white; color:#c0392b; padding:6px 10px; font-size:16px; border:1px solid #c0392b; border-radius:6px; font-weight:bold;">{{{{ l.key }}}}</code><br>
                    <small style="color:#c0392b; font-weight:bold;">Expired on: {{{{ l.expiry_str }}}}</small>
                </div>
                <div style="display:flex; flex-direction:column; gap:5px; align-items:flex-end;">
                    <form action="/renew_license/{{{{ l.key }}}}" method="POST" style="display:flex; gap:5px; margin:0;">
                        <input type="number" name="days" placeholder="Days" value="30" style="width:70px; margin:0; padding:5px;" required>
                        <button type="submit" class="btn" style="background:#27ae60; padding:5px 10px;" title="Manual Renew"><i class="fas fa-check"></i> Reactivate</button>
                    </form>
                    <div style="display:flex; gap:5px;">
                        {{% if l.status == 'Active' %}}
                            <a href="/block_license/{{{{ l.key }}}}" class="btn" style="background:#34495e; padding:5px 10px;" onclick="return confirm('Ban this account?')"><i class="fas fa-ban"></i> Ban Account</a>
                        {{% else %}}
                            <a href="/unblock_license/{{{{ l.key }}}}" class="btn" style="background:#f39c12; padding:5px 10px;"><i class="fas fa-unlock"></i> Unban</a>
                        {{% endif %}}
                        
                        <a href="/delete_license/{{{{ l.key }}}}" class="btn" style="background:#c0392b; padding:5px 10px;" onclick="return confirm('Are you sure you want to permanently DELETE this expired key?')"><i class="fas fa-trash"></i> Delete Key</a>
                    </div>
                </div>
            </div>
            {{% endfor %}}
        {{% else %}}
            <p style="color:green; font-weight:bold;"><i class="fas fa-check-circle"></i> No expired accounts found!</p>
        {{% endif %}}

        <h3 style="color:#1155cc; margin-top:40px; border-bottom:2px solid #1155cc; padding-bottom:10px;"><i class="fas fa-check-circle"></i> Active Clients</h3>
        <table>
            <tr><th>Status</th><th>Shop & Phone</th><th>License Key</th><th>Domain / PC</th><th>Renew / Actions</th></tr>
            {{% for l in active_licenses %}}
            <tr>
                <td style="text-align:center;">
                    {{% if l.status == 'Blocked' %}}<span style="color:red; font-size:20px;" title="Banned"><i class="fas fa-ban"></i> Banned</span>
                    {{% else %}}<span style="color:green; font-size:20px;"><i class="fas fa-check-circle"></i> Active</span>{{% endif %}}
                </td>
                <td>
                    <b>{{{{ l.shop_name }}}}</b><br>
                    <span style="font-weight:bold; color:#1155cc;"><i class="fas fa-phone-alt"></i> {{{{ l.phone or 'N/A' }}}}</span><br>
                    <small style="color:#777;">{{{{ l.address or 'N/A' }}}}</small>
                </td>
                <td><code style="background:#e8f0fe; color:#1155cc; padding:5px 8px; font-size:14px; border-radius:4px; font-weight:bold;">{{{{ l.key }}}}</code></td>
                <td>
                    {{% if l.domain %}} <span style="color:#27ae60; font-weight:bold;"><i class="fas fa-desktop"></i> PC Linked</span> 
                    {{% else %}} <span style="color:gray;">Not Linked</span> {{% endif %}}<br>
                    <small style="color:#e67e22; font-weight:bold;"><i class="fas fa-clock"></i> Exp: {{{{ l.expiry_str }}}}</small>
                </td>
                <td>
                    <form action="/renew_license/{{{{ l.key }}}}" method="POST" style="display:flex; gap:5px; margin-bottom:5px;">
                        <input type="number" name="days" placeholder="Days" value="30" style="width:70px; margin:0; padding:5px;" required>
                        <button type="submit" class="btn" style="background:#8e44ad; padding:5px 10px;" onclick="return confirm('Extend validity?')"><i class="fas fa-sync"></i> Renew</button>
                    </form>
                    <div style="display:flex; gap:5px;">
                        {{% if l.status == 'Active' %}}
                            <a href="/block_license/{{{{ l.key }}}}" class="btn" style="background:#34495e; padding:5px 10px;" onclick="return confirm('Ban this account?')"><i class="fas fa-ban"></i> Ban</a>
                        {{% else %}}
                            <a href="/unblock_license/{{{{ l.key }}}}" class="btn" style="background:#f39c12; padding:5px 10px;"><i class="fas fa-unlock"></i> Unban</a>
                        {{% endif %}}
                        <a href="/delete_license/{{{{ l.key }}}}" class="btn" style="background:#c0392b; padding:5px 10px;" onclick="return confirm('Delete this Key FOREVER?')"><i class="fas fa-trash"></i> Del</a>
                    </div>
                </td>
            </tr>
            {{% endfor %}}
            {{% if not active_licenses %}}
            <tr><td colspan="5" style="text-align:center; color:gray;">No active licenses.</td></tr>
            {{% endif %}}
        </table>
    </body></html>
    """
    return render_template_string(html, active_licenses=active_licenses, expired_licenses=expired_licenses, current_version=current_version, fraud_count=fraud_count, search=search, new_key=new_key, new_shop=new_shop)

# ================= 🚨 FRAUD DETECTION PAGE =================
@app.route('/fraud_logs')
@login_required
def fraud_logs():
    conn = get_db()
    query = """
        SELECT f.*, l.shop_name, l.phone 
        FROM fraud_logs f 
        LEFT JOIN licenses l ON f.key = l.key 
        ORDER BY f.id DESC
    """
    logs = conn.execute(query).fetchall()
    conn.close()
    
    html = f"""
    <html><head><title>Security Alerts</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>body{{font-family: 'Segoe UI', sans-serif; padding: 20px; background:#fce8e6;}} table{{width: 100%; border-collapse: collapse; background:white; box-shadow:0 4px 10px rgba(0,0,0,0.1);}} th, td{{
