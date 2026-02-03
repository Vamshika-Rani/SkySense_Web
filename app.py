from flask import Flask, render_template_string, jsonify, request, send_from_directory, send_file
import pandas as pd
import io
import datetime
import random
import os
import time

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    # Random User Agent prevents blocking
    geolocator = Nominatim(user_agent=f"skysense_drone_{random.randint(10000,99999)}")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- GLOBAL DATA ---
history_log = [] 
historical_stats = [] 
location_cache = {} 

current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "avg_aqi": 0, "avg_pm1": 0, "avg_pm25": 0, "avg_pm10": 0, "avg_temp": 0, "avg_hum": 0,
    "status": "Waiting...", "location_name": "Waiting for GPS...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready..."],
    "last_updated": "Never"
}

# --- HELPERS ---
def has_moved(lat, lon):
    gps_list = current_data['chart_data']['gps']
    if not gps_list: return True 
    last_pt = gps_list[-1]
    return (abs(lat - last_pt['lat']) > 0.0001 or abs(lon - last_pt['lon']) > 0.0001)

def read_file_safely(file):
    file.seek(0)
    try: return pd.read_csv(file)
    except: pass
    try: file.seek(0); return pd.read_csv(file, encoding='latin1')
    except: pass
    try: file.seek(0); return pd.read_excel(file)
    except: pass
    raise ValueError("Invalid File Format")

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'lat' in c: col_map[col] = 'lat'
        elif 'lon' in c: col_map[col] = 'lon'
    return df.rename(columns=col_map)

# --- ROBUST LOCATION FINDER (FIXED) ---
def get_city_name(lat, lon):
    if lat == 0 or lon == 0: return "No GPS Signal"
    
    # Cache key (rounded to prevent spamming same spot)
    cache_key = (round(lat, 3), round(lon, 3))
    if cache_key in location_cache: return location_cache[cache_key]
    
    coord_str = f"{round(lat, 4)}, {round(lon, 4)}"
    if not geolocator: return coord_str
    
    try:
        # Retry logic
        for _ in range(2): 
            try:
                # 10s timeout to allow slow responses
                loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en', timeout=10)
                if loc:
                    add = loc.raw.get('address', {})
                    # Prioritize specific areas
                    area = add.get('neighbourhood') or add.get('suburb') or add.get('residential') or add.get('road')
                    city = add.get('city') or add.get('town') or add.get('county')
                    
                    res = coord_str
                    if area and city: res = f"{area}, {city}"
                    elif area: res = f"{area}"
                    elif city: res = f"{city}"
                    
                    location_cache[cache_key] = res
                    return res
            except: 
                time.sleep(1) # Wait before retry
    except: pass
    
    return coord_str

