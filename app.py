from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
import random
from datetime import datetime

# Try to import geopy for City Names (Fallback if missing)
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_app_v2")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
current_data = {
    "aqi": 0, "pm25": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0,
    "status": "Waiting...",
    "location_name": "Unknown Location",
    "health_risks": [],
    "chart_data": {"pm25":[], "pm10":[], "gps":[]},
    "esp32_log": [],
    "last_updated": "Never",
    "connection_status": "Disconnected"
}

# --- HELPER: GPS TO CITY NAME ---
def get_city_name(lat, lon):
    if not geolocator: return "Location Svc Unavailable"
    try:
        # Simple caching could go here, but for now we call direct
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en')
        if location:
            address = location.raw.get('address', {})
            return address.get('suburb') or address.get('city') or address.get('town') or "Unknown Area"
    except:
        return "Unknown Area"
    return "Unknown Area"

# --- HEALTH ENGINE ---
def calculate_advanced_health(val):
    risks = []
    # 1. Asthma
    asthma_prob = min(100, int((val['pm25'] / 35) * 20 + (val['pm10'] / 50) * 10))
    risks.append({
        "name": "Asthma & Allergies",
        "prob": asthma_prob,
        "level": "High" if asthma_prob > 50 else "Moderate" if asthma_prob > 20 else "Low",
        "symptoms": ["Wheezing", "Coughing", "Runny nose", "Itchy eyes"],
        "recs": ["Keep rescue inhaler handy", "Stay indoors during high pollution", "Use air purifier"]
    })
    # 2. Cardiovascular
    cardio_prob = min(100, int((val['pm25'] / 35) * 15 + (val['co'] / 4) * 20))
    risks.append({
        "name": "Cardiovascular Diseases",
        "prob": cardio_prob,
        "level": "High" if cardio_prob > 50 else "Moderate" if cardio_prob > 20 else "Low",
        "symptoms": ["Chest pain", "Irregular heartbeat", "Fatigue", "Dizziness"],
        "recs": ["Monitor blood pressure", "Avoid strenuous outdoor exercise", "Consult cardiologist"]
    })
    return risks

