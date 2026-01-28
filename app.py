from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
from datetime import datetime

app = Flask(__name__)

# --- GLOBAL STORAGE (For Report Generation) ---
current_data = {
    "aqi": 0, "pm25": 0, "pm10": 0, "no2": 0, "so2": 0, "co": 0,
    "status": "Waiting...", "health_risks": [], 
    "chart_data": {"pm25":[], "pm10":[], "no2":[], "so2":[], "gps":[]}
}

# --- THE FRONTEND (HTML/CSS/JS) ---
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
        
        /* SIDEBAR */
        .sidebar { position: fixed; width: 260px; height: 100vh; background: #fff; padding: 30px; border-right: 1px solid #e2e8f0; z-index: 1000; }
        .logo { font-size: 1.6rem; font-weight: 800; color: var(--primary); margin-bottom: 40px; display: flex; align-items: center; gap: 10px; }
        .nav-link { display: flex; align-items: center; gap: 12px; padding: 16px; color: #64748b; text-decoration: none; font-weight: 600; border-radius: 12px; margin-bottom: 8px; transition: 0.2s; }
        .nav-link:hover, .nav-link.active { background: #eff6ff; color: var(--primary); }
        
        /* MAIN CONTENT */
        .main { margin-left: 260px; }
        .slide { min-height: 100vh; padding: 60px; border-bottom: 1px solid #e2e8f0; display: flex; flex-direction: column; justify-content: center; }
        .slide-title { font-size: 2.5rem; font-weight: 800; margin-bottom: 10px; }
        .slide-desc { color: #64748b; margin-bottom: 40px; font-size: 1.1rem; }
        
        /* GRIDS & CARDS */
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
        .grid-4 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #fff; padding: 25px; border-radius: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        
        /* AQI BOX */
        .aqi-box { background: linear-gradient(135deg, #2563eb, #1e40af); color: white; padding: 40px; border-radius: 20px; text-align: center; }
        .aqi-val { font-size: 6rem; font-weight: 800; line-height: 1; margin: 20px 0; }
        .badge { background: rgba(255,255,255,0.2); padding: 8px 16px; border-radius: 30px; font-weight: 600; }
        
        /* CHARTS */
        .chart-container { position: relative; height: 300px; width: 100%; }
        
        /* ESP32 CONSOLE */
        .console { background: #1e293b; color: #4ade80; font-family: monospace; padding: 20px; border-radius: 12px; height: 200px; overflow-y: auto; margin-top: 20px; }
        
        /* UPLOAD & DOWNLOAD */
        .upload-zone { border: 3px dashed #cbd5e1; padding: 40px; text-align: center; border-radius: 20px; cursor: pointer; background: #fff; transition: 0.3s; }
        .upload-zone:hover { border-color: var(--primary); background: #eff6ff; }
        .btn-download { display: inline-block; background: #0f172a; color: white; padding: 15px 30px; border-radius: 12px; text-decoration: none; font-weight: 600; margin-top: 20px; }
        .btn-download:hover { opacity: 0.9; }

        /* RESPONSIVE */
        @media(max-width: 900px) {
            .sidebar { width: 100%; height: auto; position: relative; }
            .main { margin-left: 0; }
            .grid-2, .grid-4 { grid-template-columns: 1fr; }
        }
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
            <div>
                <h1 class="slide-title">Mission Overview</h1>
                <p class="slide-desc">Real-time Air Quality & Telemetry Dashboard</p>
            </div>
            <div class="grid-2">
                <div class="aqi-box">
                    <h3>AIR QUALITY INDEX</h3>
                    <div class="aqi-val" id="aqi-val">--</div>
                    <span class="badge" id="status-badge">Waiting for Data...</span>
                </div>
                <div class="card">
                    <h3>Pollutant Breakdown</h3>
                    <table style="width:100%; margin-top:20px; font-size:1.1rem; border-collapse: collapse;">
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:15px 0;">PM 2.5</td><td style="text-align:right; font-weight:bold;" id="val-pm25">--</td></tr>
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:15px 0;">PM 10</td><td style="text-align:right; font-weight:bold;" id="val-pm10">--</td></tr>
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:15px 0;">Nitrogen Dioxide (NO₂)</td><td style="text-align:right; font-weight:bold;" id="val-no2">--</td></tr>
                        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:15px 0;">Sulfur Dioxide (SO₂)</td><td style="text-align:right; font-weight:bold;" id="val-so2">--</td></tr>
                        <tr><td style="padding:15px 0;">Carbon Monoxide (CO)</td><td style="text-align:right; font-weight:bold;" id="val-co">--</td></tr>
                    </table>
                </div>
            </div>
        </section>

        <section id="charts" class="slide" style="background:#fff;">
            <div>
                <h1 class="slide-title">Flight Path Analytics</h1>
                <p class="slide-desc">Pollutant Concentration mapped to GPS Coordinates (Hover to see location)</p>
            </div>
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
            <div>
                <h1 class="slide-title">Health Risk Assessment</h1>
                <p class="slide-desc">AI-Generated Safety Protocols based on Chemical Toxicity</p>
            </div>
            <div id="risk-container" class="grid-2">
                <div class="card" style="grid-column: span 2; text-align: center; color: #94a3b8;">
                    <i class="fa-solid fa-user-doctor" style="font-size:3rem; margin-bottom:15px;"></i>
                    <p>Upload data to generate health analysis.</p>
                </div>
            </div>
        </section>

        <section id="esp32" class="slide" style="background:#1e293b; color:white;">
            <div>
                <h1 class="slide-title" style="color:white;">Drone Link (ESP32)</h1>
                <p class="slide-desc" style="color:#94a3b8;">Direct Hardware Interface</p>
            </div>
            <div class="grid-2">
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>📡 Connection Status</h3>
                    <div style="margin-top:20px;">
                        <p><strong>Protocol:</strong> HTTP / JSON</p>
                        <p><strong>Endpoint:</strong> <code style="background:#334155; padding:2px 6px; border-radius:4px;">/api/upload_sensor</code></p>
                        <p><strong>Status:</strong> <span style="color:#4ade80;">● Listening</span></p>
                    </div>
                </div>
                <div class="card" style="background:#0f172a; border:1px solid #334155; color:white;">
                    <h3>🚀 Live Telemetry</h3>
                    <div class="console" id="esp-console">
                        > System Initialized...<br>
                        > Waiting for Drone Handshake...<br>
                        > Ready for JSON payloads.
                    </div>
                </div>
            </div>
        </section>

        <section id="report" class="slide">
            <div>
                <h1 class="slide-title">Mission Report</h1>
                <p class="slide-desc">Generate Official Documentation & Manage Data</p>
            </div>
            <div class="grid-2">
                <div class="card" style="text-align:center;">
                    <h3>📄 Generate Report</h3>
                    <p style="color:#64748b; margin:15px 0;">Download a comprehensive PDF-ready text report containing all averages, identified risks, and safety precautions.</p>
                    <a href="/export" class="btn-download"><i class="fa-solid fa-file-pdf"></i> Download Full Report</a>
                </div>
                <div class="card">
                    <h3>📤 Upload Data</h3>
                    <label class="upload-zone" style="margin-top:15px; display:block;">
                        <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2rem; color: #cbd5e1;"></i>
                        <p id="upload-text" style="margin-top:10px;">Select CSV / Excel File</p>
                        <input type="file" id="fileInput" style="display:none;">
                    </label>
                </div>
            </div>
        </section>
    </div>

    <script>
        // --- 1. FILE UPLOAD LOGIC ---
        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if(!file) return;
            
            const text = document.getElementById('upload-text');
            text.innerText = "Analyzing...";
            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();
                
                if(data.error) { alert(data.error); text.innerText = "Upload Failed"; }
                else {
                    text.innerText = "Data Loaded Successfully!";
                    updateDashboard(data.data);
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            } catch(err) { alert("Error: " + err); }
        });

        // --- 2. UPDATE DASHBOARD FUNCTION ---
        function updateDashboard(data) {
            // A. Update Overview
            document.getElementById('aqi-val').innerText = data.aqi;
            document.getElementById('status-badge').innerText = data.status;
            ['pm25','pm10','no2','so2','co'].forEach(k => {
                if(document.getElementById('val-'+k)) document.getElementById('val-'+k).innerText = data[k];
            });

            // B. Update Charts (With GPS Tooltip)
            renderChart('chart-pm25', 'PM 2.5', data.chart_data.pm25, data.chart_data.gps, '#2563eb');
            renderChart('chart-pm10', 'PM 10', data.chart_data.pm10, data.chart_data.gps, '#0ea5e9');
            renderChart('chart-no2', 'NO₂', data.chart_data.no2, data.chart_data.gps, '#f59e0b');
            renderChart('chart-so2', 'SO₂', data.chart_data.so2, data.chart_data.gps, '#ef4444');

            // C. Update Risks (3 Precautions each)
            const rc = document.getElementById('risk-container');
            rc.innerHTML = '';
            if(data.health_risks.length > 0) {
                data.health_risks.forEach(r => {
                    rc.innerHTML += `
                    <div class="card" style="border-left: 5px solid ${r.color};">
                        <h3 style="color:${r.color}"><i class="fa-solid fa-triangle-exclamation"></i> ${r.name}</h3>
                        <p style="font-size:0.9rem; color:#64748b; margin-bottom:10px;">Severity: <strong>${r.level}</strong></p>
                        <ul style="padding-left:20px; color:#334155;">
                            ${r.precautions.map(p => `<li style="margin-bottom:5px;">${p}</li>`).join('')}
                        </ul>
                    </div>`;
                });
            } else {
                rc.innerHTML = '<div class="card"><h3 style="color:green;">✅ No Significant Health Risks Detected</h3></div>';
            }
        }

        // --- 3. CHART RENDERER (With GPS Logic) ---
        function renderChart(id, label, dataPoints, gpsData, color) {
            new Chart(document.getElementById(id), {
                type: 'line',
                data: {
                    labels: dataPoints.map((_, i) => i+1),
                    datasets: [{
                        label: label,
                        data: dataPoints,
                        borderColor: color,
                        backgroundColor: color + '10',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        title: { display: true, text: label + " vs Flight Path" },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let val = context.raw;
                                    let idx = context.dataIndex;
                                    let gps = (gpsData && gpsData[idx]) ? gpsData[idx] : {lat: '?', lon: '?'};
                                    return [`Level: ${val}`, `Lat: ${gps.lat}`, `Lon: ${gps.lon}`];
                                }
                            }
                        }
                    },
                    scales: { x: { display: false }, y: { beginAtZero: true } }
                }
            });
        }
    </script>
</body>
</html>
"""

# --- BACKEND LOGIC ---
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']

    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400
        
        # 1. Clean Column Names
        df.columns = [re.sub(r'[^a-z0-9]', '', c.lower()) for c in df.columns]
        mapper = {'pm25':'pm25', 'pm10':'pm10', 'no2':'no2', 'so2':'so2', 'co':'co', 'lat':'lat', 'latitude':'lat', 'lon':'lon', 'longitude':'lon'}
        df = df.rename(columns={c: mapper[c] for c in df.columns if c in mapper})
        
        # 2. Fill Missing Columns
        for c in ['pm25','pm10','no2','so2','co']: 
            if c not in df.columns: df[c] = 0
        if 'lat' not in df.columns: df['lat'] = 0.0
        if 'lon' not in df.columns: df['lon'] = 0.0

        # 3. Calculate Averages
        val = {k: round(df[k].mean(), 1) for k in ['pm25','pm10','no2','so2','co']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))

        # 4. ADVANCED RISK ENGINE (More than 2 effects, 3 precautions each)
        risks = []
        
        if val['pm25'] > 150:
            risks.append({
                "name": "High Particulate Danger (PM2.5)", "level": "Critical", "color": "red",
                "precautions": ["Immediately wear N95/P100 respiratory protection.", "Evacuate the area to a filtered indoor environment.", "Avoid all physical exertion to prevent lung absorption."]
            })
        elif val['pm25'] > 50:
            risks.append({
                "name": "Respiratory Irritation Risk", "level": "High", "color": "orange",
                "precautions": ["Sensitive individuals (Asthma/COPD) should stay indoors.", "Wear a mask if working outside for >1 hour.", "Use air purifiers in the immediate vicinity."]
            })

        if val['no2'] > 100:
            risks.append({
                "name": "Nitrogen Dioxide Toxicity", "level": "High", "color": "red",
                "precautions": ["Limit exposure near traffic or combustion sources.", "Seek medical attention if coughing or wheezing occurs.", "Seal windows/vents facing the pollution source."]
            })

        if val['so2'] > 100:
            risks.append({
                "name": "Sulfur Dioxide Hazard", "level": "High", "color": "red",
                "precautions": ["Avoid deep breathing in the affected zone.", "Wash eyes immediately if irritation occurs.", "Move upwind from the industrial source."]
            })
            
        if val['co'] > 20:
            risks.append({
                "name": "Carbon Monoxide Warning", "level": "Critical", "color": "red",
                "precautions": ["Move to fresh air immediately (Do not wait).", "Extinguish any open flames or combustion engines.", "Check blood oxygen levels if dizziness occurs."]
            })

        # 5. Prepare Chart Data (Max 50 points for speed)
        chart_df = df.head(50)
        gps_data = [{"lat": round(r['lat'], 5), "lon": round(r['lon'], 5)} for _, r in chart_df.iterrows()]
        
        chart_data = {
            "pm25": chart_df['pm25'].tolist(),
            "pm10": chart_df['pm10'].tolist(),
            "no2": chart_df['no2'].tolist(),
            "so2": chart_df['so2'].tolist(),
            "gps": gps_data
        }

        # 6. Save to Global (For Report Export)
        current_data = { "aqi": aqi, **val, "status": "Hazardous" if aqi>300 else "Good", "health_risks": risks, "chart_data": chart_data }
        
        return jsonify({"message": "Success", "data": current_data})

    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/export')
def export_report():
    # GENERATE TEXT REPORT
    lines = [
        "===============================================",
        "           SKYSENSE MISSION REPORT             ",
        f"           Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "===============================================",
        "",
        "1. MISSION SUMMARY",
        f"   Average AQI: {current_data['aqi']}",
        f"   Status:      {current_data['status']}",
        "",
        "2. POLLUTANT AVERAGES (µg/m³)",
        f"   PM 2.5: {current_data['pm25']}",
        f"   PM 10:  {current_data['pm10']}",
        f"   NO2:    {current_data['no2']}",
        f"   SO2:    {current_data['so2']}",
        f"   CO:     {current_data['co']}",
        "",
        "3. HEALTH RISK ASSESSMENT",
    ]
    
    if not current_data['health_risks']:
        lines.append("   - No significant risks detected.")
    else:
        for r in current_data['health_risks']:
            lines.append(f"   [!] {r['name']} ({r['level']})")
            for p in r['precautions']:
                lines.append(f"       * {p}")
            lines.append("")
            
    lines.append("===============================================")
    lines.append("Generated automatically by SkySense AI System")
    
    # Create file in memory
    mem = io.BytesIO("\n".join(lines).encode())
    return send_file(mem, as_attachment=True, download_name="SkySense_Mission_Report.txt", mimetype="text/plain")

if __name__ == '__main__':
    app.run(debug=True)
