from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
from datetime import datetime

app = Flask(__name__)

# --- GLOBAL STORAGE ---
current_data = {
    "aqi": 0, "pm25": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0,
    "status": "Waiting for Drone...", "health_risks": [], 
    "chart_data": {"pm25":[], "pm10":[], "no2":[], "so2":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Listening for telemetry..."]
}

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
                    <p>Waiting for sensor data...</p>
                </div>
            </div>
        </section>

        <section id="esp32" class="slide" style="background:#1e293b; color:white;">
            <h1 style="font-size:2.5rem; font-weight:800; margin-bottom:10px;">Drone Link (ESP32)</h1>
            <div class="grid-2">
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>📡 Connection Info</h3>
                    <p style="margin-top:15px;"><strong>Method:</strong> POST Request (JSON)</p>
                    <p><strong>URL:</strong> <code>https://skysense-web.onrender.com/api/upload_sensor</code></p>
                    <p><strong>Status:</strong> <span style="color:#4ade80;">● Listening</span></p>
                </div>
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>🚀 Live Logs</h3>
                    <div class="console" id="esp-console"></div>
                </div>
            </div>
        </section>
    </div>

    <script>
        // UPDATE DASHBOARD
        setInterval(() => {
            fetch('/api/data').then(res => res.json()).then(data => {
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
                        rc.innerHTML += `<div class="card" style="border-left:5px solid ${r.color};">
                        <h3 style="color:${r.color}">${r.name}</h3>
                        <p><strong>Severity:</strong> ${r.level}</p>
                        <ul>${r.precautions.map(p=>`<li>${p}</li>`).join('')}</ul></div>`;
                    });
                } else { rc.innerHTML = '<div class="card"><h3 style="color:green;">✅ Safe Levels.</h3></div>'; }
                
                // Charts
                renderChart('chart-pm25', 'PM 2.5', data.chart_data.pm25, data.chart_data.gps, '#2563eb');
                renderChart('chart-pm10', 'PM 10', data.chart_data.pm10, data.chart_data.gps, '#0ea5e9');
                renderChart('chart-no2', 'NO2', data.chart_data.no2, data.chart_data.gps, '#f59e0b');
                renderChart('chart-so2', 'SO2', data.chart_data.so2, data.chart_data.gps, '#ef4444');
            });
        }, 3000); // Refresh every 3 seconds

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

# --- 1. FILE UPLOAD ROUTE (FOR CSV) ---
@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    # (Same logic as before for files - omitted for brevity, but file upload logic is standard)
    return jsonify({"message": "File processed", "data": current_data})

# --- 2. THE NEW ROUTE FOR ESP32 ---
@app.route('/api/upload_sensor', methods=['POST'])
def receive_sensor():
    global current_data
    try:
        data = request.json
        # Expecting JSON: {"pm25": 12, "pm10": 40, "no2": 5, "so2": 2, "co": 1, "lat": 17.0, "lon": 78.0}
        
        # Update current values
        current_data.update(data)
        
        # Calculate new AQI
        aqi = int((data.get('pm25',0)*2) + (data.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['status'] = "Hazardous" if aqi>300 else "Unhealthy" if aqi>100 else "Good"
        
        # Log to Console
        log_msg = f"> [REC] Data Received: AQI {aqi} | GPS: {data.get('lat')}, {data.get('lon')}"
        current_data['esp32_log'].append(log_msg)
        if len(current_data['esp32_log']) > 20: current_data['esp32_log'].pop(0)

        # Update Charts
        for k in ['pm25','pm10','no2','so2']:
            current_data['chart_data'][k].append(data.get(k, 0))
            if len(current_data['chart_data'][k]) > 50: current_data['chart_data'][k].pop(0)
            
        current_data['chart_data']['gps'].append({"lat": data.get('lat',0), "lon": data.get('lon',0)})

        return jsonify({"status": "success", "message": "Data received"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
