from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import io
import re
from datetime import datetime

# Geopy for City Names (Safe Import)
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_deploy_fix_v12")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
history_log = [] 

current_data = {
    "aqi": 0, 
    "pm1": 0, "pm25": 0, "pm10": 0, 
    "temp": 0, "hum": 0, 
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

    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- UI TEMPLATE (ATOMS LAYOUT) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Atoms Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { 
            --bg: #f3f6fc; 
            --card-bg: #ffffff; 
            --text-dark: #1e293b; 
            --text-gray: #64748b; 
            --primary: #2563eb; 
            --orange: #f97316; 
            --green: #22c55e;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-dark); padding: 30px; }
        .container { max-width: 1200px; margin: 0 auto; }

        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .logo { font-size: 1.5rem; font-weight: 800; color: var(--primary); letter-spacing: -0.5px; }
        .refresh-btn { background: #0f172a; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; }

        .alert-banner { background: #fff7ed; border: 1px solid #ffedd5; color: #9a3412; padding: 20px; border-radius: 12px; margin-bottom: 30px; }
        .rec-list { list-style: none; margin-left: 5px; font-size: 0.95rem; color: #9a3412; }
        .rec-list li::before { content: "•"; color: #ea580c; margin-right: 8px; font-weight: bold; }

        .nav-tabs { display: flex; gap: 10px; background: white; padding: 5px; border-radius: 10px; margin-bottom: 30px; overflow-x: auto; }
        .tab-btn { flex: 1; min-width: 100px; border: none; background: transparent; padding: 12px; font-weight: 600; color: var(--text-gray); cursor: pointer; border-radius: 8px; white-space: nowrap; }
        .tab-btn.active { background: white; color: var(--text-dark); box-shadow: 0 2px 5px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }

        .section { display: none; }
        .section.active { display: block; }

        .dashboard-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 25px; }
        @media(max-width: 800px) { .dashboard-grid { grid-template-columns: 1fr; } }

        .card { background: var(--card-bg); border-radius: 16px; padding: 30px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); border: 1px solid #f1f5f9; height: 100%; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .card-title { font-size: 1.2rem; font-weight: 700; color: var(--text-dark); }
        .status-pill { background: #ffedd5; color: #ea580c; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 700; }

        .aqi-container { text-align: center; margin-bottom: 30px; }
        .aqi-value { font-size: 6rem; font-weight: 800; color: #ea580c; line-height: 1; }
        .aqi-sub { color: var(--text-gray); margin-top: 5px; font-size: 0.95rem; }

        .pollutant-item { margin-bottom: 20px; }
        .pol-info { display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: 600; font-size: 0.9rem; }
        .bar-bg { height: 10px; background: #f1f5f9; border-radius: 5px; overflow: hidden; }
        .bar-fill { height: 100%; background: #0f172a; border-radius: 5px; width: 0%; transition: width 1s; }

        .stats-row { display: flex; gap: 15px; margin-bottom: 30px; }
        .stat-box { flex: 1; background: #eff6ff; padding: 20px; border-radius: 12px; text-align: center; }
        .stat-box.orange { background: #fff7ed; }
        .stat-num { font-size: 1.8rem; font-weight: 800; color: var(--primary); margin-bottom: 5px; }
        .stat-box.orange .stat-num { color: #ea580c; }
        .stat-label { font-size: 0.85rem; color: var(--text-gray); font-weight: 600; }

        .risk-list { margin-top: 10px; }
        .risk-item { display: flex; justify-content: space-between; align-items: center; padding: 15px 0; border-bottom: 1px solid #f1f5f9; }
        
        .upload-zone { border: 2px dashed #cbd5e1; padding: 40px; text-align: center; border-radius: 16px; cursor: pointer; background: #f8fafc; }
        .history-item { background: white; border: 1px solid #e2e8f0; padding: 15px; border-radius: 10px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
        .btn-primary { background: #0f172a; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo">SkySense <span style="color:#0f172a;">Dashboard</span></div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <strong><i class="fa-solid fa-triangle-exclamation"></i> Health Alert</strong>
        <ul class="rec-list" id="rec-list"><li>Waiting for analysis...</li></ul>
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
                    <div class="status-pill">Live Monitor</div>
                </div>
                <div class="aqi-container">
                    <div class="aqi-value" id="aqi-val">--</div>
                    <div class="aqi-sub"><i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown</span></div>
                </div>
                <div class="card-title" style="margin-bottom:20px;">Pollutant Levels</div>
                <div id="pollutant-container"></div>
            </div>
            <div class="card">
                <div class="card-title" style="margin-bottom:20px;">Quick Health Summary</div>
                <div class="stats-row">
                    <div class="stat-box"><div class="stat-num" id="aqi-score-box">--</div><div class="stat-label">AQI Score</div></div>
                    <div class="stat-box orange"><div class="stat-num" id="risk-count">--</div><div class="stat-label">Risks</div></div>
                </div>
                <div class="card-title" style="margin-bottom:15px;">Top Health Concerns:</div>
                <div class="risk-list" id="risk-list-container"></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <div class="card-header"><div class="card-title">Pollutant Trends vs Flight Path</div></div>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Data Upload History</div>
            <div id="history-container"><p style="color:#94a3b8; text-align:center;">No uploads yet.</p></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload New Data</div>
            <input type="date" id="upload-date" style="padding:10px; border:1px solid #cbd5e1; border-radius:8px; width:100%; margin-bottom:20px;">
            <label class="upload-zone">
                <div id="upload-text" style="font-weight:600; color:#475569;">Click to Browse CSV/Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="dashboard-grid">
            <div class="card" style="background:#0f172a; color:white;">
                <div class="card-title" style="color:white;">Connection Status</div>
                <p>Status: <span style="color:#4ade80;">● Listening</span></p>
            </div>
            <div class="card" style="background:#0f172a; color:white;">
                <div class="card-title" style="color:white;">Live Logs</div>
                <div style="font-family:monospace; color:#4ade80; height:150px; overflow-y:auto;" id="esp-console"></div>
            </div>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-title">Export Report</div>
            <a href="/export" class="btn-primary" style="margin-top:20px;">Download Report</a>
        </div>
    </div>
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
        if(!dateInput.value) { alert("Please select a date first!"); return; }
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
        document.getElementById('aqi-score-box').innerText = data.aqi;
        document.getElementById('risk-count').innerText = data.health_risks.length;
        document.getElementById('location-name').innerText = data.location_name;

        const polContainer = document.getElementById('pollutant-container');
        polContainer.innerHTML = '';
        const metrics = [
            {k:'pm25', l:'PM 2.5', u:'ug/m3', max:100},
            {k:'pm10', l:'PM 10', u:'ug/m3', max:150},
            {k:'temp', l:'Temperature', u:'C', max:50},
            {k:'hum', l:'Humidity', u:'%', max:100},
            {k:'pm1', l:'PM 1.0', u:'ug/m3', max:100}
        ];
        metrics.forEach(m => {
            const val = data[m.k] || 0;
            const pct = Math.min((val/m.max)*100, 100);
            polContainer.innerHTML += `
            <div class="pollutant-item">
                <div class="pol-info"><span>${m.l}</span><span>${val} ${m.u}</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:${pct}%"></div></div>
            </div>`;
        });

        const rContainer = document.getElementById('risk-list-container');
        rContainer.innerHTML = '';
        const recList = document.getElementById('rec-list');
        recList.innerHTML = '';
        
        if(data.health_risks.length > 0) {
            data.health_risks.forEach(r => {
                rContainer.innerHTML += `
                <div class="risk-item">
                    <span style="font-weight:600;">${r.name}</span>
                    <span style="font-weight:700; color:${r.level==='High'?'#ef4444':'#f97316'}">${r.prob}%</span>
                </div>`;
            });
            recList.innerHTML = `<li>Wear a mask outdoors.</li><li>Limit exercise.</li>`;
        } else {
            rContainer.innerHTML = `<div style="padding:20px; text-align:center; color:#22c55e;">Air is Safe.</div>`;
            recList.innerHTML = `<li>Air quality is good.</li><li>Enjoy the outdoors.</li>`;
        }

        if(data.history && data.history.length > 0) {
            const hContainer = document.getElementById('history-container');
            hContainer.innerHTML = '';
            data.history.forEach(h => {
                hContainer.innerHTML += `
                <div class="history-item">
                    <div><strong>${h.date}</strong> - ${h.filename}</div>
                    <span style="font-weight:700;">AQI ${h.aqi}</span>
                </div>`;
            });
        }

        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(4)}, ${Number(g.lon).toFixed(4)}`);
            const cities = data.chart_data.gps.map(g => g.city || "Unknown");
            const colors = data.chart_data.aqi.map(v => v > 100 ? '#ef4444' : '#22c55e');

            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{ label: 'AQI', data: data.chart_data.aqi, backgroundColor: colors, borderRadius: 4 }]
                },
                options: { 
                    responsive: true, maintainAspectRatio: false,
                    plugins: { tooltip: { callbacks: { label: function(c) { return `AQI: ${c.raw} | ${cities[c.dataIndex]}`; } } } }
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
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="SkySense_Report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
