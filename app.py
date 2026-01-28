from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import re
from datetime import datetime

app = Flask(__name__)

# --- THE WEBSITE (HTML/CSS/JS INSIDE PYTHON) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Live Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --primary: #2563eb; --bg: #f8fafc; --text: #0f172a; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { font-size: 2.5rem; color: var(--primary); margin-bottom: 5px; }
        .card { background: white; padding: 25px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 20px; }
        .btn { background: var(--primary); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: 600; width: 100%; }
        .btn:hover { opacity: 0.9; }
        .upload-box { border: 2px dashed #cbd5e1; padding: 40px; text-align: center; border-radius: 12px; cursor: pointer; transition: 0.2s; }
        .upload-box:hover { border-color: var(--primary); background: #eff6ff; }
        .hidden { display: none; }
        .grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
        @media(min-width: 768px) { .grid { grid-template-columns: 1fr 1fr; } }
        .stat-val { font-size: 2rem; font-weight: 800; }
        .risk-item { padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #e2e8f0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fa-solid fa-drone"></i> SkySense</h1>
            <p>Autonomous Air Quality Analysis</p>
        </div>

        <div class="card" id="upload-card">
            <h3 style="margin-bottom:15px;">📤 Upload Sensor Data</h3>
            <label class="upload-box">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size: 2rem; color: #94a3b8;"></i>
                <p id="upload-text" style="margin-top:10px;">Click to Select CSV or Excel File</p>
                <input type="file" id="fileInput" style="display: none;">
            </label>
        </div>

        <div id="dashboard" class="hidden">
            
            <div class="grid">
                <div class="card" style="text-align:center;">
                    <h3>Air Quality Index</h3>
                    <div class="stat-val" id="aqi-val" style="color:#ea580c;">--</div>
                    <span id="status-badge" style="background:#ffedd5; padding:5px 10px; border-radius:20px; font-size:0.9rem;">Waiting...</span>
                </div>
                <div class="card">
                    <h3>Pollutant Averages</h3>
                    <div style="display:flex; justify-content:space-between; margin-top:10px;">
                        <div><small>PM2.5</small><div id="val-pm25" style="font-weight:bold;">--</div></div>
                        <div><small>PM10</small><div id="val-pm10" style="font-weight:bold;">--</div></div>
                        <div><small>NO₂</small><div id="val-no2" style="font-weight:bold;">--</div></div>
                        <div><small>SO₂</small><div id="val-so2" style="font-weight:bold;">--</div></div>
                        <div><small>CO</small><div id="val-co" style="font-weight:bold;">--</div></div>
                    </div>
                </div>
            </div>

            <div class="card">
                <h3>📉 Pollutant Trends vs. Flight Path</h3>
                <div class="grid">
                    <div style="height:200px;"><canvas id="chart-pm25"></canvas></div>
                    <div style="height:200px;"><canvas id="chart-pm10"></canvas></div>
                </div>
            </div>

            <div class="card">
                <h3>🩺 Health Risk Assessment</h3>
                <div id="risk-container"></div>
            </div>

            <button class="btn" onclick="window.location.href='/export'"><i class="fa-solid fa-download"></i> Download Full Report</button>
        </div>
    </div>

    <script>
        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if(!file) return;

            const text = document.getElementById('upload-text');
            text.innerText = "Processing... Please wait.";
            
            const formData = new FormData();
            formData.append('file', file);

            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();

                if(data.error) {
                    alert("Error: " + data.error);
                    text.innerText = "Upload Failed. Try again.";
                } else {
                    document.getElementById('upload-card').style.display = 'none';
                    document.getElementById('dashboard').style.display = 'block';
                    updateDashboard(data.data);
                }
            } catch(err) {
                alert("Upload failed: " + err);
            }
        });

        function updateDashboard(data) {
            document.getElementById('aqi-val').innerText = data.aqi;
            document.getElementById('status-badge').innerText = data.status;
            
            ['pm25','pm10','no2','so2','co'].forEach(k => {
                if(document.getElementById('val-'+k)) document.getElementById('val-'+k).innerText = data[k];
            });

            // Risks
            const rContainer = document.getElementById('risk-container');
            rContainer.innerHTML = '';
            if(data.health_risks.length > 0) {
                data.health_risks.forEach(r => {
                    rContainer.innerHTML += `<div class="risk-item" style="border-left: 4px solid ${r.color}; background: #fffcfc;">
                        <strong>${r.name}</strong> <span style="font-size:0.8rem; color:${r.color};">(${r.level})</span>
                        <ul style="margin:5px 0 0 15px; font-size:0.9rem; color:#666;">${r.precautions.map(p=>`<li>${p}</li>`).join('')}</ul>
                    </div>`;
                });
            } else {
                rContainer.innerHTML = '<p style="color:green;">✅ Air Quality is Good. No major risks.</p>';
            }

            // Charts
            renderChart('chart-pm25', 'PM 2.5', data.chart_data.pm25, data.chart_data.gps, '#2563eb');
            renderChart('chart-pm10', 'PM 10', data.chart_data.pm10, data.chart_data.gps, '#0ea5e9');
        }

        function renderChart(id, label, data, gps, color) {
            new Chart(document.getElementById(id), {
                type: 'line',
                data: {
                    labels: data.map((_, i) => i+1),
                    datasets: [{ label: label, data: data, borderColor: color, borderWidth: 2, tension: 0.4, fill: false }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: {display: false}, title: {display: true, text: label} },
                    scales: { x: {display: false} }
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
def upload():
    try:
        if 'file' not in request.files: return jsonify({"error": "No file"}), 400
        file = request.files['file']
        
        # READ IN MEMORY (No Saving)
        if file.filename.endswith('.csv'): df = pd.read_csv(file)
        elif file.filename.endswith(('.xls','.xlsx')): df = pd.read_excel(file)
        else: return jsonify({"error": "Use CSV or Excel"}), 400

        # CLEAN COLUMNS
        df.columns = [re.sub(r'[^a-z0-9]', '', c.lower()) for c in df.columns]
        mapper = {'pm25':'pm25', 'pm10':'pm10', 'no2':'no2', 'so2':'so2', 'co':'co', 'lat':'lat', 'latitude':'lat', 'lon':'lon', 'longitude':'lon'}
        df = df.rename(columns={c: mapper[c] for c in df.columns if c in mapper})

        # CALCULATE
        for c in ['pm25','pm10','no2','so2','co']: 
            if c not in df.columns: df[c] = 0
        
        val = {k: round(df[k].mean(), 1) for k in ['pm25','pm10','no2','so2','co']}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))

        # RISKS
        risks = []
        if val['pm25']>150: risks.append({"name":"Respiratory Danger", "level":"Critical", "color":"red", "precautions":["Wear N95 Mask", "Stay Indoors"]})
        elif val['pm25']>50: risks.append({"name":"Asthma Risk", "level":"High", "color":"orange", "precautions":["Limit Outdoor Exercise"]})
        
        # CHART DATA
        chart = df.head(50)
        gps = [{"lat":0, "lon":0} for _ in range(len(chart))]
        if 'lat' in chart.columns: gps = chart[['lat','lon']].to_dict('records')

        data = {
            "aqi": aqi, **val, 
            "status": "Hazardous" if aqi>300 else "Unhealthy" if aqi>100 else "Good",
            "health_risks": risks,
            "chart_data": { "pm25": chart['pm25'].tolist(), "pm10": chart['pm10'].tolist(), "gps": gps }
        }
        return jsonify({"message":"OK", "data": data})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/export')
def export():
    # DUMMY REPORT FOR DEMO
    txt = "SKYSENSE REPORT\nStatus: Generated Successfully."
    return send_file(io.BytesIO(txt.encode()), mimetype='text/plain', as_attachment=True, download_name='report.txt')

if __name__ == '__main__':
    app.run(debug=True)