from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import datetime

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v101")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
history_log = [] 
current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never"
}

# --- ROBUST FILE READER ---
def read_file_safely(file):
    try:
        file.seek(0)
        return pd.read_csv(file)
    except:
        file.seek(0)
        return pd.read_excel(file)

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'press' in c: col_map[col] = 'press'
        elif 'gas' in c: col_map[col] = 'gas'
        elif 'alt' in c: col_map[col] = 'alt'
        elif 'lat' in c or 'lal' in c: col_map[col] = 'lat'
        elif 'lon' in c or 'lng' in c: col_map[col] = 'lon'
    return df.rename(columns=col_map)

def get_city_name(lat, lon):
    if not geolocator or lat == 0: return "Unknown Area"
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en')
        if loc:
            add = loc.raw.get('address', {})
            return add.get('suburb') or add.get('city') or add.get('town') or "Unknown Area"
    except: pass
    return "Unknown Area"

def calc_health(val):
    risks = []
    a_score = (val['pm25']*1.2) + (val['pm10']*0.5)
    risks.append({"name": "Asthma & Allergies", "prob": min(98, int(a_score)), "level": "High" if a_score>50 else "Moderate"})
    r_score = (val['pm10']*0.8) + (val['hum']<30)*20
    risks.append({"name": "Respiratory Diseases", "prob": min(95, int(r_score)), "level": "High" if r_score>60 else "Moderate"})
    c_score = (val['pm25']*0.9)
    risks.append({"name": "Cardiovascular Diseases", "prob": min(90, int(c_score)), "level": "High" if c_score>55 else "Moderate"})
    if val['temp']>30: risks.append({"name": "Heat Stress", "prob": min(100, int((val['temp']-30)*10)), "level": "High"})
    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Atoms Dark</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --bg: #0f172a; --card-bg: #1e293b; --text-main: #f1f5f9; --text-muted: #94a3b8; --primary: #3b82f6; --orange: #f59e0b; --danger: #ef4444; --success: #22c55e; --border: #334155; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; color: var(--text-main); letter-spacing: -1px; display:flex; align-items:center; gap:10px; }
        .logo i { color: var(--primary); }
        .refresh-btn { background: var(--primary); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .alert-banner { background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); color: var(--orange); padding: 15px 20px; border-radius: 12px; margin-bottom: 30px; display:flex; align-items:center; gap:15px; }
        .nav-tabs { display: flex; gap: 8px; background: var(--card-bg); padding: 6px; border-radius: 12px; margin-bottom: 30px; border: 1px solid var(--border); width: fit-content; }
        .tab-btn { border: none; background: transparent; padding: 8px 20px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-radius: 8px; transition: 0.2s; font-size: 0.9rem; }
        .tab-btn.active { background: var(--primary); color: white; }
        .section { display: none; animation: fadeIn 0.3s ease; }
        .section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
        .dashboard-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 25px; }
        @media(max-width: 850px) { .dashboard-grid { grid-template-columns: 1fr; } }
        .card { background: var(--card-bg); border-radius: 20px; padding: 30px; box-shadow: 0 4px 20px -2px rgba(0,0,0,0.3); border: 1px solid var(--border); height: 100%; position: relative; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .card-title { font-size: 1.1rem; font-weight: 700; color: var(--text-main); }
        .aqi-wrapper { display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 20px 0; }
        .aqi-num { font-size: 6rem; font-weight: 800; color: var(--orange); line-height: 1; letter-spacing: -2px; }
        .aqi-label { font-size: 1rem; font-weight: 600; color: var(--text-muted); margin-top: 10px; }
        .location-pill { background: var(--bg); padding: 6px 15px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; color: var(--text-main); margin-top: 15px; display:flex; align-items:center; gap:6px; border: 1px solid var(--border); }
        .metric-row { margin-bottom: 18px; }
        .metric-head { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.9rem; font-weight: 600; color: var(--text-main); }
        .progress-track { height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden; }
        .progress-fill { height: 100%; background: var(--primary); border-radius: 4px; transition: width 1s ease; }
        .summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 30px; }
        .stat-card { background: var(--bg); padding: 20px; border-radius: 16px; text-align: center; border: 1px solid var(--border); }
        .stat-val { font-size: 1.8rem; font-weight: 800; color: var(--primary); }
        .stat-name { font-size: 0.8rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; margin-top: 5px; }
        .risk-item { display: flex; justify-content: space-between; align-items: center; padding: 15px 0; border-bottom: 1px solid var(--border); }
        .risk-name { font-weight: 600; font-size: 0.95rem; color: var(--text-main); }
        .risk-badge { font-size: 0.8rem; font-weight: 700; padding: 4px 10px; border-radius: 6px; }
        .upload-area { display: block; width: 100%; box-sizing: border-box; border: 2px dashed var(--border); padding: 50px 20px; text-align: center; border-radius: 16px; cursor: pointer; transition: 0.2s; background: var(--bg); margin-top: 15px; }
        .date-input { width: 100%; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px; font-family: 'Inter', sans-serif; font-size: 1rem; box-sizing: border-box; background: var(--bg); color: var(--text-main); }
        .history-row { display: flex; justify-content: space-between; padding: 15px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 10px; align-items: center; }
        .console { background: #0f172a; color: #4ade80; padding: 20px; border-radius: 12px; font-family: monospace; height: 200px; overflow-y: auto; font-size: 0.9rem; border: 1px solid var(--border); }
        .btn-main { background: var(--primary); color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; display: inline-block; text-align: center; border: none; cursor: pointer; }
        .footer { text-align: center; margin-top: 50px; color: var(--text-muted); font-size: 0.85rem; }
        #map-container { height: 450px; width: 100%; border-radius: 12px; z-index: 1; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <div><div style="font-weight:700;">System Status</div><div style="font-size:0.9rem; margin-top:2px;" id="alert-msg">Waiting for sensor data...</div></div>
    </div>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="sw('overview')">Overview</button>
        <button class="tab-btn" onclick="sw('charts')">GPS Charts</button>
        <button class="tab-btn" onclick="sw('heatmap')">Heatmap</button>
        <button class="tab-btn" onclick="sw('history')">History</button>
        <button class="tab-btn" onclick="sw('esp32')">ESP32</button>
        <button class="tab-btn" onclick="sw('upload')">Upload</button>
        <button class="tab-btn" onclick="sw('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="dashboard-grid">
            <div class="card">
                <div class="card-header"><div class="card-title">Air Quality Index</div><span style="background:rgba(34, 197, 94, 0.2); color:#22c55e; padding:4px 10px; border-radius:20px; font-size:0.75rem; font-weight:700;">LIVE MONITOR</span></div>
                <div class="aqi-wrapper">
                    <div class="aqi-num" id="aqi-val">--</div>
                    <div class="aqi-label">US AQI Standard</div>
                    <div class="location-pill"><i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown</span></div>
                </div>
                <div style="margin-top:30px;"><div class="card-title" style="margin-bottom:15px; font-size:1rem;">Key Pollutants</div><div id="metric-container"></div></div>
            </div>
            <div class="card">
                <div class="card-title" style="margin-bottom:20px;">Health Summary</div>
                <div class="summary-grid">
                    <div class="stat-card"><div class="stat-val" id="aqi-score">--</div><div class="stat-name">AQI Level</div></div>
                    <div class="stat-card" style="border-color:rgba(245,158,11,0.3); background:rgba(245,158,11,0.1);"><div class="stat-val" style="color:#f59e0b;" id="risk-count">--</div><div class="stat-name">Risks Found</div></div>
                </div>
                <div class="card-title" style="margin-bottom:15px; font-size:1rem;">Detected Risks</div>
                <div id="risk-container"><p style="color:var(--text-muted); text-align:center; padding:20px;">Safe Conditions.</p></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <div class="card-header"><div class="card-title">AQI vs Flight Path (Bar)</div></div>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="heatmap" class="section">
        <div class="card">
            <div class="card-header"><div class="card-title">Pollution Heatmap</div></div>
            <div id="map-container"></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload History</div>
            <div id="history-container"><p style="color:var(--text-muted); text-align:center; padding:30px;">No files uploaded yet.</p></div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="dashboard-grid">
            <div class="card"><div class="card-title">Connection Info</div><p style="margin-top:20px;">Status: <span style="color:#4ade80;">● Listening...</span></p></div>
            <div class="card"><div class="card-title">Live Telemetry</div><div class="console" id="esp-console"></div></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload Data</div>
            <p style="margin-bottom:5px; font-weight:600; font-size:0.9rem; color:var(--text-muted);">Select Date</p>
            <input type="date" id="upload-date" class="date-input">
            <label class="upload-area">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size:2.5rem; color:#64748b; margin-bottom:15px; display:block;"></i>
                <div id="upload-text" style="font-weight:600; color:var(--text-muted);">Click to Browse CSV / Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-title">Export Data</div>
            <a href="/export" class="btn-main" style="margin-top:20px;">Download Full Report</a>
        </div>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js"></script>

<script>
    Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = '#334155';
    let map = null, heatLayer = null, mainChart = null;

    function sw(id) {
        document.querySelectorAll('.section').forEach(e => e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(e => e.classList.remove('active'));
        document.querySelector(`button[onclick="sw('${id}')"]`).classList.add('active');
        if(id === 'heatmap') setTimeout(initMap, 200);
    }

    document.getElementById('upload-date').valueAsDate = new Date();

    setInterval(() => { fetch('/api/data').then(r => r.json()).then(d => updateUI(d)); }, 3000);

    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        const dateInput = document.getElementById('upload-date');
        if(!file) return;
        const txt = document.getElementById('upload-text'); txt.innerText = "Uploading...";
        const fd = new FormData(); fd.append('file', file); fd.append('date', dateInput.value);
        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if(d.error) alert(d.error);
            else { txt.innerText = "Success!"; updateUI(d.data); setTimeout(()=>sw('overview'), 500); }
        } catch(e) { alert("Upload Failed. Check file format."); }
    });

    function initMap() {
        if (map) { map.invalidateSize(); return; }
        map = L.map('map-container').setView([20.5937, 78.9629], 5);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { attribution: '© OpenStreetMap, © CartoDB' }).addTo(map);
    }

    function updateUI(data) {
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('aqi-score').innerText = data.aqi;
        document.getElementById('risk-count').innerText = data.health_risks.length;
        document.getElementById('location-name').innerText = data.location_name;
        document.getElementById('alert-msg').innerText = data.aqi > 100 ? "Warning: High Pollution" : "Air Quality Good";

        const mContainer = document.getElementById('metric-container'); mContainer.innerHTML = '';
        [{k:'pm25', l:'PM 2.5', u:'ug/m3', m:100}, {k:'pm10', l:'PM 10', u:'ug/m3', m:150}, {k:'temp', l:'Temp', u:'C', m:50}, {k:'hum', l:'Hum', u:'%', m:100}].forEach(i => {
            const val = data[i.k] || 0, pct = Math.min((val/i.m)*100, 100);
            mContainer.innerHTML += `<div class="metric-row"><div class="metric-head"><span>${i.l}</span><span>${val} ${i.u}</span></div><div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div></div>`;
        });

        const rContainer = document.getElementById('risk-container');
        if(data.health_risks.length > 0) {
            rContainer.innerHTML = '';
            data.health_risks.forEach(r => rContainer.innerHTML += `<div class="risk-item"><span class="risk-name">${r.name}</span><span style="font-weight:700; color:${r.level==='High'?'#ef4444':'#f59e0b'}; font-size:0.8rem;">${r.level}</span></div>`);
        }

        const hContainer = document.getElementById('history-container');
        if(data.history && data.history.length > 0) {
            hContainer.innerHTML = '';
            data.history.forEach(h => hContainer.innerHTML += `<div class="history-row"><div><div class="h-date">${h.date}</div><div class="h-sub">${h.filename}</div></div><div style="font-weight:700; color:${h.aqi>100?'#ef4444':'#22c55e'}">AQI ${h.aqi}</div></div>`);
        }

        // CHART UPDATE
        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(3)}, ${Number(g.lon).toFixed(3)}`);
            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, { type: 'bar', data: { labels: labels, datasets: [{ label: 'AQI', data: data.chart_data.aqi, backgroundColor: '#3b82f6', borderRadius: 4 }] }, options: { responsive: true, maintainAspectRatio: false, scales: { x: { display: false } } } });
        }

        // HEATMAP UPDATE
        if(data.chart_data.gps.length > 0) {
            if(!map) initMap();
            const firstPt = data.chart_data.gps[0];
            if(firstPt.lat != 0) map.setView([firstPt.lat, firstPt.lon], 13);
            let heatPoints = data.chart_data.gps.map((pt, i) => [pt.lat, pt.lon, data.chart_data.aqi[i]/300]);
            if(heatLayer) map.removeLayer(heatLayer);
            heatLayer = L.heatLayer(heatPoints, {radius: 25, blur: 15, maxZoom: 17}).addTo(map);
        }

        document.getElementById('esp-console').innerHTML = data.esp32_log.join('<br>');
    }
</script>
</body>
</html>
"""

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
    f = request.files['file']
    dt = request.form.get('date', datetime.datetime.now().strftime('%Y-%m-%d'))
    try:
        df = read_file_safely(f)
        df = normalize_columns(df)
        for c in ['pm1','pm25','pm10','temp','hum','lat','lon']: 
            if c not in df.columns: df[c] = 0
        
        val = {k: round(df[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        valid = df[df['lat']!=0]
        loc = get_city_name(valid.iloc[0]['lat'], valid.iloc[0]['lon']) if not valid.empty else "No GPS"
        
        gps, aqis = [], []
        for i, r in df.head(50).iterrows():
            aqis.append(int((r['pm25']*2)+(r['pm10']*0.5)))
            gps.append({"lat":r['lat'], "lon":r['lon']})
            
        history_log.insert(0, {"date":dt, "filename":f.filename, "aqi":aqi})
        current_data.update({"aqi":aqi, **val, "location_name":loc, "health_risks":calc_health(val), "chart_data":{"aqi":aqis,"gps":gps}, "last_updated":datetime.datetime.now().strftime("%H:%M")})
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def sensor():
    try:
        d = request.json
        current_data.update(d)
        aqi = int((d.get('pm25',0)*2) + (d.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['health_risks'] = calc_health(current_data)
        current_data['location_name'] = get_city_name(d.get('lat',0), d.get('lon',0))
        current_data['last_updated'] = datetime.datetime.now().strftime("%H:%M")
        current_data['chart_data']['aqi'].append(aqi)
        current_data['chart_data']['gps'].append({"lat":d.get('lat',0),"lon":d.get('lon',0)})
        if len(current_data['chart_data']['aqi'])>50: 
            current_data['chart_data']['aqi'].pop(0); current_data['chart_data']['gps'].pop(0)
        current_data['esp32_log'].insert(0, f"> AQI:{aqi} | T:{d.get('temp')}")
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"error":str(e)}), 400

@app.route('/export')
def export():
    out = io.StringIO()
    out.write(f"Date,AQI,Location\n{datetime.datetime.now()},{current_data['aqi']},{current_data['location_name']}")
    mem = io.BytesIO()
    mem.write(out.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
