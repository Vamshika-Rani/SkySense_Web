from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
import random
from datetime import datetime

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
current_data = {
    "aqi": 0, "pm25": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0,
    "status": "Waiting...",
    "health_risks": [],
    # Added GPS array back for your specific request
    "chart_data": {"pm25":[], "pm10":[], "no2":[], "so2":[], "co":[], "gps":[]},
    "esp32_log": ["> System Ready...", "> Waiting for connection..."],
    "last_updated": "Never"
}

# --- HEALTH ENGINE ---
def calculate_advanced_health(val):
    risks = []
    # 1. Asthma & Allergies
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
    # 3. Respiratory
    resp_prob = min(100, int((val['no2'] / 40) * 30 + (val['so2'] / 20) * 20))
    risks.append({
        "name": "Respiratory Infections",
        "prob": resp_prob,
        "level": "High" if resp_prob > 50 else "Moderate" if resp_prob > 20 else "Low",
        "symptoms": ["Shortness of breath", "Throat irritation", "Lung inflammation"],
        "recs": ["Wear N95 mask outdoors", "Avoid traffic-heavy areas", "Hydrate frequently"]
    })
    return risks

# --- THE "ATOMS" UI TEMPLATE ---
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
        :root { --primary: #3b82f6; --bg: #f3f4f6; --card: #ffffff; --text: #111827; --text-light: #6b7280; --border: #e5e7eb; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        
        /* HEADER */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .logo { font-size: 1.5rem; font-weight: 700; color: var(--primary); display: flex; align-items: center; gap: 8px; }
        .refresh-btn { background: #111827; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9rem; }

        /* ALERT BANNER */
        .alert-banner { background: #fffbeb; border: 1px solid #fcd34d; color: #92400e; padding: 20px; border-radius: 12px; margin-bottom: 25px; }
        .alert-title { font-weight: 700; display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .alert-badge { background: #fcd34d; color: #78350f; font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; }
        .rec-list { list-style: none; margin-top: 10px; font-size: 0.95rem; line-height: 1.6; }
        .rec-list li::before { content: "•"; color: #3b82f6; margin-right: 8px; }

        /* TABS */
        .tabs { display: flex; gap: 5px; background: white; padding: 5px; border-radius: 12px; margin-bottom: 25px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .tab-btn { flex: 1; border: none; background: transparent; padding: 12px; font-weight: 600; color: var(--text-light); cursor: pointer; border-radius: 8px; transition: 0.2s; text-align: center; }
        .tab-btn:hover { background: #f9fafb; }
        .tab-btn.active { background: #fff; color: var(--primary); box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid var(--border); }
        .tab-btn i { margin-right: 6px; }

        /* CONTENT */
        .section { display: none; }
        .section.active { display: block; }

        /* GRID */
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
        .card { background: var(--card); border-radius: 16px; padding: 25px; border: 1px solid var(--border); box-shadow: 0 1px 2px rgba(0,0,0,0.05); height: 100%; }
        .card h3 { font-size: 1.1rem; margin-bottom: 20px; font-weight: 700; }

        /* OVERVIEW */
        .aqi-display { text-align: center; margin-bottom: 30px; }
        .aqi-num { font-size: 5rem; font-weight: 800; color: #ea580c; line-height: 1; }
        .aqi-label { color: var(--text-light); margin-top: 5px; }
        .pollutant-row { margin-bottom: 15px; }
        .p-header { display: flex; justify-content: space-between; font-size: 0.9rem; font-weight: 600; margin-bottom: 5px; }
        .p-bar-bg { background: #f3f4f6; height: 8px; border-radius: 10px; overflow: hidden; }
        .p-bar-fill { height: 100%; background: #111827; width: 0%; transition: width 1s; }

        /* STATS */
        .stat-box { background: #eff6ff; padding: 15px; border-radius: 10px; text-align: center; flex: 1; }
        .stat-val { font-size: 1.5rem; font-weight: 700; color: var(--primary); }
        .risk-row { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border); font-size: 0.95rem; }

        /* DISEASE */
        .disease-card { margin-bottom: 20px; border-left: 5px solid #3b82f6; }
        .prob-bar { height: 6px; background: #e5e7eb; border-radius: 4px; margin: 10px 0; }
        .prob-fill { height: 100%; background: #3b82f6; border-radius: 4px; }
        .tag { display: inline-block; background: #f3f4f6; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; margin-right: 5px; color: #4b5563; }

        /* UTILS */
        .console { background: #1f2937; color: #4ade80; padding: 20px; border-radius: 8px; font-family: monospace; height: 200px; overflow-y: auto; margin-top: 15px; }
        .upload-zone { border: 2px dashed #d1d5db; padding: 50px; text-align: center; border-radius: 12px; cursor: pointer; background: #f9fafb; transition: 0.2s; }
        .upload-zone:hover { border-color: var(--primary); background: #eff6ff; }
        .btn-black { background: #111827; color: white; border: none; padding: 12px 20px; border-radius: 8px; width: 100%; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; }
        .report-summary-row { display: flex; justify-content: space-between; padding: 15px 0; border-bottom: 1px solid #f3f4f6; }
        .footer { text-align: center; margin-top: 40px; font-size: 0.8rem; color: #9ca3af; }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()"><i class="fa-solid fa-rotate"></i> Refresh Data</button>
    </div>

    <div class="alert-banner">
        <div class="alert-title"><i class="fa-solid fa-circle-info"></i> Health Alert <span class="alert-badge" id="aqi-badge">AQI --</span></div>
        <div id="alert-msg">Waiting for data analysis...</div>
        <ul class="rec-list" id="main-recs"></ul>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="switchTab('overview')"><i class="fa-solid fa-chart-pie"></i> Overview</button>
        <button class="tab-btn" onclick="switchTab('charts')"><i class="fa-solid fa-map-location-dot"></i> GPS Charts</button>
        <button class="tab-btn" onclick="switchTab('disease')"><i class="fa-solid fa-notes-medical"></i> Disease Reports</button>
        <button class="tab-btn" onclick="switchTab('esp32')"><i class="fa-solid fa-wifi"></i> ESP32</button>
        <button class="tab-btn" onclick="switchTab('upload')"><i class="fa-solid fa-upload"></i> Upload</button>
        <button class="tab-btn" onclick="switchTab('export')"><i class="fa-solid fa-file-export"></i> Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="grid-2">
            <div class="card">
                <h3>Air Quality Index</h3>
                <div class="aqi-display">
                    <div class="aqi-num" id="aqi-val">--</div>
                    <div class="aqi-label">Sensitive individuals may experience effects</div>
                </div>
                <h3>Pollutant Levels</h3>
                <div id="pollutant-bars"></div>
                <div style="font-size:0.8rem; color:#9ca3af; margin-top:20px;">Last updated: <span id="last-update">--</span></div>
            </div>
            <div class="card">
                <h3>Quick Health Summary</h3>
                <div style="display:flex; gap:15px; margin-bottom:25px;">
                    <div class="stat-box">
                        <div class="stat-val" id="aqi-score-box">--</div>
                        <div style="font-size:0.8rem; color:#6b7280;">AQI Score</div>
                    </div>
                    <div class="stat-box" style="background:#fff7ed;">
                        <div class="stat-val" style="color:#ea580c;" id="risk-count">--</div>
                        <div style="font-size:0.8rem; color:#6b7280;">Risk Factors</div>
                    </div>
                </div>
                <h3>Top Health Concerns:</h3>
                <div id="quick-risks"></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <h3>Pollutant Trends vs Flight Path</h3>
            <p style="color:#6b7280; font-size:0.9rem; margin-bottom:15px;">Hover over points to see GPS Coordinates</p>
            <div style="height:400px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card" style="background:transparent; border:none; box-shadow:none; padding:0;">
            <h3>Disease Risk Assessment</h3>
            <div id="disease-container"></div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h3><i class="fa-solid fa-microchip"></i> ESP32 Connection</h3>
                <span style="background:#dcfce7; color:#166534; padding:4px 10px; border-radius:20px; font-size:0.85rem;">● Active Listener</span>
            </div>
            <div style="background:#f3f4f6; padding:20px; border-radius:12px; margin-top:20px;">
                <strong>⚡ ESP32 Setup:</strong>
                <ol style="margin:10px 0 0 20px; font-size:0.9rem; color:#4b5563; line-height:1.6;">
                    <li>Connect ESP32 to WiFi.</li>
                    <li>POST JSON to <code>/api/upload_sensor</code>.</li>
                    <li>Format: <code>{"pm25":25.5, "lat":17.385, "lon":78.486 ...}</code></li>
                </ol>
            </div>
            <div class="console" id="esp-console"></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <h3><i class="fa-solid fa-file-csv"></i> File Upload & SD Card Data</h3>
            <label class="upload-zone">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2.5rem; color: #9ca3af; margin-bottom:15px;"></i>
                <div id="upload-text" style="font-weight:600;">Click to Browse Files</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <h3><i class="fa-solid fa-file-arrow-down"></i> Export Report</h3>
            <div style="background:#f9fafb; padding:20px; border-radius:12px; border:1px solid #e5e7eb; margin-bottom:20px;">
                <div class="report-summary-row"><span>Report Date</span><strong><script>document.write(new Date().toLocaleDateString())</script></strong></div>
                <div class="report-summary-row"><span>AQI Score</span><strong id="rep-aqi">--</strong></div>
                <div class="report-summary-row"><span>Pollutant Levels</span><strong id="rep-pol">--</strong></div>
            </div>
            <a href="/export" class="btn-black"><i class="fa-solid fa-download"></i> Download Full Report</a>
        </div>
    </div>

    <div class="footer">Made by SkySense Team | v1.0.5</div>
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

    let mainChart = null;
    function updateUI(data) {
        // OVERVIEW
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('aqi-badge').innerText = `AQI ${data.aqi}`;
        document.getElementById('aqi-score-box').innerText = data.aqi;
        document.getElementById('risk-count').innerText = data.health_risks.length;
        document.getElementById('last-update').innerText = data.last_updated;
        document.getElementById('alert-msg').innerText = data.aqi > 100 ? "Unhealthy conditions detected." : "Air quality is acceptable.";

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

        // CHARTS (UPDATED to LINE chart with GPS Tooltips)
        if(data.chart_data.pm25.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: data.chart_data.pm25.map((_, i) => `Pt ${i+1}`),
                    datasets: [
                        { label: 'PM2.5', data: data.chart_data.pm25, borderColor: '#3b82f6', fill: false, tension: 0.1 },
                        { label: 'PM10', data: data.chart_data.pm10, borderColor: '#ef4444', fill: false, tension: 0.1 }
                    ]
                },
                options: { 
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let idx = context.dataIndex;
                                    let val = context.raw;
                                    let gps = data.chart_data.gps[idx] || {lat: '?', lon: '?'};
                                    return `${context.dataset.label}: ${val} | GPS: ${gps.lat}, ${gps.lon}`;
                                }
                            }
                        }
                    }
                }
            });
        }

        // DISEASE
        const dContainer = document.getElementById('disease-container'); dContainer.innerHTML = '';
        data.health_risks.forEach(r => {
            dContainer.innerHTML += `<div class="card disease-card" style="border-color:${r.level==='High'?'#ef4444':'#3b82f6'}">
                <div style="display:flex; justify-content:space-between;"><h3>${r.name}</h3><span>${r.level}</span></div>
                <div class="prob-bar"><div class="prob-fill" style="width:${r.prob}%; background:${r.level==='High'?'#ef4444':'#3b82f6'}"></div></div>
                <div>${r.symptoms.map(s => `<span class="tag">${s}</span>`).join('')}</div>
            </div>`;
        });

        document.getElementById('esp-console').innerHTML = data.esp32_log.join('<br>');
        document.getElementById('rep-aqi').innerText = data.aqi;
        document.getElementById('rep-pol').innerText = `PM2.5: ${data.pm25}`;
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
        
        # Prepare Chart Data with GPS
        c_data = {k: df[k].head(50).tolist() for k in val.keys()}
        c_data['gps'] = [{"lat": r['lat'], "lon": r['lon']} for _, r in df.head(50).iterrows()]

        current_data.update({
            "aqi": aqi, **val, "status": "Updated",
            "health_risks": calculate_advanced_health(val),
            "chart_data": c_data,
            "last_updated": datetime.now().strftime("%H:%M:%S")
        })
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def receive_sensor():
    global current_data
    try:
        data = request.json
        current_data.update(data)
        current_data['aqi'] = int((data.get('pm25',0)*2) + (data.get('pm10',0)*0.5))
        current_data['health_risks'] = calculate_advanced_health(current_data)
        current_data['last_updated'] = datetime.now().strftime("%H:%M:%S")
        
        # Append to History
        for k in ['pm25','pm10','no2','so2','co']:
            current_data['chart_data'][k].append(data.get(k, 0))
            if len(current_data['chart_data'][k]) > 50: current_data['chart_data'][k].pop(0)
        
        # Append GPS
        current_data['chart_data']['gps'].append({"lat": data.get('lat',0), "lon": data.get('lon',0)})
        if len(current_data['chart_data']['gps']) > 50: current_data['chart_data']['gps'].pop(0)

        current_data['esp32_log'].append(f"> [REC] Data AQI: {current_data['aqi']}")
        if len(current_data['esp32_log']) > 20: current_data['esp32_log'].pop(0)
        
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route('/export')
def export_report():
    output = io.StringIO()
    output.write(f"Report Date,{datetime.now()}\nAQI,{current_data['aqi']}\n\nPollutant,Value\n")
    for k in ['pm25','pm10','no2','so2','co']: output.write(f"{k},{current_data[k]}\n")
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="SkySense_Report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