# --- DYNAMIC HEALTH LOGIC (6 LEVELS) ---
def calc_health(val):
    aqi = int((val.get('pm25', 0) * 2) + (val.get('pm10', 0) * 0.5))
    risks = []
    
    if aqi <= 100:
        risks = [{"name": "General Well-being", "desc": "Air quality is satisfactory.", "prob": 5, "level": "Good", "recs": ["Active outdoors is safe.", "Ventilate home.", "No filters needed."]},
                 {"name": "Respiratory Health", "desc": "No irritation expected.", "prob": 5, "level": "Good", "recs": ["Exercise freely.", "Deep breathing safe.", "Enjoy fresh air."]},
                 {"name": "Sensitive Groups", "desc": "Safe for asthmatics.", "prob": 10, "level": "Low", "recs": ["Keep inhalers nearby.", "Monitor pollen.", "No masks."]},
                 {"name": "Skin & Eye Health", "desc": "No irritation risks.", "prob": 0, "level": "Low", "recs": ["No eyewear needed.", "Standard skincare.", "Use sunscreen."]}]
    elif aqi <= 200:
        risks = [{"name": "Mild Irritation", "desc": "Coughing/throat irritation.", "prob": 40, "level": "Moderate", "recs": ["Limit prolonged exertion.", "Hydrate throat.", "Carry water."]},
                 {"name": "Asthma Risk", "desc": "May trigger mild symptoms.", "prob": 50, "level": "Moderate", "recs": ["Inhalers accessible.", "Avoid heavy traffic.", "Watch for wheezing."]},
                 {"name": "Sinus Pressure", "desc": "Minor nasal congestion.", "prob": 30, "level": "Moderate", "recs": ["Saline rinse.", "Shower after outdoors.", "Close windows."]},
                 {"name": "Fatigue", "desc": "Quicker tiredness.", "prob": 25, "level": "Low", "recs": ["Take breaks.", "Avoid heavy cardio.", "Monitor heart rate."]}]
    elif aqi <= 300:
        risks = [{"name": "Bronchitis Risk", "desc": "Inflamed bronchial tubes.", "prob": 65, "level": "High", "recs": ["Avoid outdoor activity.", "Wear N95 mask.", "Use air purifier."]},
                 {"name": "Cardiac Stress", "desc": "Elevated blood pressure.", "prob": 50, "level": "High", "recs": ["Heart patients stay in.", "Avoid salty food.", "Monitor BP."]},
                 {"name": "Allergies", "desc": "Worsened allergy symptoms.", "prob": 70, "level": "High", "recs": ["Take antihistamines.", "Seal windows.", "Change clothes."]},
                 {"name": "Eye Irritation", "desc": "Burning or watery eyes.", "prob": 60, "level": "Moderate", "recs": ["Use eye drops.", "Wear sunglasses.", "Don't rub eyes."]}]
    elif aqi <= 400:
        risks = [{"name": "Lung Infection", "desc": "High infection risk.", "prob": 80, "level": "Severe", "recs": ["Strictly avoid outdoors.", "Wear N99 mask.", "Steam inhalation."]},
                 {"name": "Ischemic Risk", "desc": "Reduced heart oxygen.", "prob": 75, "level": "Severe", "recs": ["Elderly stay inside.", "No physical labor.", "Watch chest pain."]},
                 {"name": "Hypoxia", "desc": "Headaches/Dizziness.", "prob": 60, "level": "High", "recs": ["Use oxygen.", "Calm breathing.", "No smoking."]},
                 {"name": "Pneumonia", "desc": "Vulnerable to bacteria.", "prob": 50, "level": "High", "recs": ["Wash hands often.", "Avoid crowds.", "Consult doctor."]}]
    elif aqi <= 500:
        risks = [{"name": "Lung Impairment", "desc": "Breathing difficulty.", "prob": 90, "level": "Critical", "recs": ["Do not go out.", "Wet towels on windows.", "Max air purifier."]},
                 {"name": "Stroke Risk", "desc": "Thickened blood.", "prob": 60, "level": "High", "recs": ["Hydrate heavily.", "Avoid stress.", "Emergency contacts ready."]},
                 {"name": "Inflammation", "desc": "Systemic body inflammation.", "prob": 85, "level": "Critical", "recs": ["Anti-inflammatory food.", "Rest fully.", "No frying food."]},
                 {"name": "Pulmonary Edema", "desc": "Fluid in lungs.", "prob": 40, "level": "Severe", "recs": ["Medical care needed.", "Sleep elevated.", "Don't lie flat."]}]
    else:
        risks = [{"name": "ARDS", "desc": "Lung failure potential.", "prob": 95, "level": "Emergency", "recs": ["Evacuate area.", "Medical oxygen.", "N99 respirator."]},
                 {"name": "Cardiac Arrest", "desc": "Extreme heart stress.", "prob": 70, "level": "Emergency", "recs": ["Bed rest.", "Defibrillator ready.", "No exertion."]},
                 {"name": "Asphyxiation", "desc": "Toxic choking feeling.", "prob": 90, "level": "Emergency", "recs": ["Create clean room.", "Double filtration.", "Limit talking."]},
                 {"name": "Lung Damage", "desc": "Permanent scarring risk.", "prob": 80, "level": "Critical", "recs": ["See pulmonologist.", "Lung detox.", "Relocate."]}]
    return risks

