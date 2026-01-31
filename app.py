from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
from datetime import datetime

# Geopy Setup
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v18")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA ---
history_log = [] 

current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, 
    "temp": 0, "hum": 0, "press": 0, "gas": 0, "alt": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never", "connection_status": "Disconnected"
}

# --- SMART COLUMN FIXER ---
def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c_lower = str(col).lower().strip()
        if 'pm1.0' in c_lower or ('pm1' in c_lower and 'pm10' not in c_lower): col_map[col] = 'pm1'
        elif 'pm2.5' in c_lower or 'pm25' in c_lower: col_map[col] = 'pm25'
        elif 'pm10' in c_lower: col_map[col] = 'pm10'
        elif 'temp' in c_lower: col_map[col] = 'temp'
        elif 'hum' in c_lower: col_map[col] = 'hum'
        elif 'press' in c_lower: col_map[col] = 'press'
        elif 'gas' in c_lower: col_map[col] = 'gas'
        elif 'alt' in c_lower: col_map[col] = 'alt'
        elif 'lat' in c_lower or 'lal' in c_lower: col_map[col] = 'lat'
        elif 'lon' in c_lower or 'lng' in c_lower: col_map[col] = 'lon'
    return df.rename(columns=col_map)

# --- LOCATION HELPER ---
def get_city_name(lat, lon):
    if not geolocator or lat == 0: return "Unknown Area"
    try:
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en')
        if location:
            add = location.raw.get('address', {})
            return add.get('suburb') or add.get('city') or add.get('town') or "Unknown Area"
    except:
        return "Unknown Area"
    return "Unknown Area"

