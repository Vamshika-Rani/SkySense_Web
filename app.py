from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
import random
from datetime import datetime

# Geopy for City Names
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v10")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
history_log = [] # Stores the list of uploaded files

current_data = {
    "aqi": 0, 
    "pm1": 0, "pm25": 0, "pm10": 0, 
    "temp": 0, "hum": 0, "press": 0, "gas": 0, "alt": 0,
    "status": "Waiting...",
    "location_name": "Waiting for Data...",
    "health_risks": [],
    "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Waiting for Data stream..."],
    "last_updated": "Never",
    "connection_status": "Listening"
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
    
    if val['pm25'] > 35:
        risks.append({
            "name": "Fine Particle Toxicity", "prob": min(95, int(val['pm25']*1.5)), "level": "High",
            "symptoms": ["Deep lung irritation", "Bloodstream absorption"],
            "recs": ["Use HEPA filter", "Wear N95 mask"]
        })

    if val['pm10'] > 50:
        risks.append({
            "name": "Upper Airway Stress", "prob": min(90, int(val['pm10'])), "level": "Moderate",
            "symptoms": ["Coughing", "Throat scratchiness"],
            "recs": ["Drink water", "Avoid dusty areas"]
        })

    if val['temp'] > 30:
        risks.append({
            "name": "Heat Stress Risk", "prob": min(100, int((val['temp']-30)*10)), "level": "High",
            "symptoms": ["Dehydration", "Fatigue"],
            "recs": ["Hydrate frequently", "Seek shade"]
        })

    if val['hum'] < 40:
        risks.append({
            "name": "Viral Transmission", "prob": 65, "level": "Moderate",
            "symptoms": ["Dry mucous membranes", "Flu susceptibility"],
            "recs": ["Use humidifier", "Moisturize skin"]
        })

    asthma_score = (val['pm25'] + val['pm10']) / 2
    if asthma_score > 40:
        risks.append({
            "name": "Asthma Trigger", "prob": min(100, int(asthma_score)), "level": "High",
            "symptoms": ["Wheezing", "Shortness of breath"],
            "recs": ["Keep rescue inhaler ready", "Stay indoors"]
        })

    if not risks:
        risks.append({"name": "Optimal Conditions", "prob": 5, "level": "Safe", "symptoms": ["None"], "recs": ["Enjoy outdoor activities"]})

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
    <style>
        :root { --primary: #3b82f6; --bg: #f8fafc; --card: #ffffff; --text: #1f2937; --border: #e5e7eb; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .logo { font-size: 1.5rem; font-weight: 700; color: #2563eb; display: flex; align-items: center; gap: 8px; }
        .refresh-btn { background: #111827; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; }
        .alert-banner { background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; padding: 20px; border-radius: 12px; margin-bottom: 25px; }
        
        .tabs { display: flex; gap: 5px; background: white; padding: 5px; border-radius: 12px; margin-bottom: 25px; overflow-x: auto; }
        .tab-btn { flex: 1; min-width: 100px; border: none; background: transparent; padding: 12px; font-weight: 600; color: #6b7280; cursor: pointer; border-radius: 8px; transition: 0.2s; white-space: nowrap; }
        .tab-btn.active { background: #fff; color: #2563eb; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .section { display: none; }
        .section.active { display: block; }
        
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
        .card { background: var(--card); border-radius: 16px; padding: 25px; border: 1px solid var(--border); box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .aqi-num { font-size: 6rem; font-weight: 800; color: #ea580c; line-height: 1; text-align: center; margin-bottom: 5px; }
        
        .metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-top: 30px; }
        .metric-box { background: #f3f4f6; padding: 15px; border-radius: 12px; text-align: center; }
        .metric-val { font-weight: 700; color: #111827; font-size: 1.2rem; }
        .metric-label { font-size: 0.8rem; color: #6b7280; margin-top: 4px; font-weight:600; }

        .esp-dark-card { background: #111827; color: white; border-radius: 16px; padding: 25px; height: 100%; }
        .console-dark { background: #1f2937; color: #4ade80; padding: 20px; border-radius: 8px; font-family: monospace; height: 200px; overflow-y: auto; }
        
        .upload-zone { border: 2px dashed #d1d5db; padding: 40px; text-align: center; border-radius: 12px; cursor: pointer; background: #f9fafb; margin-top: 20px; }
        .date-input { width: 100%; padding: 12px; border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 10px; font-family: 'Inter', sans-serif; }
        
        .history-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; border-bottom: 1px solid #f3f4f6; }
        .history-item:last-child { border-bottom: none; }
        .history-date { font-weight: 700; color: #2563eb; }
        .history-details { color: #6b7280; font-size: 0.9rem; }

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
        <div style="font-weight:700; margin-bottom:10px;"><i class="fa-solid fa-circle-info"></i> System Status</div>
        <div id="alert-msg">Waiting for sensor input...</div>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('overview')">Overview</button>
        <button class="tab-btn" onclick="switchTab('charts')">GPS Charts</button>
        <button class="tab-btn" onclick="switchTab('history')">History</button>
        <button class="tab-btn" onclick="switchTab('disease')">Disease Reports</button>
        <button class="tab-btn" onclick="switchTab('esp32')">ESP32</button>
        <button class="tab-btn" onclick="switchTab('upload')">Upload</button>
        <button class="tab-btn" onclick="switchTab('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="grid-2">
            <div class="card">
                <h3>Real-Time Air Quality</h3>
                <div class="aqi-num" id="aqi-val">--</div>
                <div style="text-align:center; color:#6b7280; font-size:1.2rem; font-weight:600;">AQI (US)</div>
                <div style="text-align:center; color:#9ca3af; font-size:0.9rem; margin-top:10px;">
                    <i class="fa-solid fa-location-dot"></i> <span id="location-name">Unknown</span>
                </div>
                
                <div class="metric-grid">
                    <div class="metric-box"><div class="metric-val" id="val-pm1">--</div><div class="metric-label">PM 1.0</div></div>
                    <div class="metric-box"><div class="metric-val" id="val-pm25">--</div><div class="metric-label">PM 2.5</div></div>
                    <div class="metric-box"><div class="metric-val" id="val-pm10">--</div><div class="metric-label">PM 10</div></div>
                    <div class="metric-box"><div class="metric-val" id="val-temp">--°C</div><div class="metric-label">Temp</div></div>
                    <div class="metric-box"><div class="metric-val" id="val-hum">--%</div><div class="metric-label">Humidity</div></div>
                </div>
            </div>
            <div class="card">
                <h3>Health Risk Analysis</h3>
                <div id="quick-risks" style="margin-top:20px;"></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <h3>AQI Level vs GPS Location</h3>
            <p style="color:#6b7280; font-size:0.9rem; margin-bottom:15px;">X-Axis shows Latitude & Longitude | Tooltip shows City</p>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <h3>Uploaded Data History</h3>
            <p style="color:#6b7280; margin-bottom:20px;">List of all files uploaded, sorted by date (Latest first).</p>
            <div id="history-list">
                <p style="text-align:center; color:#9ca3af; padding:20px;">No files uploaded yet.</p>
            </div>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card" style="border:none; box-shadow:none; padding:0;">
            <div id="disease-container"></div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="grid-2">
            <div class="esp-dark-card">
                <h3><i class="fa-solid fa-satellite-dish"></i> Status</h3>
                <div style="margin-top:20px; font-size:0.9rem;">
                    <p><strong>Endpoint:</strong> <code style="background:#374151; padding:2px 6px;">/api/upload_sensor</code></p>
                    <p><strong>Status:</strong> <span style="color:#4ade80;">● Listening</span></p>
                </div>
            </div>
            <div class="esp-dark-card">
                <h3><i class="fa-solid fa-rocket"></i> Live Telemetry</h3>
                <div class="console-dark" id="esp-console"></div>
            </div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <h3>Upload Data File</h3>
            <p style="color:#6b7280; font-size:0.9rem; margin-bottom:15px;">Please select the date of data collection before uploading.</p>
            
            <input type="date" id="upload-date" class="date-input" required>
            
            <label class="upload-zone">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2rem; color: #9ca3af;"></i>
                <div id="upload-text" style="font-weight:600; margin-top:10px;">Click to Browse File</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <h3>Export Report</h3>
            <a href="/export" class="btn-black">Download Full Report</a>
        </div>
    </div>

    <div class="footer">Made by SkySense Team | v10.0</div>
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
        
        if(!dateInput.value) {
            alert("⚠️ Please select a date first!");
            e.target.value = ''; // Reset file input
            return;
        }
        
        if(!file) return;
        const txt = document.getElementById('upload-text'); txt.innerText = "Processing...";
        const fd = new FormData(); 
        fd.append('file', file);
        fd.append('date', dateInput.value); // SEND DATE

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
        document.getElementById('location-name').innerText = data.location_name;
        document.getElementById('alert-msg').innerText = data.aqi > 100 ? "Warning: Poor Air Quality" : "Air Quality is Good";

        ['pm1','pm25','pm10','temp','hum'].forEach(k => {
            if(document.getElementById('val-'+k)) document.getElementById('val-'+k).innerText = data[k];
        });

        // UPDATE HISTORY LIST
        const hContainer = document.getElementById('history-list');
        if(data.history && data.history.length > 0) {
            hContainer.innerHTML = '';
            data.history.forEach(h => {
                hContainer.innerHTML += `
                <div class="history-item">
                    <div>
                        <div class="history-date"><i class="fa-regular fa-calendar"></i> ${h.date}</div>
                        <div class="history-details">${h.filename} | ${h.location}</div>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-weight:700; color:${h.aqi > 100 ? '#ef4444' : '#22c55e'}">AQI ${h.aqi}</span>
                    </div>
                </div>`;
            });
        }

        const qContainer = document.getElementById('quick-risks'); qContainer.innerHTML = '';
        data.health_risks.forEach(r => qContainer.innerHTML += `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid #eee;">
                <span>${r.name}</span>
                <span style="font-size:0.85rem; font-weight:700; color:${r.level==='High'?'#ef4444':'#f59e0b'}">${r.level} (${r.prob}%)</span>
            </div>`);

        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map(g => `${Number(g.lat).toFixed(4)},${Number(g.lon).toFixed(4)}`);
            const cities = data.chart_data.gps.map(g => g.city || "Unknown");
            const colors = data.chart_data.aqi.map(v => v > 150 ? '#ef4444' : v > 100 ? '#f97316' : v > 50 ? '#eab308' : '#22c55e');

            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{ 
                        label: 'AQI Level', 
                        data: data.chart_data.aqi, 
                        backgroundColor: colors,
                        borderRadius: 4
                    }]
                },
                options: { 
                    responsive: true, maintainAspectRatio: false,
                    plugins: { tooltip: { callbacks: { label: function(c) { return `AQI: ${c.raw} | Area: ${cities[c.dataIndex]}`; } } } },
                    scales: { 
                        x: { title: {display:true, text:'GPS Coordinates (Latitude, Longitude)'}, ticks: {maxRotation: 45, minRotation: 45} },
                        y: { title: {display:true, text:'AQI Value'}, beginAtZero: true }
                    }
                }
            });
        }
        
        const dContainer = document.getElementById('disease-container'); dContainer.innerHTML = '';
        data.health_risks.forEach(r => {
            dContainer.innerHTML += `
            <div style="background:white; border:1px solid #e5e7eb; border-radius:12px; padding:20px; margin-bottom:20px; border-left:5px solid ${r.level==='High'?'#ef4444':'#3b82f6'};">
                <div style="display:flex; justify-content:space-between;">
                    <h3>${r.name}</h3>
                    <span style="font-weight:700; color:${r.level==='High'?'#ef4444':'#3b82f6'}">${r.level}</span>
                </div>
                <p style="font-size:0.9rem; color:#6b7280; margin-bottom:10px;">Symptoms: ${r.symptoms.join(', ')}</p>
                <ul style="padding-left:20px; margin:0; color:#4b5563;">${r.recs.map(rec => `<li>${rec}</li>`).join('')}</ul>
            </div>`;
        });

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
    # Return history along with data
    current_data['history'] = history_log
    return jsonify(current_data)

@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    user_date = request.form.get('date', datetime.now().strftime('%Y-%m-%d')) # GET DATE

    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400

        df = normalize_columns(df)
        
        all_cols = ['pm1','pm25','pm10','temp','hum','press','gas','alt','lat','lon']
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

        # --- SAVE TO HISTORY ---
        history_entry = {
            "date": user_date,
            "filename": file.filename,
            "location": loc_name,
            "aqi": aqi
        }
        history_log.append(history_entry)
        # Sort history: Latest date first
        history_log.sort(key=lambda x: x['date'], reverse=True)

        current_data.update({
            "aqi": aqi, **val, "status": "Updated",
            "location_name": loc_name,
            "health_risks": calculate_advanced_health(val),
            "chart_data": {"aqi": aqi_list, "gps": gps_list},
            "last_updated": datetime.now().strftime("%H:%M:%S"),
            "connection_status": "Connected",
            "history": history_log # Send updated history back
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