# --- HTML TEMPLATES ---
HTML_HEAD = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Pro Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        :root { --bg: #fdfbf7; --card-bg: #ffffff; --text-main: #1c1917; --text-muted: #78716c; --primary: #0f172a; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; margin:0; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; }
        .alert-banner { background: #fff7ed; border: 1px solid #ffedd5; color: #9a3412; padding: 20px; border-radius: 12px; margin-bottom: 30px; display:flex; gap:15px; }
        .nav-tabs { display: flex; gap: 10px; background: white; padding: 8px; border-radius: 50px; margin-bottom: 30px; border: 1px solid #e7e5e4; width: fit-content; }
        .tab-btn { border: none; background: transparent; padding: 10px 24px; font-weight: 600; color: #78716c; cursor: pointer; border-radius: 30px; }
        .tab-btn.active { background: var(--primary); color: white; }
        .section { display: none; } .section.active { display: block; animation: fadeIn 0.3s; }
        .dashboard-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 25px; }
        .card { background: white; border-radius: 20px; padding: 30px; border: 1px solid #e7e5e4; }
        .stat-row { display: flex; gap: 15px; margin-top: 30px; }
        .stat-box { flex: 1; background: #fafaf9; padding: 15px; border-radius: 12px; text-align: center; font-weight:800; font-size:1.5rem; }
        .risk-card { border: 1px solid #e7e5e4; border-radius: 16px; padding: 25px; border-left: 5px solid red; margin-bottom:20px; }
        .filter-btn { padding: 8px 16px; border: 1px solid #e7e5e4; background: white; border-radius: 20px; cursor: pointer; margin-right: 5px; }
        .filter-btn.active { background: var(--primary); color: white; }
        .date-picker { padding:15px; border:1px solid #ddd; border-radius:12px; width:100%; margin-bottom:10px; }
        .upload-card { display:block; text-align:center; padding: 40px; border: 2px dashed #ccc; border-radius: 20px; cursor: pointer; }
        .history-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .history-table th { text-align: left; padding: 12px; border-bottom: 2px solid #eee; }
        .history-table td { padding: 15px 12px; border-bottom: 1px solid #eee; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="logo">SkySense</div>
        <button onclick="location.reload()" style="padding:10px 20px; border-radius:30px; border:none; background:#e5e5e5; cursor:pointer; font-weight:600;">Refresh</button>
    </div>
    <div class="alert-banner">
        <strong>Status:</strong> <span id="alert-msg">Waiting for data...</span>
    </div>
    <div class="nav-tabs">
        <button class="tab-btn active" onclick="sw('overview')">Overview</button>
        <button class="tab-btn" onclick="sw('gps')">GPS Charts</button>
        <button class="tab-btn" onclick="sw('analytics')">Analytics</button>
        <button class="tab-btn" onclick="sw('disease')">Health</button>
        <button class="tab-btn" onclick="sw('history')">History</button>
        <button class="tab-btn" onclick="sw('upload')">Upload</button>
        <button class="tab-btn" onclick="sw('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="dashboard-grid">
            <div class="card">
                <h3>Real-Time Air Quality</h3>
                <div style="font-size:5rem; font-weight:800; color:#dc2626; text-align:center;" id="aqi-val">--</div>
                <div style="text-align:center; color:#78716c;" id="loc-name">Unknown</div>
                <div class="stat-row">
                    <div class="stat-box"><div id="val-pm1">--</div><div style="font-size:0.8rem">PM 1.0</div></div>
                    <div class="stat-box"><div id="val-pm25">--</div><div style="font-size:0.8rem">PM 2.5</div></div>
                    <div class="stat-box"><div id="val-pm10">--</div><div style="font-size:0.8rem">PM 10</div></div>
                </div>
            </div>
            <div class="card">
                <h3>Quick Health Summary</h3>
                <div id="mini-risk-list">Loading...</div>
            </div>
        </div>
    </div>

    <div id="gps" class="section">
        <div class="card">
            <h3>AQI Level vs Exact Location</h3>
            <div style="height:500px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="analytics" class="section">
        <div class="card">
            <h3>Historical Trends</h3>
            <button class="filter-btn active" onclick="updateTrend(7)">7 Days</button>
            <button class="filter-btn" onclick="updateTrend(30)">30 Days</button>
            <div style="height:400px; margin-top:20px;"><canvas id="trendChart"></canvas></div>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card">
            <h3>Detailed Health Analysis</h3>
            <div id="full-health-grid"></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <h3>Upload History</h3>
            <table class="history-table">
                <thead><tr><th>Date</th><th>File (Download)</th><th>AQI</th></tr></thead>
                <tbody id="history-body"></tbody>
            </table>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <h3>Upload Data</h3>
            <input type="date" id="upload-date" class="date-picker">
            <label class="upload-card">
                <div id="upload-text" style="font-weight:600; font-size:1.2rem;">Click to Upload CSV/Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <h3>Export Report</h3>
            <a href="/export/text" style="display:inline-block; background:#0f172a; color:white; padding:12px 25px; border-radius:8px; text-decoration:none;">Download Full Report</a>
        </div>
    </div>
</div>
"""

HTML_SCRIPT = """
<script>
    let mainChart = null, trendChart = null, rawHistory = [];

    function sw(id) {
        document.querySelectorAll('.section').forEach(e => e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(e => e.classList.remove('active'));
        document.querySelector(`button[onclick="sw('${id}')"]`).classList.add('active');
        if(id === 'analytics') updateTrend(7);
    }

    document.getElementById('upload-date').valueAsDate = new Date();
    setInterval(() => { fetch('/api/data').then(r => r.json()).then(d => { rawHistory = d.historical_stats || []; updateUI(d); }); }, 3000);

    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if(!file) return;
        const txt = document.getElementById('upload-text'); txt.innerText = "Uploading...";
        const fd = new FormData(); fd.append('file', file); fd.append('date', document.getElementById('upload-date').value);
        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            const d = await res.json();
            txt.innerText = d.error ? "Failed" : "Success!";
            if(!d.error) { updateUI(d.data); setTimeout(()=>sw('overview'), 500); }
        } catch(e) { txt.innerText = "Error"; }
    });

    function updateTrend(days) {
        const ctx = document.getElementById('trendChart').getContext('2d');
        if(trendChart) trendChart.destroy();
        const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - days);
        const filtered = rawHistory.filter(d => days===0 || new Date(d.date) >= cutoff).sort((a,b) => new Date(a.date)-new Date(b.date));
        trendChart = new Chart(ctx, {
            type: 'line',
            data: { labels: filtered.map(d=>d.date), datasets: [{ label: 'Avg AQI', data: filtered.map(d=>d.aqi), borderColor: '#0f172a', tension: 0.3 }] },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    function updateUI(data) {
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('val-pm1').innerText = data.pm1;
        document.getElementById('val-pm25').innerText = data.pm25;
        document.getElementById('val-pm10').innerText = data.pm10;
        document.getElementById('loc-name').innerText = data.location_name;
        document.getElementById('alert-msg').innerText = `AQI ${data.aqi}`;

        // HEALTH
        const grid = document.getElementById('full-health-grid');
        const mini = document.getElementById('mini-risk-list');
        if(data.health_risks.length) {
            grid.innerHTML = ''; mini.innerHTML = '';
            data.health_risks.forEach(r => {
                let color = r.level === 'Good' ? '#16a34a' : (r.level === 'Moderate' ? '#ea580c' : '#dc2626');
                grid.innerHTML += `<div class="risk-card" style="border-left-color:${color}"><h3>${r.name} (${r.level})</h3><p>${r.desc}</p><ul>${r.recs.map(x=>`<li>${x}</li>`).join('')}</ul></div>`;
                mini.innerHTML += `<div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #eee;"><span>${r.name}</span><span style="color:${color}; font-weight:bold;">${r.level}</span></div>`;
            });
        }

        // HISTORY
        const hb = document.getElementById('history-body');
        if(data.history.length) {
            hb.innerHTML = data.history.map(h => `<tr><td>${h.date}</td><td><a href="/uploads/${h.filename}" target="_blank" style="color:#2563eb; text-decoration:none;">${h.filename}</a></td><td><b>${h.aqi}</b></td></tr>`).join('');
        }

        // CHART
        if(data.chart_data.aqi.length) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            // CLEAN LOCATION STRING: Remove coordinates if they are duplicated
            const cleanLoc = data.location_name.split('(')[0].trim();
            const labels = data.chart_data.gps.map(g => `${cleanLoc} (${Number(g.lat).toFixed(3)}, ${Number(g.lon).toFixed(3)})`);
            
            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, {
                type: 'bar',
                data: { labels: labels, datasets: [{ label: 'AQI', data: data.chart_data.aqi, backgroundColor: '#3b82f6', borderRadius: 5 }] },
                options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, scales: { x: { beginAtZero: true } } }
            });
        }
    }
</script>
</body>
</html>
"""

# --- ROUTES ---
@app.route('/')
def home(): return render_template_string(HTML_HEAD + HTML_STYLE + HTML_BODY + HTML_SCRIPT)

@app.route('/api/data')
def get_data(): 
    current_data['history'] = history_log
    current_data['historical_stats'] = historical_stats
    return jsonify(current_data)

@app.route('/uploads/<filename>')
def dl(filename): return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/upload', methods=['POST'])
def upload():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    f, dt = request.files['file'], request.form.get('date', str(datetime.date.today()))
    try:
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], f.filename))
        f.seek(0)
        df = normalize_columns(read_file_safely(f))
        
        valid = [r for i, r in df.head(100).iterrows() if r.get('lat',0) != 0 and r.get('lon',0) != 0]
        if not valid: raise ValueError("No valid GPS")
        
        # Filter duplicates & calculate
        filtered = [valid[0]]
        for r in valid[1:]:
            if has_moved(r['lat'], r['lon']): filtered.append(r)
            
        avgs = {k: round(pd.DataFrame(filtered)[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int(avgs['pm25']*2 + avgs['pm10']*0.5)
        
        # USE CACHED OR RETRIED LOCATION
        loc = get_city_name(filtered[0]['lat'], filtered[0]['lon'])
        
        # Update Global
        history_log.insert(0, {"date":dt, "filename":f.filename, "status":"Success", "aqi": aqi})
        existing = next((x for x in historical_stats if x['date'] == dt), None)
        if existing: existing['aqi'] = aqi
        else: historical_stats.append({"date": dt, "aqi": aqi})
        historical_stats.sort(key=lambda x: x['date'])
        
        current_data.update({"aqi": aqi, "location_name": loc, **avgs, 
                             "health_risks": calc_health(avgs), 
                             "chart_data": {"aqi": [int(r['pm25']*2 + r['pm10']*0.5) for r in filtered], 
                                            "gps": [{"lat":r['lat'], "lon":r['lon']} for r in filtered]}})
        
        return jsonify({"message": "OK", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def sensor():
    try:
        d = request.json
        aqi = int(d.get('pm25',0)*2 + d.get('pm10',0)*0.5)
        
        # Smart Location Update (only occasionally to save API calls)
        if current_data['location_name'] == "Waiting for GPS..." or random.random() < 0.1:
            current_data['location_name'] = get_city_name(d.get('lat',0), d.get('lon',0))
            
        current_data.update(d)
        current_data['aqi'] = aqi
        current_data['health_risks'] = calc_health(current_data)
        
        if has_moved(d.get('lat',0), d.get('lon',0)) and d.get('lat',0) != 0:
            current_data['chart_data']['aqi'].append(aqi)
            current_data['chart_data']['gps'].append({"lat":d.get('lat',0),"lon":d.get('lon',0)})
            if len(current_data['chart_data']['aqi']) > 50: 
                current_data['chart_data']['aqi'].pop(0); current_data['chart_data']['gps'].pop(0)
                
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"error":str(e)}), 400

@app.route('/export/text')
def export():
    d = current_data
    report = f"SKYSENSE REPORT\nDate: {datetime.datetime.now()}\nLoc: {d['location_name']}\nAQI: {d['aqi']}\n"
    report += "\n".join([f"- {r['name']}: {r['desc']}" for r in d['health_risks']])
    return send_file(io.BytesIO(report.encode()), mimetype='text/plain', as_attachment=True, download_name="report.txt")

if __name__ == '__main__':
    app.run(debug=True)
