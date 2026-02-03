from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import datetime
import random

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent=f"skysense_final_v130_{random.randint(1000,9999)}")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA ---
history_log = [] 
historical_stats = [] # Stores {date, aqi, pm25} for comparison
current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "avg_aqi": 0, "avg_pm1": 0, "avg_pm25": 0, "avg_pm10": 0, "avg_temp": 0, "avg_hum": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never"
}

# --- HELPER: CHECK IF DRONE MOVED ---
def has_moved(lat, lon):
    gps_list = current_data['chart_data']['gps']
    if not gps_list: return True 
    last_pt = gps_list[-1]
    return (abs(lat - last_pt['lat']) > 0.0001 or abs(lon - last_pt['lon']) > 0.0001)

# --- ROBUST FILE READER ---
def read_file_safely(file):
    file.seek(0)
    try: return pd.read_csv(file)
    except: pass
    try: file.seek(0); return pd.read_csv(file, encoding='latin1')
    except: pass
    try: file.seek(0); return pd.read_csv(file, sep=None, engine='python', encoding='utf-8', on_bad_lines='skip')
    except: pass
    try: file.seek(0); return pd.read_excel(file)
    except: pass
    raise ValueError("Could not read file. Please ensure it is a valid CSV or Excel file.")

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'lat' in c or 'lal' in c: col_map[col] = 'lat'
        elif 'lon' in c or 'lng' in c: col_map[col] = 'lon'
    return df.rename(columns=col_map)

def get_city_name(lat, lon):
    if lat == 0 or lon == 0: return "No GPS Data"
    formatted_coords = f"{round(lat, 4)}°N, {round(lon, 4)}°E"
    if not geolocator: return formatted_coords
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en', timeout=2)
        if loc:
            add = loc.raw.get('address', {})
            city = add.get('suburb') or add.get('city') or add.get('town') or add.get('county')
            if city: return city
    except: pass
    return formatted_coords

