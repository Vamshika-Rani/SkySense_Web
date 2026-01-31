from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import io
import re
from datetime import datetime

# Geopy for City Names
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_atoms_final_v12")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
history_log = [] 

current_data = {
    "aqi": 0, 
    "pm1": 0, "pm25": 0, "pm10": 0, 
    "temp": 0, "hum": 0, "press": 0, "gas": 0, "alt": 0,
    "status": "Waiting...",
    "location_name": "Waiting for Data...",
    "health_risks": [],
    "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never",
    "connection_status": "Disconnected"
}

# --- SMART COLUMN FIXER ---
def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c_lower = col.lower().strip()
        if 'pm1.0' in c_lower or 'pm1' in c_lower and 'pm10' not in c_lower: col_map[col] = 'pm1'
        elif 'pm2.5' in c_lower or 'pm25' in c_lower: col_map[col] = 'pm25'
        elif 'pm10' in c_lower: col_map[col] = 'pm10'
        elif 'temp' in c_lower: col_map[col] = 'temp'
        elif 'hum' in c_lower: col_map[col] = 'hum'
        elif 'press' in c_lower: col_map[col] = 'press'
        elif 'gas' in c_lower: col_map[col] = 'gas'
        elif 'alt' in c_lower: col_map[col] = 'alt'
        # Typo fix for your specific file
        elif 'lat' in c_lower or 'lal' in c_lower: col_map[col] = 'lat'
        elif 'lon' in c_lower or 'lng' in c_lower: col_map[col] = 'lon'
    return df.rename(columns=col_map)

