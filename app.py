from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
from datetime import datetime

app = Flask(__name__)

# --- GLOBAL STORAGE (Shared by File Upload & ESP32) ---
current_data = {
    "aqi": 0, "pm25": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0,
    "status": "Waiting for Data...", 
    "health_risks": [], 
    "chart_data": {"pm25":[], "pm10":[], "no2":[], "so2":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Waiting for drone telemetry..."]
}

# --- HEALTH ENGINE FUNCTION ---
def calculate_risks(val):
    risks = []
    # 1. PM2.5 CRITICAL
    if val['pm25'] > 150:
        risks.append({
            "name": "Severe Respiratory Distress (PM2.5)", "level": "CRITICAL", "color": "#dc2626",
            "precautions": [
                "Wear an N95/P100 respirator mask immediately.",
                "Evacuate to an indoor area with HEPA air filtration.",
                "Seal windows and doors to prevent ingress of particulates.",
                "Avoid all physical exertion; heart and lung strain is likely."
            ]
        })
    elif val['pm25'] > 50:
        risks.append({
            "name": "Respiratory Irritation Risk (PM2.5)", "level": "HIGH", "color": "#f97316",
            "precautions": [
                "Sensitive groups (Asthma/COPD) must stay indoors.",
                "Wear a standard pollution mask if outside for >30 mins.",
                "Run air purifiers on high mode.",
                "Keep inhalers and emergency medication accessible."
            ]
        })

    # 2. PM10 DANGER
    if val['pm10'] > 250:
        risks.append({
            "name": "Heavy Particulate Load (PM10)", "level": "HIGH", "color": "#ea580c",
            "precautions": [
                "Wear protective eyewear to prevent corneal abrasion.",
                "Cover exposed skin to avoid contact dermatitis.",
                "Avoid construction zones or dusty unpaved roads.",
                "Drink plenty of water to help clear throat irritation."
            ]
        })

    # 3. CARBON MONOXIDE (The Silent Killer)
    if val['co'] > 20:
        risks.append({
            "name": "Carbon Monoxide Poisoning Risk", "level": "DANGER", "color": "#991b1b",
            "precautions": [
                "Move to fresh air immediately (Do not wait).",
                "Check pulse and blood oxygen levels if dizziness occurs.",
                "Extinguish all open flames or combustion engines nearby.",
                "Seek emergency medical attention if confusion or headache persists."
            ]
        })

    # 4. CHEMICAL TOXICITY (NO2 / SO2)
    if val['no2'] > 100 or val['so2'] > 100:
        risks.append({
            "name": "Acidic Gas Toxicity (NO₂/SO₂)", "level": "HIGH", "color": "#ef4444",
            "precautions": [
                "Avoid deep breathing; gases can scar lung tissue.",
                "Wash eyes thoroughly with saline if burning sensation occurs.",
                "Move upwind from traffic or industrial smoke sources.",
                "Monitor for wheezing or shortness of breath."
            ]
        })

    # 5. SAFE STATE
    if not risks:
        risks.append({
            "name": "Optimal Air Quality", "level": "SAFE", "color": "#16a34a",
            "precautions": [
                "Air quality is safe for outdoor activities.",
                "Ventilate indoor spaces by opening windows.",
                "Great conditions for drone calibration flights.",
                "Continue routine monitoring to maintain safety."
            ]
        })
    return risks

# --- THE FRONTEND ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Mission Control</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --primary: #2563eb; --bg: #f8fafc; --text: #0f172a; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); overflow-x: hidden; }
        .sidebar { position: fixed; width: 260px; height: 100vh; background: #fff; padding: 30px; border-right: 1px solid #e2e8f0; z-index: 1000; }
        .logo { font-size: 1.6rem; font-weight: 800; color: var(--primary); margin-bottom: 40px; display: flex; align-items: center; gap: 10px; }
        .nav-link { display: flex; align-items: center; gap: 12px; padding: 16px; color: #64748b; text-decoration: none; font-weight: 600; border-radius: 12px; margin-bottom: 8px; transition: 0.2s; }
        .nav-link:hover, .nav-link.active { background: #eff6ff; color: var(--primary); }
        .main { margin-left: 260px; }
        .slide { min-height: 100vh; padding: 60px; border-bottom: 1px solid #e2e8f0; display: flex; flex-direction: column; justify-content: center; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
        .card { background: #fff; padding: 25px; border-radius: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .aqi-box { background: linear-gradient(135deg, #2563eb, #1e40af); color: white; padding: 40px; border-radius: 20px; text-align: center; }
        .aqi-val { font-size: 6rem; font-weight: 800; line-height: 1; margin: 20px 0; }
        .console { background: #1e293b; color: #4ade80; font-family: monospace; padding: 20px; border-radius: 12px; height: 250px; overflow-y: auto; }
        .chart-container { position: relative; height: 300px; width: 100%; }
        .upload-zone { border: 3px dashed #cbd5e1; padding: 40px; text-align: center; border-radius: 20px; cursor: pointer; background: #fff; transition: 0.3s; }
        .upload-zone:hover { border-color: var(--primary); background: #eff6ff; }
        .btn-download { display: inline-block; background: #0f172a; color: white; padding: 15px 30px; border-radius: 12px; text-decoration: none; font-weight: 600; margin-top: 20px; }
        @media(max-width: 900px) { .sidebar { width: 100%; height: auto; position: relative; } .main { margin-left: 0; } .grid-2 { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <nav class="sidebar">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <a href="#overview" class="nav-link"><i class="fa-solid fa-chart-pie"></i> Overview</a>
        <a href="#charts" class="nav-link"><i class="fa-solid fa-chart-area"></i> GPS Analytics</a>
        <a href="#health" class="nav-link"><i class="fa-solid fa-heart-pulse"></i> Health Risks</a>
        <a href="#esp32" class="nav-link"><i class="fa-solid fa-wifi"></i> Drone Link</a>
        <a href="#report" class="nav-link"><i class="fa-solid fa-file-export"></i> Report & Data</a>
    </nav>

    <div class="main">
        <section id="overview" class="slide">
            <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Mission Overview</h1>
            <div class="grid-2">
                <div class="aqi-box">
                    <h3>AIR QUALITY INDEX</h3>
                    <div class="aqi-val" id="aqi-val">--</div>
                    <span style="background:rgba(255,255,255,0.2); padding:5px 15px; border-radius:20px;" id="status-badge">Waiting...</span>
                </div>
                <div class="card">
                    <h3>Pollutant Breakdown</h3>
                    <table style="width:100%; margin-top:20px; font-size:1.1rem;">
                        <tr><td style="padding:10px 0;">PM 2.5</td><td style="font-weight:bold; text-align:right;" id="val-pm25">--</td></tr>
                        <tr><td style="padding:10px 0;">PM 10</td><td style="font-weight:bold; text-align:right;" id="val-pm10">--</td></tr>
                        <tr><td style="padding:10px 0;">NO₂</td><td style="font-weight:bold; text-align:right;" id="val-no2">--</td></tr>
                        <tr><td style="padding:10px 0;">SO₂</td><td style="font-weight:bold; text-align:right;" id="val-so2">--</td></tr>
                        <tr><td style="padding:10px 0;">CO</td><td style="font-weight:bold; text-align:right;" id="val-co">--</td></tr>
                    </table>
                </div>
            </div>
        </section>

        <section id="charts" class="slide">
             <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Flight Analytics</h1>
             <div class="grid-2" style="margin-bottom:30px;">
                <div class="card"><div class="chart-container"><canvas id="chart-pm25"></canvas></div></div>
                <div class="card"><div class="chart-container"><canvas id="chart-pm10"></canvas></div></div>
             </div>
             <div class="grid-2">
                <div class="card"><div class="chart-container"><canvas id="chart-no2"></canvas></div></div>
                <div class="card"><div class="chart-container"><canvas id="chart-so2"></canvas></div></div>
             </div>
        </section>
        
        <section id="health" class="slide">
            <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Health Risk Assessment</h1>
            <div id="risk-container" class="grid-2">
                <div class="card" style="grid-column: span 2; text-align: center; color: #94a3b8;">
                    <i class="fa-solid fa-user-doctor" style="font-size:3rem; margin-bottom:15px;"></i>
                    <p>Upload data or connect drone to see analysis.</p>
                </div>
            </div>
        </section>

        <section id="esp32" class="slide" style="background:#1e293b; color:white;">
            <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Drone Link (ESP32)</h1>
            <div class="grid-2">
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>📡 Connection Info</h3>
                    <p style="margin-top:15px;"><strong>Status:</strong> <span style="color:#4ade80;">● Active Listener</span></p>
                    <p><strong>Endpoint:</strong> <code>/api/upload_sensor</code></p>
                </div>
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>🚀 Live Logs</h3>
                    <div class="console" id="esp-console"></div>
                </div>
            </div>
        </section>

        <section id="report" class="slide">
            <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Mission Report & Data</h1>
            <div class="grid-2">
                <div class="card">
                    <h3>Option 1: Upload Data</h3>
                    <label class="upload-zone" style="margin-top:15px; display:block;">
                        <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2rem; color: #cbd5e1;"></i>
                        <p id="upload-text" style="margin-top:10px;">Select CSV / Excel File</p>
                        <input type="file" id="fileInput" style="display:none;">
                    </label>
                </div>
                <div class="card" style="text-align:center;">
                    <h3>Option 2: Generate Report</h3>
                    <p style="color:#64748b; margin:15px 0;">Download full PDF-ready mission summary.</p>
                    <a href="/export" class="btn-download"><i class="fa-solid fa-file-pdf"></i> Download Report</a>
                </div>
            </div>
        </section>
    </div>

    <script>
        // --- POLLING FOR UPDATES (For ESP32 Live View) ---
        setInterval(() => {
            fetch('/api/data').then(res => res.json()).then(data => {
                updateUI(data);
            });
        }, 3000);

        // --- FILE UPLOAD LOGIC ---
        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if(!file) return;
            const text = document.getElementById('upload-text');
            text.innerText = "Processing...";
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if(data.error) { alert(data.error); text.innerText = "Failed"; }
                else { text.innerText = "Success!"; updateUI(data.data); window.location.hash = "#overview"; }
            } catch(err) { alert(err); }
        });

        // --- CENTRAL UPDATE FUNCTION ---
        function updateUI(data) {
            document.getElementById('aqi-val').innerText = data.aqi;
            document.getElementById('status-badge').innerText = data.status;
            ['pm25','pm10','no2','so2','co'].forEach(k => {
                if(document.getElementById('val-'+k)) document.getElementById('val-'+k).innerText = data[k];
            });

            // Console
            const con = document.getElementById('esp-console');
            con.innerHTML = data.esp32_log.join('<br>');
            con.scrollTop = con.scrollHeight;

            // Risks
            const rc = document.getElementById('risk-container');
            rc.innerHTML = '';
            if(data.health_risks.length > 0) {
                data.health_risks.forEach(r => {
                    rc.innerHTML += `
                    <div class="card" style="border-left:5px solid ${r.color};">
                        <h3 style="color:${r.color}; margin-bottom:5px;">${r.name}</h3>
                        <p style="margin-bottom:10px;"><strong>Severity:</strong> <span style="background:${r.color}; color:white; padding:2px 8px; border-radius:4px;">${r.level}</span></p>
                        <strong style="display:block; margin-bottom:5px;">Precautions:</strong>
                        <ul style="padding-left:20px; color:#475569;">${r.precautions.map(p=>`<li style="margin-bottom:4px;">${p}</li>`).join('')}</ul>
                    </div>`;
                });
            } else { rc.innerHTML = '<div class="card"><h3 style="color:green;">✅ No Risks Detected.</h3></div>'; }
            
            // Charts
            renderChart('chart-pm25', 'PM 2.5', data.chart_data.pm25, data.chart_data.gps, '#2563eb');
            renderChart('chart-pm10', 'PM 10', data.chart_data.pm10, data.chart_data.gps, '#0ea5e9');
            renderChart('chart-no2', 'NO2', data.chart_data.no2, data.chart_data.gps, '#f59e0b');
            renderChart('chart-so2', 'SO2', data.chart_data.so2, data.chart_data.gps, '#ef4444');
        }

        function renderChart(id, label, data, gps, color) {
            new Chart(document.getElementById(id), {
                type: 'line',
                data: { labels: data.map((_, i) => i+1), datasets: [{ label: label, data: data, borderColor: color, fill: true, backgroundColor: color+'10' }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display:false}, title: {display:true, text:label} }, scales: {x:{display:false}} }
            });
        }
    </script>
</body>
</html>
"""

# --- BACKEND LOGIC ---
@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data(): return jsonify(current_data)

# --- 1. UPLOAD HANDLER ---
@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400

        # Process columns
        df.columns = [re.sub(r'[^a-z0-9]', '', c.lower()) for c in df.columns]
        mapper = {'pm25':'pm25', 'pm10':'pm10', 'no2':'no2', 'so2':'so2', 'co':'co', 'lat':'lat', 'latitude':'lat', 'lon':'lon', 'longitude':'lon'}
        df = df.rename(columns={c: mapper[c] for c in df.columns if c in mapper})
        for c in ['pm25','pm10','no2','so2','co']: 
            if c not in df.columns: df[c] = 0
        if 'lat' not in df.columns: df['lat'] = 0.0
        if 'lon' not in df.columns: df['lon'] = 0.0

        val = {k: round(df[k].mean(), 1) for k in ['pm25','pm10','no2','so2','co']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        # Charts & GPS
        chart_df = df.head(50)
        chart_data = {
            "pm25": chart_df['pm25'].tolist(), "pm10": chart_df['pm10'].tolist(),
            "no2": chart_df['no2'].tolist(), "so2": chart_df['so2'].tolist(),
            "gps": [{"lat": r['lat'], "lon": r['lon']} for _, r in chart_df.iterrows()]
        }
        
        # Risks
        risks = calculate_risks(val)
        
        current_data = { "aqi": aqi, **val, "status": "Hazardous" if aqi>300 else "Good", "health_risks": risks, "chart_data": chart_data, "esp32_log": current_data["esp32_log"] }
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- 2. ESP32 HANDLER ---
@app.route('/api/upload_sensor', methods=['POST'])
def receive_esp32():
    global current_data
    try:
        data = request.json
        # Merge new data
        current_data.update(data)
        
        # Recalculate AQI & Risks
        current_data['aqi'] = int((current_data.get('pm25',0)*2) + (current_data.get('pm10',0)*0.5))
        current_data['health_risks'] = calculate_risks(current_data)
        
        # Log
        log = f"> [REC] Data Received. AQI: {current_data['aqi']}"
        current_data['esp32_log'].append(log)
        if len(current_data['esp32_log']) > 20: current_data['esp32_log'].pop(0)
        
        # Update Chart Arrays
        for k in ['pm25','pm10','no2','so2']:
            current_data['chart_data'][k].append(data.get(k, 0))
            if len(current_data['chart_data'][k]) > 50: current_data['chart_data'][k].pop(0)
        current_data['chart_data']['gps'].append({"lat": data.get('lat',0), "lon": data.get('lon',0)})
        
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 400

# --- 3. REPORT EXPORT HANDLER ---
@app.route('/export')
def export_report():
    lines = [
        "===============================================",
        "           SKYSENSE MISSION REPORT             ",
        f"           Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "===============================================",
        "",
        "1. MISSION DATA SUMMARY",
        f"   AQI Level:   {current_data['aqi']}",
        f"   PM 2.5 Avg:  {current_data['pm25']} µg/m³",
        f"   PM 10 Avg:   {current_data['pm10']} µg/m³",
        f"   NO2 Avg:     {current_data['no2']} ppb",
        f"   SO2 Avg:     {current_data['so2']} ppb",
        f"   CO Avg:      {current_data['co']} ppm",
        "",
        "2. DETAILED HEALTH RISK ANALYSIS",
    ]
    
    if not current_data['health_risks']:
        lines.append("   [SAFE] No significant health risks detected.")
        lines.append("   Precautions: Maintain routine monitoring.")
    else:
        for r in current_data['health_risks']:
            lines.append(f"   [!] {r['name']} (Severity: {r['level']})")
            lines.append("       PRECAUTIONS:")
            for p in r['precautions']:
                lines.append(f"       - {p}")
            lines.append("")
            
    lines.append("===============================================")
    lines.append("Generated by SkySense Autonomous System")

    mem = io.BytesIO("\n".join(lines).encode())
    return send_file(mem, as_attachment=True, download_name="SkySense_Full_Report.txt", mimetype="text/plain")

if __name__ == '__main__':
    app.run(debug=True)