# --- UPDATED DYNAMIC HEALTH LOGIC (STRICT TIERS) ---
def calc_health(val):
    pm25 = val.get('pm25', 0)
    pm10 = val.get('pm10', 0)
    aqi = int((pm25 * 2) + (pm10 * 0.5))
    risks = []
    
    # LEVEL 1: AQI 0 - 100 (Safe)
    if aqi <= 100:
        risks.append({
            "name": "General Well-being",
            "desc": "Air quality is considered satisfactory, and air pollution poses little or no risk.",
            "prob": 5, "level": "Good",
            "recs": ["It is a great day to be active outside.", "Ventilate your home freely.", "No special filtration needed."]
        })
        risks.append({
            "name": "Respiratory Health",
            "desc": "No irritation or respiratory distress expected for general population.",
            "prob": 5, "level": "Good",
            "recs": ["Continue normal outdoor exercises.", "Deep breathing exercises are safe.", "Enjoy the fresh air."]
        })
        risks.append({
            "name": "Sensitive Groups",
            "desc": "People with asthma or allergies can typically enjoy outdoor activities without issue.",
            "prob": 10, "level": "Low",
            "recs": ["Keep usual rescue inhalers just in case.", "Monitor local pollen if you have allergies.", "No masks required."]
        })
        risks.append({
            "name": "Skin & Eye Health",
            "desc": "Clear visibility and low particulate matter mean no irritation.",
            "prob": 0, "level": "Low",
            "recs": ["No protective eyewear needed.", "Standard skincare routine is sufficient.", "Sunscreen is your only concern today."]
        })

    # LEVEL 2: AQI 101 - 200 (Moderate Risk)
    elif aqi <= 200:
        risks.append({
            "name": "Mild Respiratory Irritation",
            "desc": "Sensitive individuals may experience coughing or throat irritation.",
            "prob": 40, "level": "Moderate",
            "recs": ["Limit prolonged outdoor exertion.", "Hydrate frequently to soothe throat.", "Carry water when walking outside."]
        })
        risks.append({
            "name": "Asthma Aggravation",
            "desc": "Air quality is acceptable for most, but may trigger mild asthma symptoms.",
            "prob": 50, "level": "Moderate",
            "recs": ["Keep inhalers accessible at all times.", "Avoid jogging near heavy traffic areas.", "Watch for wheezing symptoms."]
        })
        risks.append({
            "name": "Sinus Pressure",
            "desc": "Particulates may cause minor nasal congestion or sinus pressure.",
            "prob": 30, "level": "Moderate",
            "recs": ["Consider a saline nasal rinse.", "Shower after coming indoors to wash off dust.", "Keep windows closed during traffic hours."]
        })
        risks.append({
            "name": "Fatigue Levels",
            "desc": "Slight reduction in oxygen efficiency may cause quicker tiredness during sports.",
            "prob": 25, "level": "Low",
            "recs": ["Take more breaks during exercise.", "Avoid heavy cardio outdoors.", "Monitor heart rate during activity."]
        })

    # LEVEL 3: AQI 201 - 300 (Poor / Very Unhealthy)
    elif aqi <= 300:
        risks.append({
            "name": "Bronchitis Risk",
            "desc": "High PM levels can inflame the bronchial tubes causing heavy coughing.",
            "prob": 65, "level": "High",
            "recs": ["Avoid all outdoor physical activity.", "Wear a basic mask (N95 preferred) outside.", "Use an air purifier in the bedroom."]
        })
        risks.append({
            "name": "Cardiac Stress",
            "desc": "Fine particles entering the bloodstream can slightly elevate blood pressure.",
            "prob": 50, "level": "High",
            "recs": ["People with heart conditions should stay indoors.", "Avoid salty foods to keep BP low.", "Monitor blood pressure if you feel dizzy."]
        })
        risks.append({
            "name": "Allergic Rhinitis",
            "desc": "High pollution can mimic or worsen severe allergy symptoms.",
            "prob": 70, "level": "High",
            "recs": ["Take antihistamines if prescribed.", "Keep windows sealed tight.", "Change clothes immediately after entering home."]
        })
        risks.append({
            "name": "Eye Irritation",
            "desc": "Dust and chemicals in the air may cause burning or watery eyes.",
            "prob": 60, "level": "Moderate",
            "recs": ["Use lubricating eye drops.", "Wear sunglasses/glasses to block dust.", "Avoid rubbing eyes with unwashed hands."]
        })

    # LEVEL 4: AQI 301 - 400 (Severe)
    elif aqi <= 400:
        risks.append({
            "name": "Acute Respiratory Infection",
            "desc": "Immune system in lungs is compromised, increasing risk of infections.",
            "prob": 80, "level": "Severe",
            "recs": ["Strictly avoid outdoor exposure.", "Wear N95/N99 masks if transit is necessary.", "Steam inhalation twice a day."]
        })
        risks.append({
            "name": "Ischemic Heart Risk",
            "desc": "Reduced oxygen supply to the heart due to pollution stress.",
            "prob": 75, "level": "Severe",
            "recs": ["Elderly should remain strictly indoors.", "Avoid any strenuous physical labor.", "Seek help if experiencing chest heaviness."]
        })
        risks.append({
            "name": "Hypoxia Symptoms",
            "desc": "Lower oxygen intake may lead to headaches and dizziness.",
            "prob": 60, "level": "High",
            "recs": ["Use indoor plants or oxygen concentrators if available.", "Practice shallow, calm breathing.", "Avoid smoking or incense indoors."]
        })
        risks.append({
            "name": "Pneumonia Susceptibility",
            "desc": "Lungs are highly vulnerable to bacterial and viral attacks.",
            "prob": 50, "level": "High",
            "recs": ["Maintain good hand hygiene.", "Stay away from crowded, dusty places.", "Consult a doctor for persistent cough."]
        })

    # LEVEL 5: AQI 401 - 500 (Hazardous)
    elif aqi <= 500:
        risks.append({
            "name": "Severe Lung Impairment",
            "desc": "Healthy people will experience reduced endurance and breathing difficulty.",
            "prob": 90, "level": "Critical",
            "recs": ["Do not go outside under any circumstances.", "Seal window gaps with wet towels.", "Run air purifiers on maximum speed."]
        })
        risks.append({
            "name": "Cerebrovascular Risk",
            "desc": "Increased risk of stroke due to thickened blood and inflammation.",
            "prob": 60, "level": "High",
            "recs": ["Stay hydrated to keep blood thin.", "Avoid stress and sudden movements.", "Keep emergency contacts ready."]
        })
        risks.append({
            "name": "Systemic Inflammation",
            "desc": "Pollutants entering blood trigger inflammation throughout the body.",
            "prob": 85, "level": "Critical",
            "recs": ["Consume anti-inflammatory foods (turmeric, berries).", "Rest as much as possible.", "Avoid cooking that produces smoke (frying)."]
        })
        risks.append({
            "name": "Pulmonary Edema Risk",
            "desc": "Fluid buildup in air sacs due to toxic chemical irritation.",
            "prob": 40, "level": "Severe",
            "recs": ["Seek immediate medical care for difficulty breathing.", "Sleep with head elevated.", "Avoid lying flat if breathing is hard."]
        })

    # LEVEL 6: AQI 500+ (Emergency / Toxic)
    else:
        risks.append({
            "name": "Acute Respiratory Distress (ARDS)",
            "desc": "Life-threatening lung failure potential. Oxygen absorption is blocked.",
            "prob": 95, "level": "Emergency",
            "recs": ["Evacuate to a cleaner area if possible.", "Use medical-grade oxygen if prescribed.", "Wear N99/P100 respirator if movement is forced."]
        })
        risks.append({
            "name": "Cardiac Arrest Risk",
            "desc": "Extremely high stress on heart muscles due to toxic air.",
            "prob": 70, "level": "Emergency",
            "recs": ["Absolute bed rest suggested for patients.", "Keep defibrillator/emergency services on speed dial.", "Do not exert yourself in any way."]
        })
        risks.append({
            "name": "Asphyxiation Hazard",
            "desc": "Air is chemically toxic. Feeling of choking or suffocation.",
            "prob": 90, "level": "Emergency",
            "recs": ["Create a 'clean room' with no ventilation leaks.", "Use double-filtration air purifiers.", "Limit talking to conserve oxygen."]
        })
        risks.append({
            "name": "Permanent Lung Damage",
            "desc": "Long-term scarring of lung tissue (Fibrosis) possible even after short exposure.",
            "prob": 80, "level": "Critical",
            "recs": ["Follow up with a pulmonologist immediately.", "Start long-term lung detox measures.", "Consider relocation if conditions persist."]
        })

    return risks

