import os
from flask import Flask, request, jsonify, render_template_string, redirect, send_file
import sqlite3
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pagla_license_server_key_2026")

# ================= 🔧 RAILWAY CLOUD SETUP =================
# Railway তে ডাটা যেন ডিলিট না হয়, তাই আমরা /app/data ডিরেক্টরি ব্যবহার করবো
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
def publish_release():
    v = request.form.get('version')
    file = request.files.get('update_zip')
    if file and file.filename.endswith('.zip'): file.save(os.path.join(UPDATE_FOLDER, "update.zip"))
    if v:
        conn = get_db(); conn.execute("UPDATE sys_settings SET latest_version=? WHERE id=1", (v,)); conn.commit(); conn.close()
    return redirect('/')

# ================= 🌐 MASTER PANEL UI =================
@app.route('/')
def dashboard():
    search = request.args.get('search', '').strip()
    filter_days = request.args.get('filter')
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
        .th-expired{{background: #c0392b !important; color:white; font-weight: 600;}} 
        .btn{{padding: 8px 15px; text-decoration: none; color: white; border-radius: 6px; font-weight:bold; display:inline-flex; align-items:center; gap:5px; border:none; cursor:pointer; font-size:14px; transition:0.2s;}}
        .btn:hover{{opacity:0.8;}}
        input, select{{padding:10px; border: 1px solid #ccc; border-radius: 6px; width: 100%; box-sizing: border-box;}}
        .grid-2{{display: grid; grid-template-columns: 1fr 1fr; gap: 20px;}}
        .top-nav{{display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;}}
        .alert-card{{background: #fdf5f5; border-left: 5px solid #e74a3b; padding: 15px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: center;}}
    </style></head>
    <body>
        <div class="top-nav">
            <h2 style="color:#1155cc; margin:0;"><i class="fas fa-crown" style="color:#f1c40f;"></i> Master Control Panel</h2>
            <a href="/fraud_logs" class="btn" style="background:#e74a3b; font-size: 16px; padding:10px 20px;">
                <i class="fas fa-shield-alt"></i> Security Alerts <span style="background:white; color:red; padding:2px 8px; border-radius:10px; margin-left:5px; font-weight:bold;">{fraud_count}</span>
            </a>
        </div>
        
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
    return render_template_string(html, active_licenses=active_licenses, expired_licenses=expired_licenses, current_version=current_version, fraud_count=fraud_count, search=search)

# ================= 🚨 FRAUD DETECTION PAGE =================
@app.route('/fraud_logs')
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
    <style>body{{font-family: 'Segoe UI', sans-serif; padding: 20px; background:#fce8e6;}} table{{width: 100%; border-collapse: collapse; background:white; box-shadow:0 4px 10px rgba(0,0,0,0.1);}} th, td{{border: 1px solid #ddd; padding: 12px;}} th{{background: #c0392b; color:white;}} .btn{{padding: 8px 12px; color: white; text-decoration:none; border-radius: 6px; font-weight:bold; display:inline-flex; align-items:center; gap:5px; transition:0.2s;}} .btn:hover{{opacity:0.8;}}</style></head>
    <body>
        <h2 style="color:#c0392b;"><i class="fas fa-shield-alt"></i> Security Alerts & Fraud Attempts</h2>
        <a href="/" class="btn" style="margin-bottom:20px; background:#2c3e50;"><i class="fas fa-arrow-left"></i> Back to Dashboard</a>
        <p style="font-weight:bold;">কেউ অন্য পিসিতে আপনার লাইসেন্স ব্যবহার করার চেষ্টা করলে এখানে ধরা পড়বে। আপনি তাকে কল দিয়ে ধরতে পারেন বা সরাসরি ব্যান করে দিতে পারেন!</p>
        <table>
            <tr><th>Date & Time</th><th>Client Info</th><th>Compromised Key</th><th>Registered PC</th><th>Thief's PC</th><th>Action</th></tr>
            {{% for lg in logs %}}
            <tr>
                <td>{{{{ lg.attempt_date }}}}</td>
                <td>
                    <b>{{{{ lg.shop_name or 'Unknown' }}}}</b><br>
                    <span style="font-size:18px; color:#27ae60; font-weight:bold;"><i class="fas fa-phone-alt"></i> {{{{ lg.phone or 'No Number' }}}}</span>
                </td>
                <td><code style="color:red; font-size:16px; font-weight:bold;">{{{{ lg.key }}}}</code></td>
                <td>{{{{ lg.actual_domain }}}}</td>
                <td style="color:#c0392b; font-weight:bold;"><i class="fas fa-desktop"></i> {{{{ lg.attempted_domain }}}}</td>
                <td>
                    <a href="/block_license/{{{{ lg.key }}}}" class="btn" style="background:#34495e; margin-bottom:5px;" onclick="return confirm('Ban this account instantly?')"><i class="fas fa-ban"></i> Ban Account</a><br>
                    <a href="/delete_license/{{{{ lg.key }}}}" class="btn" style="background:#c0392b;" onclick="return confirm('Delete this Key permanently?')"><i class="fas fa-trash"></i> Delete Key</a>
                </td>
            </tr>
            {{% endfor %}}
            {{% if not logs %}}
            <tr><td colspan="6" style="text-align:center; color:green; font-weight:bold;">No fraud attempts detected yet!</td></tr>
            {{% endif %}}
        </table>
    </body></html>
    """
    return render_template_string(html, logs=logs)

# ================= 🛠️ ACTIONS & LOGIC =================
@app.route('/create', methods=['POST'])
def create_license():
    shop_name = request.form.get('shop_name'); phone = request.form.get('phone'); address = request.form.get('address')
    days = int(request.form.get('days', 365))
    key = "PAGLA-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5)) + "-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5)) + "-" + ''.join(random.choices(string.digits, k=4))
    expiry = datetime.now() + timedelta(days=days)
    conn = get_db(); conn.execute("INSERT INTO licenses (key, shop_name, phone, address, expiry_date, domain) VALUES (?, ?, ?, ?, ?, NULL)", (key, shop_name, phone, address, expiry)); conn.commit(); conn.close()
    return redirect('/')

@app.route('/renew_license/<key>', methods=['POST'])
def renew_license(key):
    days = int(request.form.get('days', 30))
    conn = get_db()
    lic = conn.execute("SELECT expiry_date FROM licenses WHERE key=?", (key,)).fetchone()
    if lic:
        current_expiry = datetime.strptime(str(lic['expiry_date']).split('.')[0], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > current_expiry:
            new_expiry = datetime.now() + timedelta(days=days)
        else:
            new_expiry = current_expiry + timedelta(days=days)
            
        conn.execute("UPDATE licenses SET expiry_date=?, status='Active' WHERE key=?", (new_expiry, key))
        conn.commit()
    conn.close()
    return redirect(request.referrer or '/')

@app.route('/block_license/<key>')
def block_license(key):
    conn = get_db(); conn.execute("UPDATE licenses SET status='Blocked' WHERE key=?", (key,)); conn.commit(); conn.close(); return redirect(request.referrer or '/')

@app.route('/unblock_license/<key>')
def unblock_license(key):
    conn = get_db(); conn.execute("UPDATE licenses SET status='Active' WHERE key=?", (key,)); conn.commit(); conn.close(); return redirect(request.referrer or '/')

@app.route('/delete_license/<key>')
def delete_license(key):
    conn = get_db(); conn.execute("DELETE FROM licenses WHERE key=?", (key,)); conn.commit(); conn.close(); return redirect(request.referrer or '/')

@app.route('/verify_license', methods=['POST'])
def verify_license():
    key = request.json.get('key'); domain = request.json.get('domain'); conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    
    if not lic: conn.close(); return jsonify({"valid": False, "reason": "Invalid License Key! (ভুল লাইসেন্স কী)"})
    if lic['status'] == 'Blocked': conn.close(); return jsonify({"valid": False, "reason": "আপনার লাইসেন্সটি অ্যাডমিন দ্বারা ব্লক করা হয়েছে!"})
    
    saved_domain = lic['domain']
    if not saved_domain: 
        conn.execute("UPDATE licenses SET domain=? WHERE key=?", (domain, key)); conn.commit()
    elif saved_domain != domain:
        conn.execute("INSERT INTO fraud_logs (key, attempted_domain, actual_domain) VALUES (?, ?, ?)", (key, domain, saved_domain))
        conn.commit(); conn.close()
        return jsonify({"valid": False, "reason": f"লাইসেন্স লক এরর! এই লাইসেন্সটি অন্য কম্পিউটারে ব্যবহার করার চেষ্টা করা হচ্ছে। Security Alert Sent!"})
    
    expiry_date = datetime.strptime(str(lic['expiry_date']).split('.')[0], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > expiry_date: 
        conn.close()
        return jsonify({"valid": False, "reason": "আপনার লাইসেন্সের মেয়াদ শেষ! দয়া করে সফটওয়্যার রিনিউ করুন।"})
        
    conn.close()
    return jsonify({"valid": True, "expiry": expiry_date.strftime("%Y-%m-%d")})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)