# --- CITY NAME HELPER ---
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
    
    # 1. Asthma & Allergies
    asthma_score = (val['pm25'] * 1.2) + (val['pm10'] * 0.5)
    risks.append({
        "name": "Asthma & Allergies", 
        "prob": min(98, int(asthma_score)), 
        "level": "High" if asthma_score > 50 else "Moderate"
    })

    # 2. Respiratory Diseases
    resp_score = (val['pm10'] * 0.8) + (val['hum'] < 30) * 20
    risks.append({
        "name": "Respiratory Diseases", 
        "prob": min(95, int(resp_score)), 
        "level": "High" if resp_score > 60 else "Moderate"
    })

    # 3. Cardiovascular
    cardio_score = (val['pm25'] * 0.9)
    risks.append({
        "name": "Cardiovascular Diseases", 
        "prob": min(90, int(cardio_score)), 
        "level": "High" if cardio_score > 55 else "Moderate"
    })

    # 4. Heat Stress
    if val['temp'] > 30:
        risks.append({
            "name": "Heat Stress", 
            "prob": min(100, int((val['temp']-30)*10)), 
            "level": "High"
        })

    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- UI TEMPLATE (EXACT ATOMS DESIGN) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Atoms</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { 
            --bg: #f8fafc; 
            --card-bg: #ffffff; 
            --text-dark: #0f172a; 
            --text-light: #64748b; 
            --primary: #2563eb; 
            --orange: #f97316; 
            --danger: #ef4444;
            --success: #22c55e;
            --border: #e2e8f0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-dark); padding: 40px 20px; }
        .container { max-width: 1200px; margin: 0 auto; }

        /* HEADER */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; color: var(--text-dark); letter-spacing: -1px; display:flex; align-items:center; gap:10px; }
        .logo i { color: var(--primary); }
        .refresh-btn { background: var(--text-dark); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .refresh-btn:hover { background: #334155; }

        /* ALERT */
        .alert-banner { background: #fff7ed; border: 1px solid #ffedd5; color: #9a3412; padding: 15px 20px; border-radius: 12px; margin-bottom: 30px; display:flex; align-items:center; gap:15px; }
        .alert-icon { background: #fdba74; color: #7c2d12; width:30px; height:30px; display:flex; align-items:center; justify-content:center; border-radius:50%; }

        /* TABS */
        .nav-tabs { display: flex; gap: 8px; background: white; padding: 6px; border-radius: 12px; margin-bottom: 30px; border: 1px solid var(--border); width: fit-content; }
        .tab-btn { border: none; background: transparent; padding: 8px 20px; font-weight: 600; color: var(--text-light); cursor: pointer; border-radius: 8px; transition: 0.2s; font-size: 0.9rem; }
        .tab-btn:hover { background: #f1f5f9; color: var(--text-dark); }
        .tab-btn.active { background: var(--text-dark); color: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }

        /* LAYOUT */
        .section { display: none; animation: fadeIn 0.3s ease; }
        .section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

        .dashboard-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 25px; }
        @media(max-width: 850px) { .dashboard-grid { grid-template-columns: 1fr; } }

        .card { background: var(--card-bg); border-radius: 20px; padding: 30px; box-shadow: 0 4px 20px -2px rgba(0,0,0,0.05); border: 1px solid var(--border); height: 100%; position: relative; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .card-title { font-size: 1.1rem; font-weight: 700; color: var(--text-dark); }
        
        /* AQI SECTION */
        .aqi-wrapper { display: flex; align-items: center; justify-content: center; flex-direction: column; padding: 20px 0; }
        .aqi-num { font-size: 6rem; font-weight: 800; color: var(--orange); line-height: 1; letter-spacing: -2px; }
        .aqi-label { font-size: 1rem; font-weight: 600; color: var(--text-light); margin-top: 10px; }
        .location-pill { background: #f1f5f9; padding: 6px 15px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; color: var(--text-dark); margin-top: 15px; display:flex; align-items:center; gap:6px; }

        /* PROGRESS BARS */
        .metric-row { margin-bottom: 18px; }
        .metric-head { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.9rem; font-weight: 600; color: var(--text-dark); }
        .progress-track { height: 8px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }
        .progress-fill { height: 100%; background: var(--text-dark); border-radius: 4px; transition: width 1s ease; }

        /* STATS (RIGHT SIDE) */
        .summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 30px; }
        .stat-card { background: #f8fafc; padding: 20px; border-radius: 16px; text-align: center; border: 1px solid var(--border); }
        .stat-card.highlight { background: #fff7ed; border-color: #ffedd5; }
        .stat-val { font-size: 1.8rem; font-weight: 800; color: var(--primary); }
        .stat-card.highlight .stat-val { color: var(--orange); }
        .stat-name { font-size: 0.8rem; font-weight: 600; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 5px; }

        .risk-item { display: flex; justify-content: space-between; align-items: center; padding: 15px 0; border-bottom: 1px solid var(--border); }
        .risk-item:last-child { border-bottom: none; }
        .risk-name { font-weight: 600; font-size: 0.95rem; }
        .risk-badge { font-size: 0.8rem; font-weight: 700; padding: 4px 10px; border-radius: 6px; }
        .risk-badge.High { background: #fef2f2; color: var(--danger); }
        .risk-badge.Moderate { background: #fff7ed; color: var(--orange); }

        /* UPLOAD & HISTORY */
        .upload-area { border: 2px dashed #cbd5e1; padding: 50px; text-align: center; border-radius: 16px; cursor: pointer; transition: 0.2s; background: #f8fafc; }
        .upload-area:hover { border-color: var(--primary); background: #eff6ff; }
        .date-input { width: 100%; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 20px; font-family: 'Inter', sans-serif; }
        
        .history-row { display: flex; justify-content: space-between; padding: 15px; background: #fff; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 10px; align-items: center; }
        .h-date { font-weight: 700; color: var(--text-dark); }
        .h-sub { font-size: 0.85rem; color: var(--text-light); }

        /* ESP32 */
        .console { background: #0f172a; color: #4ade80; padding: 20px; border-radius: 12px; font-family: monospace; height: 200px; overflow-y: auto; font-size: 0.9rem; }

        .btn-main { background: var(--text-dark); color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; display: inline-block; text-align: center; }
        .footer { text-align: center; margin-top: 50px; color: var(--text-light); font-size: 0.85rem; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <div class="alert-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <div>
            <div style="font-weight:700; color:#9a3412;">Health Alert System</div>
            <div style="font-size:0.9rem; margin-top:2px;" id="alert-msg">Waiting for sensor data...</div>
        </div>
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
        <div class="dashboard-grid">
            
            <div class="card">
                <div class="card-header">
                    <div class="card-title">Air Quality Index</div>
                    <span style="background:#dcfce7; color:#166534; padding:4px 10px; border-radius:20px; font-size:0.75rem; font-weight:700;">LIVE MONITOR</span>
                </div>
                
                <div class="aqi-wrapper">
                    <div class="aqi-num" id="aqi-val">--</div>
                    <div class="aqi-label">US AQI Standard</div>
                    <div class="location-pill"><i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown</span></div>
                </div>

                <div style="margin-top:30px;">
                    <div class="card-title" style="margin-bottom:15px; font-size:1rem;">Key Pollutants</div>
                    <div id="metric-container"></div> </div>
                <div style="margin-top:20px; font-size:0.8rem; color:#94a3b8; text-align:center;">Last Update: <span id="last-update">--</span></div>
            </div>

            <div class="card">
                <div class="card-title" style="margin-bottom:20px;">Health Summary</div>
                
                <div class="summary-grid">
                    <div class="stat-card">
                        <div class="stat-val" id="aqi-score">--</div>
                        <div class="stat-name">AQI Level</div>
                    </div>
                    <div class="stat-card highlight">
                        <div class="stat-val" id="risk-count">--</div>
                        <div class="stat-name">Risks Found</div>
                    </div>
                </div>

                <div class="card-title" style="margin-bottom:15px; font-size:1rem;">Detected Risks</div>
                <div id="risk-container">
                    <p style="color:#94a3b8; text-align:center; padding:20px;">Safe Conditions.</p>
                </div>
            </div>

        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <div class="card-header"><div class="card-title">AQI vs Flight Path</div></div>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload History</div>
            <div id="history-container">
                <p style="color:#94a3b8; text-align:center; padding:30px;">No files uploaded yet.</p>
            </div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="dashboard-grid">
            <div class="card" style="background:#0f172a; color:white; border:none;">
                <div class="card-title" style="color:white;">Connection Info</div>
                <div style="margin-top:20px; line-height:1.8;">
                    <p><strong>Protocol:</strong> JSON over HTTP</p>
                    <p><strong>Endpoint:</strong> <code style="background:#334155; padding:2px 6px; border-radius:4px;">/api/upload_sensor</code></p>
                    <p><strong>Status:</strong> <span style="color:#4ade80;">● Listening for ESP32...</span></p>
                </div>
            </div>
            <div class="card" style="background:#0f172a; color:white; border:none;">
                <div class="card-title" style="color:white;">Live Telemetry</div>
                <div class="console" id="esp-console"></div>
            </div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload Data</div>
            <p style="margin-bottom:5px; font-weight:600; font-size:0.9rem;">Select Date</p>
            <input type="date" id="upload-date" class="date-input">
            
            <label class="upload-area">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size:2.5rem; color:#cbd5e1; margin-bottom:15px;"></i>
                <div id="upload-text" style="font-weight:600; color:#475569;">Click to Browse CSV / Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-title">Export Data</div>
            <p style="color:#64748b; margin:15px 0 25px 0;">Download a complete CSV report of the current session including all health metrics.</p>
            <a href="/export" class="btn-main">Download Full Report</a>
        </div>
    </div>

    <div class="footer">SkySense v12.0 | Atoms Design System</div>
</div>

<script>
    function switchTab(tabId) {
        document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        document.querySelector(`button[onclick="switchTab('${tabId}')"]`).classList.add('active');
    }

    setInterval(() => { fetch('/api/data').then(res => res.json()).then(data => updateUI(data)); }, 3000);

    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        const dateInput = document.getElementById('upload-date');
        
        if(!dateInput.value) { alert("Please select a date first!"); e.target.value = ''; return; }
        if(!file) return;

        const txt = document.getElementById('upload-text'); txt.innerText = "Uploading...";
        const fd = new FormData(); fd.append('file', file); fd.append('date', dateInput.value);

        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if(d.error) alert(d.error);
            else { txt.innerText = "Success!"; updateUI(d.data); setTimeout(()=>switchTab('overview'), 500); }
        } catch(e) { alert(e); }
    });

    let mainChart = null;
    function updateUI(data) {
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('aqi-score').innerText = data.aqi;
        document.getElementById('risk-count').innerText = data.health_risks.length;
        document.getElementById('location-name').innerText = data.location_name;
        document.getElementById('last-update').innerText = data.last_updated;
        document.getElementById('alert-msg').innerText = data.aqi > 100 ? "Warning: Poor air quality detected." : "Air quality is good.";

        // METRICS BARS
        const mContainer = document.getElementById('metric-container');
        mContainer.innerHTML = '';
        const items = [
            {k:'pm25', l:'PM 2.5', u:'ug/m3', m:100},
            {k:'pm10', l:'PM 10', u:'ug/m3', m:150},
            {k:'temp', l:'Temp', u:'°C', m:50},
            {k:'hum', l:'Humidity', u:'%', m:100},
            {k:'pm1', l:'PM 1.0', u:'ug/m3', m:100}
        ];
        items.forEach(i => {
            const val = data[i.k] || 0;
            const pct = Math.min((val/i.m)*100, 100);
            mContainer.innerHTML += `
            <div class="metric-row">
                <div class="metric-head"><span>${i.l}</span><span>${val} ${i.u}</span></div>
                <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
            </div>`;
        });

        // RISKS
        const rContainer = document.getElementById('risk-container');
        if(data.health_risks.length > 0) {
            rContainer.innerHTML = '';
            data.health_risks.forEach(r => {
                rContainer.innerHTML += `
                <div class="risk-item">
                    <span class="risk-name">${r.name}</span>
                    <span class="risk-badge ${r.level}">${r.level}</span>
                </div>`;
            });
        }

        // HISTORY
        if(data.history && data.history.length > 0) {
            const hContainer = document.getElementById('history-container');
            hContainer.innerHTML = '';
            data.history.forEach(h => {
                hContainer.innerHTML += `
                <div class="history-row">
                    <div>
                        <div class="h-date">${h.date}</div>
                        <div class="h-sub">${h.filename} | ${h.location}</div>
                    </div>
                    <div style="font-weight:700; color:${h.aqi>100?'#ef4444':'#22c55e'}">AQI ${h.aqi}</div>
                </div>`;
            });
        }

        // CHART
        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(4)}, ${Number(g.lon).toFixed(4)}`);
            const colors = data.chart_data.aqi.map(v => v > 100 ? '#ef4444' : '#22c55e');

            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{ label: 'AQI Level', data: data.chart_data.aqi, backgroundColor: colors, borderRadius: 4 }]
                },
                options: { 
                    responsive: true, maintainAspectRatio: false,
                    plugins: { tooltip: { callbacks: { label: function(c) { return `AQI: ${c.raw}`; } } } },
                    scales: { 
                        x: { title: {display:true, text:'GPS (Lat, Lon)'}, ticks: {maxRotation: 45, minRotation: 45} },
                        y: { beginAtZero: true }
                    }
                }
            });
        }

        document.getElementById('esp-console').innerHTML = data.esp32_log.join('<br>');
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
        all_cols = ['pm1','pm25','pm10','temp','hum','lat','lon']
        for c in all_cols: 
            if c not in df.columns: df[c] = 0

        val = {k: round(df[k].mean(), 1) for k in all_cols}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        valid_gps = df[(df['lat'] != 0) & (df['lon'] != 0)]
        loc_name = get_city_name(valid_gps.iloc[0]['lat'], valid_gps.iloc[0]['lon']) if not valid_gps.empty else "No GPS Data"

        gps_list = []
        aqi_list = []
        for i, r in df.head(50).iterrows():
            row_aqi = int((r['pm25']*2) + (r['pm10']*0.5))
            aqi_list.append(row_aqi)
            gps_list.append({
                "lat": r['lat'], "lon": r['lon'],
                "city": get_city_name(r['lat'], r['lon']) if i % 5 == 0 else loc_name
            })

        history_entry = {
            "date": user_date,
            "filename": file.filename,
            "location": loc_name,
            "aqi": aqi
        }
        history_log.append(history_entry)
        history_log.sort(key=lambda x: x['date'], reverse=True)

        current_data.update({
            "aqi": aqi, **val, "status": "Updated",
            "location_name": loc_name,
            "health_risks": calculate_advanced_health(val),
            "chart_data": {"aqi": aqi_list, "gps": gps_list},
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "connection_status": "Connected"
        })
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def receive_sensor():
    global current_data
    try:
        data = request.json
        current_data.update(data)
        
        aqi = int((data.get('pm25',0)*2) + (data.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['health_risks'] = calculate_advanced_health(current_data)
        current_data['location_name'] = get_city_name(data.get('lat',0), data.get('lon',0))
        current_data['last_updated'] = datetime.now().strftime("%H:%M:%S")

        current_data['chart_data']['aqi'].append(aqi)
        if len(current_data['chart_data']['aqi']) > 50: current_data['chart_data']['aqi'].pop(0)
        
        current_data['chart_data']['gps'].append({
            "lat": data.get('lat',0), "lon": data.get('lon',0),
            "city": current_data['location_name']
        })
        if len(current_data['chart_data']['gps']) > 50: current_data['chart_data']['gps'].pop(0)

        current_data['esp32_log'].append(f"> [REC] AQI:{aqi} | Loc:{current_data['location_name']}")
        if len(current_data['esp32_log']) > 20: current_data['esp32_log'].pop(0)
        
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route('/export')
def export_report():
    output = io.StringIO()
    output.write(f"Report Date,{datetime.now()}\nLocation,{current_data['location_name']}\nAQI,{current_data['aqi']}\n\n")
    for k in ['pm1','pm25','pm10','temp','hum','press','gas','alt']:
        output.write(f"{k},{current_data.get(k,0)}\n")
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="SkySense_Report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