# --- HEALTH ENGINE ---
def calculate_advanced_health(val):
    risks = []
    # 1. Asthma
    asthma_score = (val['pm25'] * 1.2) + (val['pm10'] * 0.5)
    risks.append({"name": "Asthma & Allergies", "prob": min(98, int(asthma_score)), "level": "High" if asthma_score > 50 else "Moderate"})
    # 2. Respiratory
    resp_score = (val['pm10'] * 0.8) + (val['hum'] < 30) * 20
    risks.append({"name": "Respiratory Diseases", "prob": min(95, int(resp_score)), "level": "High" if resp_score > 60 else "Moderate"})
    # 3. Cardio
    cardio_score = (val['pm25'] * 0.9)
    risks.append({"name": "Cardiovascular Diseases", "prob": min(90, int(cardio_score)), "level": "High" if cardio_score > 55 else "Moderate"})
    # 4. Heat
    if val['temp'] > 30:
        risks.append({"name": "Heat Stress", "prob": min(100, int((val['temp']-30)*10)), "level": "High"})
    
    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- UI TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Atoms</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --bg:#0f172a; --card:#1e293b; --text:#f1f5f9; --muted:#94a3b8; --p:#3b82f6; --o:#f59e0b; --d:#ef4444; --s:#22c55e; --b:#334155; }
        * { box-sizing:border-box; margin:0; padding:0; }
        body { font-family:'Inter',sans-serif; background:var(--bg); color:var(--text); padding:30px 20px; }
        .container { max-width:1200px; margin:0 auto; }
        .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:30px; }
        .logo { font-size:1.8rem; font-weight:800; } .logo i { color:var(--p); margin-right:10px; }
        .refresh-btn { background:var(--p); color:white; border:none; padding:8px 16px; border-radius:8px; font-weight:600; cursor:pointer; }
        
        .alert-banner { background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); color:var(--o); padding:15px; border-radius:12px; margin-bottom:30px; display:flex; align-items:center; gap:15px; }
        
        .nav-tabs { display:flex; gap:10px; background:var(--card); padding:6px; border-radius:12px; margin-bottom:30px; overflow-x:auto; border:1px solid var(--b); }
        .tab-btn { border:none; background:transparent; padding:8px 20px; font-weight:600; color:var(--muted); cursor:pointer; border-radius:8px; white-space:nowrap; }
        .tab-btn.active { background:var(--p); color:white; }
        
        .section { display:none; } .section.active { display:block; }
        .grid { display:grid; grid-template-columns:1.5fr 1fr; gap:25px; }
        @media(max-width:850px){ .grid { grid-template-columns:1fr; } }
        
        .card { background:var(--card); border-radius:20px; padding:30px; border:1px solid var(--b); height:100%; }
        .card-head { display:flex; justify-content:space-between; margin-bottom:20px; font-weight:700; font-size:1.1rem; }
        
        .aqi-box { text-align:center; padding:20px 0; }
        .aqi-num { font-size:6rem; font-weight:800; color:var(--o); line-height:1; }
        .loc-pill { background:var(--bg); padding:6px 15px; border-radius:20px; font-size:0.85rem; font-weight:600; display:inline-flex; align-items:center; gap:6px; margin-top:15px; border:1px solid var(--b); }
        
        .bar-row { margin-bottom:15px; }
        .bar-head { display:flex; justify-content:space-between; font-size:0.9rem; font-weight:600; margin-bottom:5px; }
        .bar-track { height:8px; background:var(--bg); border-radius:4px; overflow:hidden; }
        .bar-fill { height:100%; background:var(--p); border-radius:4px; }
        
        .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:15px; margin-bottom:30px; }
        .stat-box { background:var(--bg); padding:20px; border-radius:16px; text-align:center; border:1px solid var(--b); }
        .stat-val { font-size:1.8rem; font-weight:800; color:var(--p); }
        
        .risk-item { display:flex; justify-content:space-between; padding:15px 0; border-bottom:1px solid var(--b); font-weight:600; }
        .risk-badge { font-size:0.8rem; padding:4px 10px; border-radius:6px; background:rgba(239,68,68,0.2); color:var(--d); }
        
        .upload-area { display:block; border:2px dashed var(--b); padding:40px; text-align:center; border-radius:16px; cursor:pointer; background:var(--bg); margin-top:15px; }
        .date-input { width:100%; padding:12px; background:var(--bg); border:1px solid var(--b); color:var(--text); border-radius:8px; }
        .history-row { display:flex; justify-content:space-between; padding:15px; background:var(--bg); border:1px solid var(--b); border-radius:10px; margin-bottom:10px; }
        
        .btn-main { background:var(--p); color:white; padding:12px 24px; border-radius:8px; font-weight:600; text-decoration:none; display:inline-block; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    </div>

    <div class="alert-banner">
        <div class="alert-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <div><strong>System Status:</strong> <span id="alert-msg">Waiting for data...</span></div>
    </div>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="switchTab('overview')">Overview</button>
        <button class="tab-btn" onclick="switchTab('charts')">GPS Charts</button>
        <button class="tab-btn" onclick="switchTab('history')">History</button>
        <button class="tab-btn" onclick="switchTab('esp32')">ESP32</button>
        <button class="tab-btn" onclick="switchTab('upload')">Upload</button>
        <button class="tab-btn" onclick="switchTab('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="grid">
            <div class="card">
                <div class="card-head"><span>Air Quality Index</span> <span style="color:var(--s); font-size:0.8rem;">● LIVE</span></div>
                <div class="aqi-box">
                    <div class="aqi-num" id="aqi-val">--</div>
                    <div style="color:var(--muted); margin-top:5px;">US AQI Standard</div>
                    <div class="loc-pill"><i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown</span></div>
                </div>
                <div style="margin-top:30px;">
                    <div class="card-head" style="font-size:1rem;">Pollutants</div>
                    <div id="metric-container"></div>
                </div>
            </div>
            <div class="card">
                <div class="card-head">Health Summary</div>
                <div class="stat-grid">
                    <div class="stat-box"><div class="stat-val" id="aqi-score">--</div><div style="font-size:0.8rem; color:var(--muted);">AQI Score</div></div>
                    <div class="stat-box"><div class="stat-val" style="color:var(--o);" id="risk-count">--</div><div style="font-size:0.8rem; color:var(--muted);">Risks</div></div>
                </div>
                <div class="card-head" style="font-size:1rem;">Detected Risks</div>
                <div id="risk-container" style="color:var(--muted); text-align:center;">Safe Conditions.</div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <div class="card-head">AQI vs Flight Path</div>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-head">Upload History</div>
            <div id="history-container" style="color:var(--muted); text-align:center;">No files yet.</div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="grid">
            <div class="card">
                <div class="card-head">Connection</div>
                <p>Endpoint: <code style="background:var(--b); padding:2px 6px;">/api/upload_sensor</code></p>
                <p style="margin-top:10px;">Status: <span style="color:var(--s);">● Listening</span></p>
            </div>
            <div class="card">
                <div class="card-head">Logs</div>
                <div id="esp-console" style="font-family:monospace; color:var(--s); height:150px; overflow-y:auto;"></div>
            </div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-head">Upload Data</div>
            <p style="color:var(--muted); margin-bottom:5px;">Select Date</p>
            <input type="date" id="upload-date" class="date-input">
            <label class="upload-area">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size:2rem; color:var(--muted); margin-bottom:10px;"></i>
                <div style="font-weight:600;">Browse CSV / Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-head">Export Data</div>
            <a href="/export" class="btn-main">Download CSV Report</a>
        </div>
    </div>
</div>

<script>
    Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = '#334155';
    function switchTab(id) {
        document.querySelectorAll('.section').forEach(e => e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(e => e.classList.remove('active'));
        document.querySelector(`button[onclick="switchTab('${id}')"]`).classList.add('active');
    }
    
    setInterval(() => { fetch('/api/data').then(r=>r.json()).then(d=>updateUI(d)); }, 3000);

    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const f = e.target.files[0], dInput = document.getElementById('upload-date');
        if(!dInput.value) { alert("Select date first!"); return; }
        if(!f) return;
        const fd = new FormData(); fd.append('file', f); fd.append('date', dInput.value);
        try {
            await fetch('/upload', {method:'POST', body:fd});
            alert("Uploaded!"); setTimeout(()=>switchTab('overview'), 500);
        } catch(err) { alert("Error"); }
    });

    let chart;
    function updateUI(d) {
        document.getElementById('aqi-val').innerText = d.aqi;
        document.getElementById('aqi-score').innerText = d.aqi;
        document.getElementById('risk-count').innerText = d.health_risks.length;
        document.getElementById('location-name').innerText = d.location_name;
        document.getElementById('alert-msg').innerText = d.aqi > 100 ? "Warning: High Pollution" : "Air is Good";

        const mc = document.getElementById('metric-container'); mc.innerHTML = '';
        [{k:'pm25',l:'PM2.5',m:100}, {k:'pm10',l:'PM10',m:150}, {k:'temp',l:'Temp',m:50}, {k:'hum',l:'Hum',m:100}].forEach(i => {
            const v = d[i.k]||0, p = Math.min((v/i.m)*100, 100);
            mc.innerHTML += `<div class="bar-row"><div class="bar-head"><span>${i.l}</span><span>${v}</span></div><div class="bar-track"><div class="bar-fill" style="width:${p}%"></div></div></div>`;
        });

        const rc = document.getElementById('risk-container');
        if(d.health_risks.length) {
            rc.innerHTML = '';
            d.health_risks.forEach(r => rc.innerHTML += `<div class="risk-item"><span>${r.name}</span><span class="risk-badge">${r.level}</span></div>`);
        }

        const hc = document.getElementById('history-container');
        if(d.history && d.history.length) {
            hc.innerHTML = '';
            d.history.forEach(h => hc.innerHTML += `<div class="history-row"><span>${h.date} | ${h.filename}</span><span style="color:var(--p); font-weight:700;">AQI ${h.aqi}</span></div>`);
        }

        if(d.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = d.chart_data.gps.map(g => `${Number(g.lat).toFixed(3)},${Number(g.lon).toFixed(3)}`);
            if(chart) chart.destroy();
            chart = new Chart(ctx, {
                type: 'bar',
                data: { labels: labels, datasets: [{ label: 'AQI', data: d.chart_data.aqi, backgroundColor: '#3b82f6', borderRadius:4 }] },
                options: { responsive:true, maintainAspectRatio:false, scales:{x:{ticks:{maxRotation:45, minRotation:45}}} }
            });
        }
        document.getElementById('esp-console').innerHTML = d.esp32_log.join('<br>');
    }
