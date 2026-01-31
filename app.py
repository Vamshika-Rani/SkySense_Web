from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import datetime

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v112")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA ---
history_log = [] 
current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "avg_aqi": 0, "avg_pm1": 0, "avg_pm25": 0, "avg_pm10": 0, "avg_temp": 0, "avg_hum": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never"
}

# --- ROBUST FILE READER ---
def read_file_safely(file):
    # Reset pointer to start
    file.seek(0)
    
    # 1. Try Reading as CSV
    try:
        return pd.read_csv(file)
    except:
        pass
    
    # 2. Try Reading as Excel
    try:
        file.seek(0)
        return pd.read_excel(file)
    except:
        pass

    # 3. Fallback for messy CSVs
    try:
        file.seek(0)
        return pd.read_csv(file, encoding='latin1', sep=None, engine='python')
    except:
        raise ValueError("File format not recognized. Please upload a valid CSV or Excel file.")

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'lat' in c or 'lal' in c: col_map[col] = 'lat' # Fixes 'lalitude'
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
    
    # 1. Fine Particle Toxicity
    pm25_score = min(100, int(val['pm25'] * 1.2))
    risks.append({
        "name": "Fine Particle Toxicity",
        "desc": "Micro-particles entering bloodstream causing inflammation.",
        "prob": pm25_score,
        "level": "High" if pm25_score > 50 else "Moderate",
        "recs": ["Wear an N95/N99 mask outdoors", "Run HEPA air purifiers", "Avoid outdoor cardio", "Keep windows sealed"]
    })

    # 2. Upper Airway Stress
    airway_score = min(95, int((val['pm10'] * 0.8) + (20 if val['hum'] < 30 else 0)))
    risks.append({
        "name": "Upper Airway Stress",
        "desc": "Irritation of throat and nasal passages due to dust/dryness.",
        "prob": airway_score,
        "level": "High" if airway_score > 60 else "Moderate",
        "recs": ["Use a humidifier", "Saline nasal rinses", "Drink warm fluids", "Wear protective eyewear"]
    })

    # 3. Heat Stress
    heat_score = 0
    if val['temp'] > 30: heat_score = min(100, int((val['temp'] - 30) * 10))
    risks.append({
        "name": "Heat Stress Risk",
        "desc": "Potential for dehydration and heat exhaustion.",
        "prob": heat_score,
        "level": "High" if heat_score > 40 else "Low",
        "recs": ["Drink electrolytes", "Wear light clothing", "Avoid sun 12PM-4PM", "Cool showers"]
    })

    # 4. Asthma Trigger
    asthma_score = min(100, int((val['pm25'] * 0.9) + (val['pm10'] * 0.4)))
    risks.append({
        "name": "Asthma Trigger",
        "desc": "High particulate matter may trigger wheezing.",
        "prob": asthma_score,
        "level": "High" if asthma_score > 50 else "Moderate",
        "recs": ["Keep inhaler ready", "Stay indoors", "No candles/incense", "Monitor peak flow"]
    })
    return risks

