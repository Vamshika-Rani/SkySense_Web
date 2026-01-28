from flask import Flask, render_template_string, jsonify, request
import pandas as pd
import re

app = Flask(__name__)

# --- THE WEBSITE (SLIDES LAYOUT INSIDE PYTHON) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Drone Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --primary: #2563eb; --bg: #f0f4f8; --card-bg: #ffffff; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: #1e293b; overflow-x: hidden; }
        
        /* SIDEBAR NAVIGATION */
        .sidebar { position: fixed; top: 0; left: 0; width: 250px; height: 100vh; background: white; padding: 30px; box-shadow: 2px 0 10px rgba(0,0,0,0.05); z-index: 1000; }
        .logo { font-size: 1.5rem; font-weight: 800; color: var(--primary); margin-bottom: 40px; display: flex; align-items: center; gap: 10px; }
        .nav-links a { display: block; padding: 15px; margin-bottom: 10px; text-decoration: none; color: #64748b; font-weight: 600; border-radius: 8px; transition: 0.2s; }
        .nav-links a:hover, .nav-links a.active { background: #eff6ff; color: var(--primary); }
        
        /* MAIN CONTENT SLIDES */
        .main-content { margin-left: 250px; }
        .slide-section { min-height: 100vh; padding: 60px; border-bottom: 1px solid #e2e8f0; display: flex; flex-direction: column; justify-content: center; }
        .slide-header { margin-bottom: 40px; }
        .slide-header h2 { font-size: 2.5rem; font-weight: 800; color: #0f172a; }
        
        /* CARDS & GRID */
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 30px; }
        .card { background: var(--card-bg); padding: 30px; border-radius: 20px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05); }
        
        /* COMPONENTS */
        .aqi-box { text-align: center; padding: 50px; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; border-radius: 24px; }
        .aqi-val { font-size: 6rem; font-weight: 800; line-height: 1; margin: 10px 0; }
        .upload-zone { border: 3px dashed #cbd5e1; padding: 60px; text-align: center; border-radius: 20px; cursor: pointer; transition: 0.3s; background: #f8fafc; display: block; }
        .upload-zone:hover { border-color: var(--primary); background: #eff6ff; }
        
        /* RISK ITEMS */
        .risk-item { padding: 25px; margin-bottom: 20px; border-radius: 12px; border-left: 6px solid #ccc; background: white; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        
        /* RESPONSIVE */
        @media(max-width: 900px) {
            .sidebar { width: 100%; height: auto; position: relative; padding: 20px; }
            .main-content { margin-left: 0; }
            .slide-section { min-height: auto; padding: 40px 20px; }
            .nav-links { display: flex; overflow-x: auto; gap: 10px; }
            .nav-links a { white-space: nowrap; }
        }
    </style>
</head>
<body>

    <div class="sidebar">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <div class="nav-links">
            <a href="#slide-overview"><i class="fa-solid fa-chart-pie"></i> Overview</a>
            <a href="#slide-charts"><i class="fa-solid fa-chart-line"></i> Analytics</a>
            <a href="#slide-health"><i class="fa-solid fa-heart-pulse"></i> Health Risk</a>
            <a href="#slide-upload"><i class="fa-solid fa-cloud-arrow-up"></i> Upload Data</a>
        </div>
    </div>

    <div class="main-content">
        
        <div id="slide-overview" class="slide-section">
            <div class="slide-header"><h2>Mission Status</h2><p>Real-time Air Quality Telemetry</p></div>
            <div class="grid">
                <div class="aqi-box">
                    <p>AIR QUALITY INDEX</p>
                    <div class="aqi-val" id="aqi-val">--</div>
                    <div style="background:rgba(255,255,255,0.2); padding:5px 15px; border-radius:20px; display:inline-block;" id="status-badge">Waiting...</div>
                </div>
                <div class="card">
                    <h3>Pollutant Levels</h3>
                    <div style="margin-top:20px; font-size:1.1rem;">
                        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #eee;"><span>PM 2.5</span><b id="val-pm25">--</b></div>
                        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #eee;"><span>PM 10</span><b id="val-pm10">--</b></div>
                        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #eee;"><span>NO₂</span><b id="val-no2">--</b></div>
                        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #eee;"><span>SO₂</span><b id="val-so2">--</b></div>
                        <div style="display:flex; justify-content:space-between; padding:10px 0;"><span>CO</span><b id="val-co">--</b></div>
                    </div>
                </div>
            </div>
        </div>

        <div id="slide-charts" class="slide-section" style="background:#fff;">
            <div class="slide-header"><h2>Flight Analytics</h2><p>Pollutant Concentration vs. GPS Path</p></div>
            <div class="grid">
                <div class="card" style="height:400px;"><canvas id="chart-pm25"></canvas></div>
                <div class="card" style="height:400px;"><canvas id="chart-pm10"></canvas></div>
            </div>
        </div>

        <div id="slide-health" class="slide-section">
            <div class="slide-header"><h2>Health Risk Assessment</h2><p>AI-Generated Safety Precautions</p></div>
            <div id="risk-container">
                <div class="card" style="text-align:center; color:#94a3b8; padding:50px;">
                    <i class="fa-solid fa-user-doctor" style="font-size:4rem; margin-bottom:20px;"></i>
                    <h3>Upload data to generate analysis</h3>
                </div>
            </div>
        </div>

        <div id="slide-upload" class="slide-section" style="background:#fff;">
            <div class="slide-header"><h2>Data Management</h2><p>Upload Drone SD Card Data (CSV/Excel)</p></div>
            <label class="upload-zone">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 4rem; color: #cbd5e1; margin-bottom:20px;"></i>
                <h2 id="upload-text">Click to Upload File</h2>
                <input type="file" id="fileInput" style="display: none;">
            </label>
        </div>

    </div>

    <script>
        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if(!file) return;
            const text = document.getElementById('upload-text');
            text.innerText = "Processing Flight Data...";
            
            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if(data.error) { alert(data.error); text.innerText = "Upload Failed"; }
                else { 
                    text.innerText = "Success! Scroll Up.";
                    updateDashboard(data.data);
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            } catch(err) { alert("Error: " + err); }
        });

        function updateDashboard(data) {
            document.getElementById('aqi-val').innerText = data.aqi;
            document.getElementById('status-badge').innerText = data.status;
            ['pm25','pm10','no2','so2','co'].forEach(k => {
                if(document.getElementById('val-'+k)) document.getElementById('val-'+k).innerText = data[k];
            });

            const rc = document.getElementById('risk-container');
            rc.innerHTML = '';
            if(data.health_risks.length > 0) {
                data.health_risks.forEach(r => {
                    rc.innerHTML += `<div class="risk-item" style="border-color:${r.color};">
                        <h3 style="color:${r.color}; margin-bottom:5px;"><i class="fa-solid ${r.icon || 'fa-triangle-exclamation'}"></i> ${r.name}</h3>
                        <span style="background:${r.color}; color:white; padding:4px 12px; border-radius:15px; font-size:0.8rem; font-weight:bold;">${r.level}</span>
                        <ul style="margin-top:15px; padding-left:20px; color:#475569; font-size:1.1rem;">${r.precautions.map(p=>`<li style="margin-bottom:5px;">${p}</li>`).join('')}</ul>
                    </div>`;
                });
            } else { rc.innerHTML = '<div class="card"><h3 style="color:green; text-align:center;">✅ Safe Levels. No Risks Detected.</h3></div>'; }

            renderChart('chart-pm25', 'PM 2.5 Concentration', data.chart_data.pm25, '#2563eb');
            renderChart('chart-pm10', 'PM 10 Concentration', data.chart_data.pm10, '#0ea5e9');
        }

        function renderChart(id, label, data, color) {
            new Chart(document.getElementById(id), {
                type: 'line',
                data: { labels: data.map((_, i) => i+1), datasets: [{ label: label, data: data, borderColor: color, backgroundColor: color+'20', fill: true, tension: 0.4 }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: {display:false}, title: {display: true, text: label} }, scales: { x: {display: false} } }
            });
        }
    </script>
</body>
</html>
"""

# --- BACKEND LOGIC ---
@app.route('/')
def home():
    # MAGIC: This serves the HTML directly from the variable above!
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No file"}), 400

    try:
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xlsx', '.xls')): df = pd.read_excel(file)
        else: return jsonify({"error": "Invalid file"}), 400
        
        # Clean Columns
        df.columns = [re.sub(r'[^a-z0-9]', '', c.lower()) for c in df.columns]
        mapper = {'pm25':'pm25', 'pm10':'pm10', 'no2':'no2', 'so2':'so2', 'co':'co', 'lat':'lat', 'latitude':'lat', 'lon':'lon', 'longitude':'lon'}
        df = df.rename(columns={c: mapper[c] for c in df.columns if c in mapper})
        
        # Defaults
        for c in ['pm25','pm10','no2','so2','co']: 
            if c not in df.columns: df[c] = 0
            
        val = {k: round(df[k].mean(), 1) for k in ['pm25','pm10','no2','so2','co']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        # Risks
        risks = []
        if val['pm25']>150: risks.append({"name":"Respiratory Danger", "level":"Critical", "color":"red", "precautions":["Wear N95 Mask", "Stay Indoors"]})
        elif val['pm25']>50: risks.append({"name":"Asthma Risk", "level":"High", "color":"orange", "precautions":["Limit Outdoor Exercise"]})
        if val['co']>10: risks.append({"name":"CO Poisoning Risk", "level":"High", "color":"red", "precautions":["Seek Fresh Air"]})
        
        # Charts
        chart_df = df.head(50)
        data = { "aqi": aqi, **val, "status": "Hazardous" if aqi>300 else "Good", "health_risks": risks, 
                 "chart_data": { "pm25": chart_df['pm25'].tolist(), "pm10": chart_df['pm10'].tolist() } }
        
        return jsonify({"message": "Success", "data": data})

    except Exception as e: return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