# --- UI TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Autonomous Air Quality</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        :root { --primary: #3b82f6; --bg: #f8fafc; --card: #ffffff; --text: #1f2937; --border: #e5e7eb; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .logo { font-size: 1.5rem; font-weight: 700; color: #2563eb; display: flex; align-items: center; gap: 8px; }
        .refresh-btn { background: #111827; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; }
        
        .alert-banner { background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; padding: 20px; border-radius: 12px; margin-bottom: 25px; }
        .alert-badge { background: #fcd34d; color: #78350f; font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; font-weight: 600; }
        .rec-list { list-style: none; margin-top: 10px; font-size: 0.9rem; line-height: 1.6; }
        .rec-list li::before { content: "•"; color: #3b82f6; margin-right: 8px; }

        .tabs { display: flex; gap: 5px; background: white; padding: 5px; border-radius: 12px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); overflow-x: auto; }
        .tab-btn { flex: 1; min-width: 100px; border: none; background: transparent; padding: 12px; font-weight: 600; color: #6b7280; cursor: pointer; border-radius: 8px; transition: 0.2s; text-align: center; white-space: nowrap; }
        .tab-btn:hover { background: #f9fafb; }
        .tab-btn.active { background: #fff; color: #2563eb; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid var(--border); }

        .section { display: none; }
        .section.active { display: block; }
        
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
        .card { background: var(--card); border-radius: 16px; padding: 25px; border: 1px solid var(--border); box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .card h3 { font-size: 1.1rem; margin-bottom: 20px; font-weight: 700; display:flex; align-items:center; gap:10px; }

        .aqi-num { font-size: 5rem; font-weight: 800; color: #ea580c; line-height: 1; text-align: center; margin-bottom: 10px; }
        .pollutant-row { margin-bottom: 15px; }
        .p-header { display: flex; justify-content: space-between; font-size: 0.9rem; font-weight: 600; margin-bottom: 5px; }
        .p-bar-bg { background: #f3f4f6; height: 8px; border-radius: 10px; overflow: hidden; }
        .p-bar-fill { height: 100%; background: #111827; width: 0%; transition: width 1s; }
        .stat-box { background: #eff6ff; padding: 15px; border-radius: 10px; text-align: center; flex: 1; }
        .stat-val { font-size: 1.5rem; font-weight: 700; color: #2563eb; }
        .risk-row { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border); font-size: 0.95rem; }

        /* ESP32 STYLES */
        .esp-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .status-badge { background: #f3f4f6; color: #6b7280; padding: 6px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
        .status-badge.connected { background: #dcfce7; color: #166534; }
        .connect-btn { background: #111827; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 8px; }
        .setup-box { background: #eff6ff; border: 1px solid #dbeafe; border-radius: 8px; padding: 20px; margin-top: 20px; }
        .setup-list { margin: 10px 0 0 20px; color: #4b5563; font-size: 0.9rem; line-height: 1.8; }
        .code-snippet { background: #fff; padding: 2px 6px; border-radius: 4px; border: 1px solid #e5e7eb; font-family: monospace; color: #d946ef; font-size: 0.85rem; }

        .upload-zone { border: 2px dashed #d1d5db; padding: 50px; text-align: center; border-radius: 12px; cursor: pointer; background: #f9fafb; transition: 0.2s; }
        .upload-zone:hover { border-color: #3b82f6; background: #eff6ff; }
        .btn-black { background: #111827; color: white; border: none; padding: 12px 20px; border-radius: 8px; width: 100%; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; }
        .footer { text-align: center; margin-top: 40px; font-size: 0.8rem; color: #9ca3af; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <div style="font-weight:700; margin-bottom:10px; display:flex; align-items:center; gap:10px;">
            <i class="fa-solid fa-circle-info"></i> Health Alert <span class="alert-badge" id="aqi-badge">AQI --</span>
        </div>
        <div id="alert-msg" style="margin-bottom:10px;">Air quality analysis pending...</div>
        <div style="font-weight:600; font-size:0.9rem;">Recommended Actions:</div>
        <ul class="rec-list" id="main-recs"></ul>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('overview')">Overview</button>
        <button class="tab-btn" onclick="switchTab('charts')">GPS Charts</button>
        <button class="tab-btn" onclick="switchTab('trends')">Historical Trends</button> <button class="tab-btn" onclick="switchTab('disease')">Disease Reports</button>
        <button class="tab-btn" onclick="switchTab('esp32')">ESP32</button>
        <button class="tab-btn" onclick="switchTab('upload')">Upload</button>
        <button class="tab-btn" onclick="switchTab('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="grid-2">
            <div class="card">
                <h3>Air Quality Index</h3>
                <div class="aqi-num" id="aqi-val">--</div>
                <div style="text-align:center; color:#6b7280; font-size:0.9rem; margin-bottom:30px;">
                    <i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown Location</span>
                </div>
                <h3>Pollutant Levels</h3>
                <div id="pollutant-bars"></div>
                <div style="font-size:0.8rem; color:#9ca3af; margin-top:20px;">Last updated: <span id="last-update">--</span></div>
            </div>
            <div class="card">
                <h3>Quick Health Summary</h3>
                <div style="display:flex; gap:15px; margin-bottom:25px;">
                    <div class="stat-box"><div class="stat-val" id="aqi-score-box">--</div><div style="font-size:0.8rem;">AQI Score</div></div>
                    <div class="stat-box" style="background:#fff7ed;"><div class="stat-val" style="color:#ea580c;" id="risk-count">--</div><div style="font-size:0.8rem;">Risk Factors</div></div>
                </div>
                <h3>Top Health Concerns:</h3>
                <div id="quick-risks"></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <h3>Pollutant Levels vs Location</h3>
            <p style="color:#6b7280; font-size:0.9rem; margin-bottom:15px;">Hover over bars to see Area/City Names</p>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="trends" class="section">
        <div class="card">
            <h3><i class="fa-solid fa-chart-line"></i> Historical Trend Analysis</h3>
            <p style="color:#6b7280; margin-bottom:20px;">Upload long-term data (CSV with Year/Date) to visualize trends.</p>
            
            <label class="upload-zone" style="padding: 30px; margin-bottom: 20px;">
                <i class="fa-solid fa-calendar-days" style="font-size: 2rem; color: #9ca3af; margin-bottom:10px;"></i>
                <div style="font-weight:600;">Upload Historical CSV</div>
                <input type="file" id="historyInput" style="display:none;">
            </label>

            <div style="height:400px;"><canvas id="trendChart"></canvas></div>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card" style="border:none; box-shadow:none; background:transparent; padding:0;">
            <div id="disease-container"></div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="card">
            <div class="esp-header">
                <h3><i class="fa-solid fa-wifi"></i> ESP32 Connection</h3>
                <div class="status-badge" id="conn-status">Disconnected</div>
            </div>
            <button class="connect-btn" onclick="simulateConnect()"><i class="fa-solid fa-wifi"></i> Connect</button>
            <div class="setup-box">
                <div style="font-weight:600; color:#1e40af; display:flex; align-items:center; gap:8px;">
                    <i class="fa-solid fa-bolt"></i> ESP32 Setup:
                </div>
                <ol class="setup-list">
                    <li>Connect ESP32 to WiFi.</li>
                    <li>Endpoint: <code>/api/upload_sensor</code></li>
                    <li>JSON: <code>{"pm25":25.5, "lat":17.38, "lon":78.48}</code></li>
                </ol>
            </div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <h3><i class="fa-solid fa-file-arrow-up"></i> File Upload</h3>
            <label class="upload-zone">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2.5rem; color: #9ca3af; margin-bottom:15px;"></i>
                <div id="upload-text" style="font-weight:600;">Click to Browse Files</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <h3><i class="fa-solid fa-file-export"></i> Export Report</h3>
            <div style="background:#f9fafb; padding:20px; border-radius:12px; border:1px solid #e5e7eb; margin-bottom:20px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;"><span>Report Date</span><strong><script>document.write(new Date().toLocaleDateString())</script></strong></div>
                <div style="display:flex; justify-content:space-between;"><span>AQI Score</span><strong id="rep-aqi">--</strong></div>
            </div>
            <a href="/export" class="btn-black">Download Full Report</a>
        </div>
    </div>

    <div class="footer">Made by SkySense Team | v4.0</div>
</div>

<script>
    function switchTab(tabId) {
        document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        document.querySelector(`button[onclick="switchTab('${tabId}')"]`).classList.add('active');
    }

    function simulateConnect() {
        const badge = document.getElementById('conn-status');
        badge.innerText = "Listening...";
        setTimeout(() => { badge.innerText = "Connected"; badge.classList.add('connected'); }, 1500);
    }

    setInterval(() => { fetch('/api/data').then(res => res.json()).then(data => updateUI(data)); }, 3000);

    // --- MAIN UPLOAD ---
    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if(!file) return;
        const txt = document.getElementById('upload-text'); txt.innerText = "Uploading...";
        const fd = new FormData(); fd.append('file', file);
        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if(d.error) alert(d.error);
            else { txt.innerText = "Success!"; updateUI(d.data); setTimeout(()=>switchTab('overview'), 500); }
        } catch(e) { alert(e); }
    });

    // --- HISTORICAL UPLOAD ---
    let trendChart = null;
    document.getElementById('historyInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if(!file) return;
        const fd = new FormData(); fd.append('file', file);
        try {
            const res = await fetch('/upload_history', { method: 'POST', body: fd });
            const d = await res.json();
            if(d.error) alert(d.error);
            else { renderTrendChart(d.labels, d.values); }
        } catch(e) { alert("Error uploading history: " + e); }
    });

    function renderTrendChart(labels, values) {
        const ctx = document.getElementById('trendChart').getContext('2d');
        if(trendChart) trendChart.destroy();
        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Historical AQI Trend',
                    data: values,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    let mainChart = null;

    function updateUI(data) {
        // OVERVIEW
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('aqi-badge').innerText = `AQI ${data.aqi}`;
        document.getElementById('aqi-score-box').innerText = data.aqi;
        document.getElementById('risk-count').innerText = data.health_risks.length;
        document.getElementById('last-update').innerText = data.last_updated;
        document.getElementById('location-name').innerText = data.location_name; // CITY NAME HERE
        
        if(data.connection_status === 'Connected') {
            document.getElementById('conn-status').innerText = 'Connected';
            document.getElementById('conn-status').classList.add('connected');
        }

        const pContainer = document.getElementById('pollutant-bars'); pContainer.innerHTML = '';
        ['pm25','pm10','no2','so2','co'].forEach(k => {
            const pct = Math.min((data[k]/(k==='co'?10:150))*100, 100);
            pContainer.innerHTML += `<div class="pollutant-row"><div class="p-header"><span>${k.toUpperCase()}</span><span>${data[k]}</span></div><div class="p-bar-bg"><div class="p-bar-fill" style="width:${pct}%"></div></div></div>`;
        });

        const qContainer = document.getElementById('quick-risks'); qContainer.innerHTML = '';
        data.health_risks.forEach(r => qContainer.innerHTML += `<div class="risk-row"><span>${r.name}</span><strong>${r.prob}%</strong></div>`);

        const recList = document.getElementById('main-recs'); recList.innerHTML = '';
        if(data.health_risks.length > 0) data.health_risks[0].recs.forEach(r => recList.innerHTML += `<li>${r}</li>`);
        else recList.innerHTML = "<li>Safe for outdoor activities.</li>";

        // CHART: GPS + CITY NAME TOOLTIP
        if(data.chart_data.pm25.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const colors = data.chart_data.pm25.map(val => val > 100 ? '#ef4444' : val > 50 ? '#eab308' : '#22c55e');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(4)}, ${Number(g.lon).toFixed(4)}`);
            const cityNames = data.chart_data.gps.map(g => g.city || "Unknown Area");

            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'PM2.5 Level',
                        data: data.chart_data.pm25,
                        backgroundColor: colors,
                        borderRadius: 4
                    }]
                },
                options: { 
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let idx = context.dataIndex;
                                    return `PM2.5: ${context.raw} | Area: ${cityNames[idx]}`;
                                }
                            }
                        }
                    },
                    scales: { 
                        x: { title: {display:true, text:'GPS Coordinates'}, ticks: {maxRotation: 45, minRotation: 45} },
                        y: { title: {display:true, text:'Concentration (µg/m³)'} }
                    }
                }
            });
        }

        // DISEASE CARDS
        const dContainer = document.getElementById('disease-container'); dContainer.innerHTML = '';
        data.health_risks.forEach(r => {
            dContainer.innerHTML += `
            <div style="background:white; border:1px solid #e5e7eb; border-radius:12px; padding:20px; margin-bottom:20px; border-left:5px solid ${r.level==='High'?'#ef4444':'#3b82f6'}; box-shadow:0 1px 2px rgba(0,0,0,0.05);">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <h3 style="margin:0; font-size:1.1rem; color:#1f2937;">${r.name}</h3>
                    <span style="background:${r.level==='High'?'#fee2e2':'#dbeafe'}; color:${r.level==='High'?'#991b1b':'#1e40af'}; padding:2px 10px; border-radius:12px; font-size:0.8rem; font-weight:600;">${r.level}</span>
                </div>
                <div style="font-size:0.9rem; color:#6b7280; margin-bottom:5px;">Risk Probability: <strong>${r.prob}%</strong></div>
                <div style="height:6px; background:#f3f4f6; border-radius:4px; margin-bottom:15px;"><div style="height:100%; width:${r.prob}%; background:${r.level==='High'?'#ef4444':'#3b82f6'}; border-radius:4px;"></div></div>
                <div style="margin-bottom:15px;">${r.symptoms.map(s => `<span style="display:inline-block; background:#f3f4f6; padding:4px 10px; border-radius:15px; font-size:0.75rem; color:#4b5563; margin-right:5px;">${s}</span>`).join('')}</div>
                <ul style="font-size:0.9rem; color:#4b5563; padding-left:20px; margin:0;">${r.recs.map(rec => `<li>${rec}</li>`).join('')}</ul>
            </div>`;
        });
        
        document.getElementById('rep-aqi').innerText = data.aqi;
    }
</script>
</body>
</html>
"""

# --- BACKEND ROUTES ---

@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data(): return jsonify(current_data)

# --- ROUTE 1: REGULAR UPLOAD ---
@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400

        df.columns = [re.sub(r'[^a-z0-9]', '', c.lower()) for c in df.columns]
        mapper = {'pm25':'pm25', 'pm10':'pm10', 'no2':'no2', 'so2':'so2', 'co':'co', 'lat':'lat', 'lon':'lon'}
        df = df.rename(columns={c: mapper[c] for c in df.columns if c in mapper})
        for c in ['pm25','pm10','no2','so2','co']: 
            if c not in df.columns: df[c] = 0
        if 'lat' not in df.columns: df['lat'] = 0.0
        if 'lon' not in df.columns: df['lon'] = 0.0

        val = {k: round(df[k].mean(), 1) for k in ['pm25','pm10','no2','so2','co']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        # Determine Location (using first/avg point)
        lat_center = df['lat'].mean()
        lon_center = df['lon'].mean()
        loc_name = get_city_name(lat_center, lon_center)

        # Chart Data (Add City Name to each point for tooltip)
        c_data = {k: df[k].head(50).tolist() for k in val.keys()}
        gps_list = []
        for _, r in df.head(50).iterrows():
            gps_list.append({
                "lat": r['lat'], 
                "lon": r['lon'],
                "city": get_city_name(r['lat'], r['lon']) if _ % 5 == 0 else loc_name # optimize calls
            })
        c_data['gps'] = gps_list

        current_data.update({
            "aqi": aqi, **val, "status": "Updated",
            "location_name": loc_name,
            "health_risks": calculate_advanced_health(val),
            "chart_data": c_data,
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "connection_status": "Connected"
        })
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- ROUTE 2: HISTORICAL UPLOAD ---
@app.route('/upload_history', methods=['POST'])
def upload_history():
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    try:
        df = pd.read_csv(file)
        # Look for date/year/month columns
        date_col = next((c for c in df.columns if 'date' in c.lower() or 'year' in c.lower() or 'time' in c.lower()), None)
        val_col = next((c for c in df.columns if 'aqi' in c.lower() or 'pm25' in c.lower()), None)
        
        if not date_col or not val_col:
            return jsonify({"error": "CSV must have 'Date' and 'AQI' columns"}), 400
            
        df = df.sort_values(by=date_col)
        return jsonify({
            "labels": df[date_col].astype(str).tolist(),
            "values": df[val_col].tolist()
        })
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- ROUTE 3: ESP32 ---
@app.route('/api/upload_sensor', methods=['POST'])
def receive_sensor():
    global current_data
    try:
        data = request.json
        current_data.update(data)
        current_data['aqi'] = int((data.get('pm25',0)*2) + (data.get('pm10',0)*0.5))
        current_data['health_risks'] = calculate_advanced_health(current_data)
        current_data['last_updated'] = datetime.now().strftime("%H:%M:%S")
        current_data['connection_status'] = "Connected"
        
        # Get City Name (Live)
        current_data['location_name'] = get_city_name(data.get('lat',0), data.get('lon',0))

        # Append Data.
        for k in ['pm25','pm10','no2','so2','co']:
            current_data['chart_data'][k].append(data.get(k, 0))
            if len(current_data['chart_data'][k]) > 50: current_data['chart_data'][k].pop(0)
        
        current_data['chart_data']['gps'].append({
            "lat": data.get('lat',0), "lon": data.get('lon',0),
            "city": current_data['location_name']
        })
        if len(current_data['chart_data']['gps']) > 50: current_data['chart_data']['gps'].pop(0)

        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route('/export')
def export_report():
    output = io.StringIO()
    output.write(f"Report Date,{datetime.now()}\nLocation,{current_data['location_name']}\nAQI,{current_data['aqi']}\n\nPollutant,Value\n")
    for k in ['pm25','pm10','no2','so2','co']: output.write(f"{k},{current_data[k]}\n")
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="SkySense_Report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