# --- HTML TEMPLATE (Split to avoid Syntax Errors) ---
HTML_HEAD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Pro</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --bg: #fdfbf7; --card-bg: #ffffff; --text-main: #1c1917; --text-muted: #78716c; --primary: #0f172a; --orange: #ea580c; --danger: #dc2626; --success: #16a34a; --border: #e7e5e4; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; color: var(--text-main); letter-spacing: -0.5px; display:flex; align-items:center; gap:10px; }
        .refresh-btn { background: #e5e5e5; color: var(--text-main); border: none; padding: 10px 20px; border-radius: 30px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .alert-banner { background: #fff7ed; border: 1px solid #ffedd5; color: #9a3412; padding: 20px; border-radius: 12px; margin-bottom: 30px; display:flex; align-items:center; gap:15px; }
        .nav-tabs { display: flex; gap: 10px; background: white; padding: 8px; border-radius: 50px; margin-bottom: 30px; border: 1px solid var(--border); width: fit-content; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .tab-btn { border: none; background: transparent; padding: 10px 24px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-radius: 30px; transition: 0.2s; font-size: 0.9rem; }
        .tab-btn.active { background: var(--primary); color: white; }
        .section { display: none; animation: fadeIn 0.3s ease; }
        .section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
        .dashboard-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 25px; }
        .card { background: var(--card-bg); border-radius: 20px; padding: 30px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02); border: 1px solid var(--border); height: 100%; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .card-title { font-size: 1.1rem; font-weight: 700; color: var(--text-main); }
        .aqi-num { font-size: 5rem; font-weight: 800; color: var(--danger); line-height: 1; text-align: center; }
        .aqi-sub { text-align: center; color: var(--text-muted); margin-top: 10px; font-weight: 500; }
        .stat-row { display: flex; gap: 15px; margin-top: 30px; }
        .stat-box { flex: 1; background: #fafaf9; padding: 15px; border-radius: 12px; text-align: center; }
        .stat-val { font-size: 1.5rem; font-weight: 800; color: var(--text-main); }
        .health-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 800px) { .health-grid { grid-template-columns: 1fr; } }
        .risk-card { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 25px; border-left: 5px solid var(--danger); }
        .risk-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .risk-title { font-weight: 700; font-size: 1.05rem; }
        .risk-badge { background: #fee2e2; color: #991b1b; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; }
        .risk-desc { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 15px; }
        .progress-bg { height: 8px; background: #f5f5f4; border-radius: 4px; overflow: hidden; margin-bottom: 20px; }
        .progress-fill { height: 100%; background: var(--danger); border-radius: 4px; width: 0%; transition: width 1s; }
        .rec-box { background: #fdfbf7; padding: 15px; border-radius: 12px; }
        .rec-title { font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; }
        .rec-list { list-style: none; font-size: 0.9rem; color: var(--text-main); padding-left: 0; }
        .rec-list li { margin-bottom: 5px; position: relative; padding-left: 15px; }
        .rec-list li::before { content: "•"; color: var(--primary); font-weight: bold; position: absolute; left: 0; }
        
        /* UPDATED CLEAN UPLOAD CARD */
        .upload-card { display:block; text-align:center; padding: 40px; border: 2px dashed #d6d3d1; border-radius: 20px; background: #fafaf9; cursor: pointer; transition: 0.2s; }
        .upload-card:hover { border-color: var(--primary); background: #f0fdf4; }
        .upload-icon { font-size: 3rem; color: #d6d3d1; margin-bottom: 15px; transition:0.2s; }
        .upload-card:hover .upload-icon { color: var(--primary); }
        .date-picker { width:100%; padding:15px; border:1px solid #e7e5e4; border-radius:12px; font-size:1rem; margin-bottom:20px; font-family:'Inter',sans-serif; }
        
        #map-container { height: 450px; width: 100%; border-radius: 16px; z-index: 1; }
        .btn-primary { display:inline-block; background:#0f172a; color:white; padding:12px 25px; border-radius:8px; text-decoration:none; margin-right:10px; border:none; cursor:pointer; font-weight:600; font-size:0.9rem; }
        .btn-outline { display:inline-block; background:transparent; color:#0f172a; padding:12px 25px; border-radius:8px; text-decoration:none; border:2px solid #0f172a; font-weight:600; font-size:0.9rem; cursor:pointer; }
    </style>
</head>
"""

HTML_BODY = """
<body>
<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-cloud"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <div><strong>System Status:</strong> <span id="alert-msg">Waiting for data...</span></div>
    </div>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="sw('overview')">Overview</button>
        <button class="tab-btn" onclick="sw('gps')">GPS Charts</button>
        <button class="tab-btn" onclick="sw('heatmap')">Heatmap</button>
        <button class="tab-btn" onclick="sw('disease')">Disease Reports</button>
        <button class="tab-btn" onclick="sw('esp32')">ESP32</button>
        <button class="tab-btn" onclick="sw('upload')">Upload</button>
        <button class="tab-btn" onclick="sw('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="dashboard-grid">
            <div class="card">
                <div class="card-header"><div class="card-title">Real-Time Air Quality</div></div>
                <div class="aqi-num" id="aqi-val">--</div>
                <div class="aqi-sub">AQI (US Standard)</div>
                <div class="aqi-sub" style="margin-top:5px;"><i class="fa-solid fa-location-dot"></i> <span id="loc-name">Unknown</span></div>
                <div class="stat-row">
                    <div class="stat-box"><div class="stat-val" id="val-pm1">--</div><div style="font-size:0.8rem">PM 1.0</div></div>
                    <div class="stat-box"><div class="stat-val" id="val-pm25">--</div><div style="font-size:0.8rem">PM 2.5</div></div>
                    <div class="stat-box"><div class="stat-val" id="val-pm10">--</div><div style="font-size:0.8rem">PM 10</div></div>
                </div>
            </div>
            <div class="card">
                <div class="card-title" style="margin-bottom:20px;">Quick Health Summary</div>
                <div id="mini-risk-list">Waiting for data...</div>
            </div>
        </div>
    </div>

    <div id="gps" class="section">
        <div class="card">
            <div class="card-title">AQI Level vs GPS Location</div>
            <div style="height:400px; margin-top:20px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="heatmap" class="section">
        <div class="card">
            <div class="card-title">Pollution Heatmap</div>
            <p style="color:#78716c; font-size:0.9rem;">Scroll to zoom. Red areas indicate high pollution density.</p>
            <div id="map-container" style="margin-top:20px;"></div>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card-title" style="margin-bottom:20px;">Detailed Health Risk Analysis</div>
        <div class="health-grid" id="full-health-grid">
            <p style="color:#78716c">Upload data to see health analysis.</p>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="card">
            <div class="card-title">Live Telemetry</div>
            <div id="esp-console" style="background:#0f172a; color:#22c55e; padding:20px; border-radius:12px; font-family:monospace; height:200px; overflow-y:auto; margin-top:20px;"></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload Flight Data</div>
            <p style="color:#78716c; margin-bottom:10px;">Select the date of the flight:</p>
            <input type="date" id="upload-date" class="date-picker">
            
            <label class="upload-card">
                <i class="fa-solid fa-cloud-arrow-up upload-icon"></i>
                <div id="upload-text" style="font-weight:600; font-size:1.1rem; color:#1c1917;">Click to Upload File</div>
                <div style="color:#78716c; font-size:0.9rem; margin-top:5px;">Supports CSV & Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-title">Export Report</div>
            <p style="color:#78716c; margin-top:10px; margin-bottom:25px;">
                Download the complete dataset with calculated averages, health risks, and precautionary measures.
            </p>
            <div style="display:flex; gap:10px;">
                <a href="/export/text" class="btn-primary"><i class="fa-solid fa-file-lines"></i> Download Text Report</a>
                <button onclick="window.print()" class="btn-outline"><i class="fa-solid fa-print"></i> Print / Save as PDF</button>
            </div>
        </div>
    </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js"></script>

<script>
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
            if(d.error) { alert("Server Error: " + d.error); txt.innerText = "Upload Failed"; } 
            else { txt.innerText = "Success!"; updateUI(d.data); setTimeout(()=>sw('overview'), 500); }
        } catch(e) { alert("Upload Failed. Ensure file is CSV/Excel."); txt.innerText = "Retry"; }
    });

    function initMap() {
        if (map) { map.invalidateSize(); return; }
        map = L.map('map-container').setView([20.5937, 78.9629], 5);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', { attribution: '© OpenStreetMap' }).addTo(map);
    }

    function updateUI(data) {
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('val-pm1').innerText = data.pm1 || '--';
        document.getElementById('val-pm25').innerText = data.pm25 || '--';
        document.getElementById('val-pm10').innerText = data.pm10 || '--';
        document.getElementById('loc-name').innerText = data.location_name;
        document.getElementById('alert-msg').innerText = data.aqi > 100 ? "Poor Air Quality Detected" : "Air Quality is Safe";

        const grid = document.getElementById('full-health-grid');
        const miniList = document.getElementById('mini-risk-list');
        
        if(data.health_risks.length > 0) {
            grid.innerHTML = '';
            miniList.innerHTML = '';
            
            data.health_risks.forEach(r => {
                const color = r.level === 'High' ? '#dc2626' : '#ea580c';
                const badgeColor = r.level === 'High' ? '#fee2e2' : '#ffedd5';
                const badgeText = r.level === 'High' ? '#991b1b' : '#9a3412';
                
                grid.innerHTML += `
                <div class="risk-card" style="border-left-color:${color}">
                    <div class="risk-header"><div class="risk-title">${r.name}</div><div class="risk-badge" style="background:${badgeColor}; color:${badgeText}">${r.level} (${r.prob}%)</div></div>
                    <div class="risk-desc">${r.desc}</div>
                    <div class="progress-bg"><div class="progress-fill" style="width:${r.prob}%; background:${color}"></div></div>
                    <div class="rec-box"><div class="rec-title">RECOMMENDATIONS</div><ul class="rec-list">${r.recs.map(x => `<li>${x}</li>`).join('')}</ul></div>
                </div>`;

                miniList.innerHTML += `
                <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f5f5f4;">
                    <span style="font-weight:600;">${r.name}</span><span style="font-weight:700; color:${color}">${r.level}</span>
                </div>`;
            });
        }

        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(3)}, ${Number(g.lon).toFixed(3)}`);
            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, { type: 'bar', data: { labels: labels, datasets: [{ label: 'AQI', data: data.chart_data.aqi, backgroundColor: '#0f172a', borderRadius: 4 }] }, options: { responsive: true, maintainAspectRatio: false } });
        }

        if(data.chart_data.gps.length > 0) {
            if(!map) initMap();
            const firstPt = data.chart_data.gps[0];
            if(firstPt.lat != 0) map.setView([firstPt.lat, firstPt.lon], 13);
            let heatPoints = data.chart_data.gps.map((pt, i) => [pt.lat, pt.lon, Math.min(1.0, data.chart_data.aqi[i] / 200)]);
            if(heatLayer) map.removeLayer(heatLayer);
            heatLayer = L.heatLayer(heatPoints, {radius: 35, blur: 20, maxZoom: 15}).addTo(map);
        }

        document.getElementById('esp-console').innerHTML = data.esp32_log.join('<br>');
    }
</script>
</body>
</html>
"""

# --- BACKEND ROUTES ---

@app.route('/')
def home(): return render_template_string(HTML_HEAD + HTML_BODY)

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
        
        # Calculate Averages for Report
        avgs = {k: round(df[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int((avgs['pm25']*2) + (avgs['pm10']*0.5))
        
        valid = df[df['lat']!=0]
        loc = get_city_name(valid.iloc[0]['lat'], valid.iloc[0]['lon']) if not valid.empty else "No GPS"
        
        gps, aqis = [], []
        for i, r in df.head(50).iterrows():
            aqis.append(int((r['pm25']*2)+(r['pm10']*0.5)))
            gps.append({"lat":r['lat'], "lon":r['lon']})
            
        history_log.insert(0, {"date":dt, "filename":f.filename, "aqi":aqi})
        
        current_data.update({
            "aqi": aqi, "location_name": loc, 
            "avg_pm1": avgs['pm1'], "avg_pm25": avgs['pm25'], "avg_pm10": avgs['pm10'],
            "avg_temp": avgs['temp'], "avg_hum": avgs['hum'],
            "pm1": avgs['pm1'], "pm25": avgs['pm25'], "pm10": avgs['pm10'], 
            "health_risks": calc_health(avgs), 
            "chart_data": {"aqi":aqis,"gps":gps}, 
            "last_updated": datetime.datetime.now().strftime("%H:%M")
        })
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

@app.route('/export/text')
def export_text():
    d = current_data
    report = f"""
==================================================
SKYSENSE AIR QUALITY & HEALTH REPORT
==================================================
Date: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Location: {d['location_name']}

--------------------------------------------------
1. ENVIRONMENTAL SUMMARY (AVERAGES)
--------------------------------------------------
Air Quality Index (AQI): {d['aqi']}
Status: {'Poor' if d['aqi'] > 100 else 'Good'}

Particulate Matter:
- PM 1.0 : {d.get('avg_pm1', d.get('pm1', 0))} ug/m3
- PM 2.5 : {d.get('avg_pm25', d.get('pm25', 0))} ug/m3
- PM 10  : {d.get('avg_pm10', d.get('pm10', 0))} ug/m3

Conditions:
- Temperature: {d.get('avg_temp', d.get('temp', 0))} °C
- Humidity:    {d.get('avg_hum', d.get('hum', 0))} %

--------------------------------------------------
2. HEALTH RISK ANALYSIS & PRECAUTIONS
--------------------------------------------------
"""
    for risk in d['health_risks']:
        report += f"\n[RISK] {risk['name']} ({risk['level']})\n"
        report += f"Description: {risk['desc']}\n"
        report += "Precautions:\n"
        for rec in risk['recs']:
            report += f" - {rec}\n"
    
    report += "\n==================================================\nGenerated by SkySense System\n"
    
    return send_file(
        io.BytesIO(report.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"SkySense_Report_{datetime.datetime.now().strftime('%Y%m%d')}.txt"
    )

if __name__ == '__main__':
    app.run(debug=True)