</script>
</body>
</html>
"""

# --- BACKEND ROUTES ---
@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data(): 
    current_data['history'] = history_log
    return jsonify(current_data)

@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    user_date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400

        df = normalize_columns(df)
        for c in ['pm1','pm25','pm10','temp','hum','lat','lon']: 
            if c not in df.columns: df[c] = 0

        val = {k: round(df[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        valid = df[(df['lat']!=0)]
        loc = get_city_name(valid.iloc[0]['lat'], valid.iloc[0]['lon']) if not valid.empty else "No GPS"

        gps, aqis = [], []
        for i, r in df.head(50).iterrows():
            aqis.append(int((r['pm25']*2)+(r['pm10']*0.5)))
            gps.append({"lat":r['lat'],"lon":r['lon']})

        history_log.append({"date":user_date, "filename":file.filename, "aqi":aqi})
        history_log.sort(key=lambda x:x['date'], reverse=True)

        current_data.update({"aqi":aqi, **val, "location_name":loc, "health_risks":calculate_advanced_health(val), "chart_data":{"aqi":aqis,"gps":gps}, "last_updated":datetime.now().strftime("%H:%M:%S")})
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def receive_sensor():
    global current_data
    try:
        d = request.json
        current_data.update(d)
        aqi = int((d.get('pm25',0)*2) + (d.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['health_risks'] = calculate_advanced_health(current_data)
        current_data['location_name'] = get_city_name(d.get('lat',0), d.get('lon',0))
        current_data['last_updated'] = datetime.now().strftime("%H:%M:%S")
        
        current_data['chart_data']['aqi'].append(aqi)
        current_data['chart_data']['gps'].append({"lat":d.get('lat',0), "lon":d.get('lon',0)})
        if len(current_data['chart_data']['aqi']) > 50: 
            current_data['chart_data']['aqi'].pop(0)
            current_data['chart_data']['gps'].pop(0)

        current_data['esp32_log'].append(f"> AQI:{aqi} | Loc:{current_data['location_name']}")
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route('/export')
def export_report():
    out = io.StringIO()
    out.write(f"Report Date,{datetime.now()}\nLocation,{current_data['location_name']}\nAQI,{current_data['aqi']}\n")
    mem = io.BytesIO()
    mem.write(out.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="SkySense_Report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