# --- HTML PARTS ---
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
"""

HTML_STYLE = """
    <style>
        :root { --bg: #fdfbf7; --card-bg: #ffffff; --text-main: #1c1917; --text-muted: #78716c; --primary: #0f172a; --orange: #ea580c; --danger: #dc2626; --success: #16a34a; --border: #e7e5e4; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; color: var(--text-main); letter-spacing: -0.5px; display:flex; align-items:center; gap:10px; }
        .refresh-btn { background: #e5e5e5; color: var(--text-main); border: none; padding: 10px 20px; border-radius: 30px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .alert-banner { background: #fff7ed; border: 1px solid #ffedd5; color: #9a3412; padding: 20px; border-radius: 12px; margin-bottom: 30px; display:flex; align-items:center; gap:15px; }
        .nav-tabs { display: flex; gap: 10px; background: white; padding: 8px; border-radius: 50px; margin-bottom: 30px; border: 1px solid var(--border); width: fit-content; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .tab-btn { border: none; background: transparent; padding: 10px 24px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-radius: 30px; transition: 0.2s; font-size: 0.9rem; }
        .tab-btn.active { background: var(--primary); color: white; }
        .section { display: none; animation: fadeIn 0.3s ease; }
        .section.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
        .dashboard-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 25px; }
        .card { background: var(--card-bg); border-radius: 20px; padding: 30px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02); border: 1px solid var(--border); height: 100%; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; }
        .card-title { font-size: 1.1rem; font-weight: 700; color: var(--text-main); }
        .aqi-num { font-size: 5rem; font-weight: 800; color: var(--danger); line-height: 1; text-align: center; }
        .aqi-sub { text-align: center; color: var(--text-muted); margin-top: 10px; font-weight: 500; }
        .stat-row { display: flex; gap: 15px; margin-top: 30px; }
        .stat-box { flex: 1; background: #fafaf9; padding: 15px; border-radius: 12px; text-align: center; }
        .stat-val { font-size: 1.5rem; font-weight: 800; color: var(--text-main); }
        .health-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media(max-width: 800px) { .health-grid { grid-template-columns: 1fr; } }
        .risk-card { background: white; border: 1px solid var(--border); border-radius: 16px; padding: 25px; border-left: 5px solid var(--danger); }
        .risk-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .risk-title { font-weight: 700; font-size: 1.05rem; }
        .risk-badge { background: #fee2e2; color: #991b1b; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; }
        .risk-desc { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 15px; }
        .progress-bg { height: 8px; background: #f5f5f4; border-radius: 4px; overflow: hidden; margin-bottom: 20px; }
        .progress-fill { height: 100%; background: var(--danger); border-radius: 4px; width: 0%; transition: width 1s; }
        .rec-box { background: #fdfbf7; padding: 15px; border-radius: 12px; }
        .rec-title { font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 8px; }
        .rec-list { list-style: none; font-size: 0.9rem; color: var(--text-main); padding-left: 0; }
        .rec-list li { margin-bottom: 5px; position: relative; padding-left: 15px; }
        .rec-list li::before { content: "•"; color: var(--primary); font-weight: bold; position: absolute; left: 0; }
        .upload-card { display:block; text-align:center; padding: 40px; border: 2px dashed #d6d3d1; border-radius: 20px; background: #fafaf9; cursor: pointer; transition: 0.2s; }
        .upload-card:hover { border-color: var(--primary); background: #f0fdf4; }
        .upload-icon { font-size: 3rem; color: #d6d3d1; margin-bottom: 15px; transition:0.2s; }
        .upload-card:hover .upload-icon { color: var(--primary); }
        .date-picker { width:100%; padding:15px; border:1px solid #e7e5e4; border-radius:12px; font-size:1rem; margin-bottom:20px; font-family:'Inter',sans-serif; }
        .btn-primary { display:inline-block; background:#0f172a; color:white; padding:12px 25px; border-radius:8px; text-decoration:none; margin-right:10px; border:none; cursor:pointer; font-weight:600; font-size:0.9rem; }
        .history-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .history-table th { text-align: left; padding: 12px; border-bottom: 2px solid #e7e5e4; color: var(--text-muted); font-size: 0.85rem; text-transform: uppercase; }
        .history-table td { padding: 15px 12px; border-bottom: 1px solid #e7e5e4; color: var(--text-main); font-size: 0.95rem; }
        .history-table tr:last-child td { border-bottom: none; }
        .status-badge { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; background: #dcfce7; color: #166534; }
        
        .filter-btn { padding: 8px 16px; border: 1px solid #e7e5e4; background: white; border-radius: 20px; cursor: pointer; margin-right: 5px; font-weight: 500; font-size: 0.85rem; }
        .filter-btn.active { background: var(--primary); color: white; border-color: var(--primary); }
    </style>
</head>
"""

HTML_BODY = """
<body>
<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-cloud"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh Data</button>
    </div>

    <div class="alert-banner">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <div><strong>System Status:</strong> <span id="alert-msg">Waiting for data...</span></div>
    </div>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="sw('overview')">Overview</button>
        <button class="tab-btn" onclick="sw('gps')">GPS Charts</button>
        <button class="tab-btn" onclick="sw('analytics')">Analytics</button>
        <button class="tab-btn" onclick="sw('disease')">Disease Reports</button>
        <button class="tab-btn" onclick="sw('history')">History</button>
        <button class="tab-btn" onclick="sw('esp32')">ESP32</button>
        <button class="tab-btn" onclick="sw('upload')">Upload</button>
        <button class="tab-btn" onclick="sw('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="dashboard-grid">
            <div class="card">
                <div class="card-header"><div class="card-title">Real-Time Air Quality</div></div>
                <div class="aqi-num" id="aqi-val">--</div>
                <div class="aqi-sub">AQI (US Standard)</div>
                <div class="aqi-sub" style="margin-top:5px;"><i class="fa-solid fa-location-dot"></i> <span id="loc-name">Unknown</span></div>
                <div class="stat-row">
                    <div class="stat-box"><div class="stat-val" id="val-pm1">--</div><div style="font-size:0.8rem">PM 1.0</div></div>
                    <div class="stat-box"><div class="stat-val" id="val-pm25">--</div><div style="font-size:0.8rem">PM 2.5</div></div>
                    <div class="stat-box"><div class="stat-val" id="val-pm10">--</div><div style="font-size:0.8rem">PM 10</div></div>
                </div>
            </div>
            <div class="card">
                <div class="card-title" style="margin-bottom:20px;">Quick Health Summary</div>
                <div id="mini-risk-list">Waiting for data...</div>
            </div>
        </div>
    </div>

    <div id="gps" class="section">
        <div class="card">
            <div class="card-title">AQI Level vs GPS Location</div>
            <div style="height:500px; margin-top:20px;"><canvas id="mainChart"></canvas></div>
        </div>
    </div>

    <div id="analytics" class="section">
        <div class="card">
            <div class="card-header">
                <div class="card-title">Historical AQI Trends</div>
                <div>
                    <button class="filter-btn active" onclick="updateTrend(7)">7 Days</button>
                    <button class="filter-btn" onclick="updateTrend(30)">30 Days</button>
                    <button class="filter-btn" onclick="updateTrend(0)">All Time</button>
                </div>
            </div>
            <div style="height:400px;"><canvas id="trendChart"></canvas></div>
            <p style="text-align:center; color:#78716c; margin-top:10px; font-size:0.9rem;">Comparison of AQI levels based on uploaded flight data.</p>
        </div>
    </div>

    <div id="disease" class="section">
        <div class="card-title" style="margin-bottom:20px;">Detailed Health Risk Analysis</div>
        <div class="health-grid" id="full-health-grid">
            <p style="color:#78716c">Upload data to see health analysis.</p>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-title">Upload History</div>
            <table class="history-table">
                <thead><tr><th>Date</th><th>Filename</th><th>AQI</th></tr></thead>
                <tbody id="history-body">
                    <tr><td colspan="3" style="text-align:center; color:#78716c;">No files uploaded yet.</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="card">
            <div class="card-title">Live Telemetry</div>
            <div id="esp-console" style="background:#0f172a; color:#22c55e; padding:20px; border-radius:12px; font-family:monospace; height:200px; overflow-y:auto; margin-top:20px;"></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-title" style="margin-bottom:20px;">Upload Flight Data</div>
            <p style="color:#78716c; margin-bottom:10px;">Select the date of the flight:</p>
            <input type="date" id="upload-date" class="date-picker">
            <label class="upload-card">
                <i class="fa-solid fa-cloud-arrow-up upload-icon"></i>
                <div id="upload-text" style="font-weight:600; font-size:1.1rem; color:#1c1917;">Click to Upload File</div>
                <div style="color:#78716c; font-size:0.9rem; margin-top:5px;">Supports CSV & Excel</div>
                <input type="file" id="fileInput" style="display:none;">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-title">Export Report</div>
            <p style="color:#78716c; margin-top:10px; margin-bottom:25px;">
                Download the complete dataset with calculated averages, health risks, and precautionary measures.
            </p>
            <div style="display:flex; gap:10px;">
                <a href="/export/text" class="btn-primary"><i class="fa-solid fa-file-lines"></i> Export as Text File</a>
            </div>
        </div>
    </div>
</div>
"""

HTML_SCRIPT = """
<script>
    let mainChart = null;
    let trendChart = null;
    let rawHistory = []; // Stores loaded history data

    function sw(id) {
        document.querySelectorAll('.section').forEach(e => e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(e => e.classList.remove('active'));
        document.querySelector(`button[onclick="sw('${id}')"]`).classList.add('active');
        // If switching to analytics, force render
        if(id === 'analytics') updateTrend(7); 
    }

    document.getElementById('upload-date').valueAsDate = new Date();

    setInterval(() => { fetch('/api/data').then(r => r.json()).then(d => {
        rawHistory = d.historical_stats || [];
        updateUI(d);
    }); }, 3000);

    document.getElementById('fileInput').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        const dateInput = document.getElementById('upload-date');
        if(!file) return;
        const txt = document.getElementById('upload-text'); txt.innerText = "Uploading...";
        const fd = new FormData(); fd.append('file', file); fd.append('date', dateInput.value);
        try {
            const res = await fetch('/upload', { method: 'POST', body: fd });
            const d = await res.json();
            if(d.error) { 
                alert("Server Error: " + d.error); 
                txt.innerText = "Upload Failed"; 
            } else { 
                txt.innerText = "Success!"; 
                rawHistory = d.data.historical_stats || [];
                updateUI(d.data); 
                setTimeout(()=>sw('overview'), 500); 
            }
        } catch(e) { 
            alert("Upload Failed. Ensure the file is a valid CSV or Excel."); 
            txt.innerText = "Retry"; 
        }
    });

    // --- TREND CHART LOGIC ---
    function updateTrend(days) {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');

        if(!rawHistory || rawHistory.length === 0) return;

        const now = new Date();
        const cutoff = new Date();
        cutoff.setDate(now.getDate() - days);

        let filtered = rawHistory.filter(d => {
            if(days === 0) return true;
            return new Date(d.date) >= cutoff;
        }).sort((a,b) => new Date(a.date) - new Date(b.date));

        const labels = filtered.map(d => d.date);
        const data = filtered.map(d => d.aqi);

        const ctx = document.getElementById('trendChart').getContext('2d');
        if(trendChart) trendChart.destroy();

        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Average AQI',
                    data: data,
                    borderColor: '#0f172a',
                    backgroundColor: 'rgba(15, 23, 42, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    function updateUI(data) {
        document.getElementById('aqi-val').innerText = data.aqi;
        document.getElementById('val-pm1').innerText = data.pm1 || '--';
        document.getElementById('val-pm25').innerText = data.pm25 || '--';
        document.getElementById('val-pm10').innerText = data.pm10 || '--';
        document.getElementById('loc-name').innerText = data.location_name;
        
        let aqiStatus = "Good";
        if(data.aqi > 100) aqiStatus = "Moderate";
        if(data.aqi > 200) aqiStatus = "Poor";
        if(data.aqi > 300) aqiStatus = "Severe";
        if(data.aqi > 400) aqiStatus = "Hazardous";
        if(data.aqi > 500) aqiStatus = "Emergency";
        
        document.getElementById('alert-msg').innerText = `${aqiStatus} (AQI: ${data.aqi})`;

        // HEALTH REPORTS (UPDATED)
        const grid = document.getElementById('full-health-grid');
        const miniList = document.getElementById('mini-risk-list');
        if(data.health_risks.length > 0) {
            grid.innerHTML = ''; miniList.innerHTML = '';
            data.health_risks.forEach(r => {
                let color, badgeColor, badgeText;
                
                if(r.level === 'Good' || r.level === 'Low') {
                     color='#16a34a'; badgeColor='#dcfce7'; badgeText='#166534';
                } else if(r.level === 'Moderate') {
                     color='#ea580c'; badgeColor='#ffedd5'; badgeText='#9a3412';
                } else {
                     color='#dc2626'; badgeColor='#fee2e2'; badgeText='#991b1b';
                }
                
                grid.innerHTML += `<div class="risk-card" style="border-left-color:${color}">
                    <div class="risk-header"><div class="risk-title">${r.name}</div><div class="risk-badge" style="background:${badgeColor}; color:${badgeText}">${r.level}</div></div>
                    <div class="risk-desc">${r.desc}</div>
                    <div class="progress-bg"><div class="progress-fill" style="width:${r.prob}%; background:${color}"></div></div>
                    <div class="rec-box"><div class="rec-title">RECOMMENDATIONS</div><ul class="rec-list">${r.recs.map(x => `<li>${x}</li>`).join('')}</ul></div></div>`;
                
                miniList.innerHTML += `<div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f5f5f4;"><span style="font-weight:600;">${r.name}</span><span style="font-weight:700; color:${color}">${r.level}</span></div>`;
            });
        }

        // HISTORY UPDATE
        const histBody = document.getElementById('history-body');
        if(data.history && data.history.length > 0) {
            histBody.innerHTML = '';
            data.history.forEach(h => {
                histBody.innerHTML += `<tr><td>${h.date}</td><td>${h.filename}</td><td><strong>${h.aqi || '--'}</strong></td></tr>`;
            });
        }

        // HORIZONTAL BAR CHART
        if(data.chart_data.aqi.length > 0) {
            const ctx = document.getElementById('mainChart').getContext('2d');
            const labels = data.chart_data.gps.map((g, i) => {
               return `${data.location_name.split(',')[0]} (${Number(g.lat).toFixed(3)}, ${Number(g.lon).toFixed(3)})`;
            });

            if(mainChart) mainChart.destroy();
            mainChart = new Chart(ctx, { 
                type: 'bar', 
                data: { 
                    labels: labels, 
                    datasets: [{ 
                        label: 'AQI Level', 
                        data: data.chart_data.aqi, 
                        backgroundColor: '#3b82f6', 
                        borderRadius: 5,
                        barPercentage: 0.6
                    }] 
                }, 
                options: { 
                    indexAxis: 'y', 
                    responsive: true, 
                    maintainAspectRatio: false,
                    scales: {
                        x: { beginAtZero: true, grid: { display: true } },
                        y: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 15 } }
                    },
                    plugins: { legend: { display: false } }
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
def home(): return render_template_string(HTML_HEAD + HTML_STYLE + HTML_BODY + HTML_SCRIPT)

@app.route('/api/data')
def get_data(): 
    current_data['history'] = history_log
    current_data['historical_stats'] = historical_stats
    return jsonify(current_data)

@app.route('/upload', methods=['POST'])
def upload_file():
    global current_data
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    f = request.files['file']
    dt = request.form.get('date', datetime.datetime.now().strftime('%Y-%m-%d'))
    try:
        df = read_file_safely(f)
        df = normalize_columns(df)
        for c in ['pm1','pm25','pm10','temp','hum','lat','lon']: 
            if c not in df.columns: df[c] = 0
        
        valid_rows = []
        last_added = None
        for i, r in df.head(100).iterrows(): 
            if r['lat'] == 0 or r['lon'] == 0: continue
            
            is_duplicate = False
            if last_added is not None:
                if abs(r['lat'] - last_added['lat']) < 0.0001 and abs(r['lon'] - last_added['lon']) < 0.0001:
                    is_duplicate = True
            
            if not is_duplicate:
                valid_rows.append(r)
                last_added = r

        if not valid_rows: raise ValueError("No valid GPS data found (or all duplicates).")
        
        filtered_df = pd.DataFrame(valid_rows)
        avgs = {k: round(filtered_df[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int((avgs['pm25']*2) + (avgs['pm10']*0.5))
        
        loc = get_city_name(valid_rows[0]['lat'], valid_rows[0]['lon'])
        
        gps, aqis = [], []
        for r in valid_rows:
            aqis.append(int((r['pm25']*2)+(r['pm10']*0.5)))
            gps.append({"lat":r['lat'], "lon":r['lon']})
            
        history_log.insert(0, {"date":dt, "filename":f.filename, "status":"Success", "aqi": aqi})
        
        existing_record = next((item for item in historical_stats if item["date"] == dt), None)
        if existing_record:
            existing_record['aqi'] = aqi 
        else:
            historical_stats.append({"date": dt, "aqi": aqi, "pm25": avgs['pm25']})
            
        historical_stats.sort(key=lambda x: x['date'])
        
        current_data.update({
            "aqi": aqi, "location_name": loc, 
            "avg_pm1": avgs['pm1'], "avg_pm25": avgs['pm25'], "avg_pm10": avgs['pm10'],
            "avg_temp": avgs['temp'], "avg_hum": avgs['hum'],
            "pm1": avgs['pm1'], "pm25": avgs['pm25'], "pm10": avgs['pm10'], 
            "health_risks": calc_health({"pm25":avgs['pm25'], "pm10":avgs['pm10'], "aqi":aqi}), 
            "chart_data": {"aqi":aqis,"gps":gps}, 
            "last_updated": datetime.datetime.now().strftime("%H:%M")
        })
        return jsonify({"message": "Success", "data": current_data})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def sensor():
    try:
        d = request.json
        current_data.update(d)
        aqi = int((d.get('pm25',0)*2) + (d.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['health_risks'] = calc_health(current_data)
        current_data['location_name'] = get_city_name(d.get('lat',0), d.get('lon',0))
        current_data['last_updated'] = datetime.datetime.now().strftime("%H:%M")
        
        if has_moved(d.get('lat',0), d.get('lon',0)) and d.get('lat',0) != 0:
            current_data['chart_data']['aqi'].append(aqi)
            current_data['chart_data']['gps'].append({"lat":d.get('lat',0),"lon":d.get('lon',0)})
            if len(current_data['chart_data']['aqi']) > 50: 
                current_data['chart_data']['aqi'].pop(0)
                current_data['chart_data']['gps'].pop(0)
        
        current_data['esp32_log'].insert(0, f"> AQI:{aqi} | T:{d.get('temp')}")
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"error":str(e)}), 400

@app.route('/export/text')
def export_text():
    d = current_data
    report = f"""
==================================================
SKYSENSE AIR QUALITY & HEALTH REPORT
==================================================
Date: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Location: {d['location_name']}

--------------------------------------------------
1. ENVIRONMENTAL SUMMARY (AVERAGES)
--------------------------------------------------
Air Quality Index (AQI): {d['aqi']}
Status: {'Poor' if d['aqi'] > 100 else 'Good'}

Particulate Matter:
- PM 1.0 : {d.get('avg_pm1', d.get('pm1', 0))} ug/m3
- PM 2.5 : {d.get('avg_pm25', d.get('pm25', 0))} ug/m3
- PM 10  : {d.get('avg_pm10', d.get('pm10', 0))} ug/m3

Conditions:
- Temperature: {d.get('avg_temp', d.get('temp', 0))} °C
- Humidity:    {d.get('avg_hum', d.get('hum', 0))} %

--------------------------------------------------
2. HEALTH RISK ANALYSIS & PRECAUTIONS
--------------------------------------------------
"""
    for risk in d['health_risks']:
        report += f"\n[RISK] {risk['name']} ({risk['level']})\n"
        report += f"Description: {risk['desc']}\n"
        report += "Precautions:\n"
        for rec in risk['recs']:
            report += f" - {rec}\n"
    
    report += "\n==================================================\nGenerated by SkySense System\n"
    
    return send_file(
        io.BytesIO(report.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"SkySense_Report_{datetime.datetime.now().strftime('%Y%m%d')}.txt"
    )

if __name__ == '__main__':
    app.run(debug=True)
