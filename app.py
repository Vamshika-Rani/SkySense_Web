from flask import Flask, render_template_string, jsonify, request, send_from_directory, send_file
import pandas as pd
import io
import datetime
import random
import os
import time

# --- SETUP ---
try:
    from geopy.geocoders import Nominatim
    # Random User Agent to prevent blocking
    geolocator = Nominatim(user_agent=f"skysense_final_v100_{random.randint(10000,99999)}")
except ImportError:
    geolocator = None

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
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
    "esp32_log": ["> System Initialized..."], "last_updated": "Never"
}

# --- BACKEND HELPERS ---
def has_moved(lat, lon):
    gps = current_data['chart_data']['gps']
    if not gps: return True 
    return (abs(lat - gps[-1]['lat']) > 0.0001 or abs(lon - gps[-1]['lon']) > 0.0001)

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
    for c in df.columns:
        cl = str(c).lower().strip()
        if 'pm1.0' in cl or ('pm1' in cl and 'pm10' not in cl): col_map[c] = 'pm1'
        elif 'pm25' in cl or 'pm2.5' in cl: col_map[c] = 'pm25'
        elif 'pm10' in cl: col_map[c] = 'pm10'
        elif 'temp' in cl: col_map[c] = 'temp'
        elif 'hum' in cl: col_map[c] = 'hum'
        elif 'lat' in cl: col_map[c] = 'lat'
        elif 'lon' in cl: col_map[c] = 'lon'
    return df.rename(columns=col_map)

def get_city_name(lat, lon):
    if lat == 0 or lon == 0: return "No GPS Signal"
    
    # 1. Check Cache
    key = (round(lat, 3), round(lon, 3))
    if key in location_cache: return location_cache[key]
    
    coord_str = f"{round(lat, 4)}, {round(lon, 4)}"
    if not geolocator: return coord_str
    
    # 2. Try Geocoding (Aggressive Fallback)
    try:
        for _ in range(2): 
            try:
                loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en', timeout=8)
                if loc:
                    add = loc.raw.get('address', {})
                    # Try getting ANY name, starting from most specific
                    name = (add.get('neighbourhood') or 
                            add.get('suburb') or 
                            add.get('village') or 
                            add.get('road') or 
                            add.get('residential') or
                            add.get('city') or 
                            add.get('town') or 
                            add.get('county') or 
                            add.get('state'))
                    
                    if name:
                        # Append City if we found a small area
                        if name != add.get('city') and add.get('city'):
                            name = f"{name}, {add.get('city')}"
                        
                        location_cache[key] = name
                        return name
            except: time.sleep(1)
    except: pass
    return coord_str

def calc_health(val):
    aqi = int((val.get('pm25', 0) * 2) + (val.get('pm10', 0) * 0.5))
    if aqi <= 100:
        return [
            {"name": "General Well-being", "desc": "Air quality is satisfactory. Great day for outdoor activity.", "prob": 5, "level": "Good", "recs": ["Ventilate your home freely.", "Enjoy outdoor activities.", "No special filtration needed."]},
            {"name": "Respiratory Health", "desc": "No irritation or respiratory distress expected.", "prob": 5, "level": "Good", "recs": ["Continue normal exercise.", "Deep breathing is safe.", "Enjoy the fresh air."]},
            {"name": "Sensitive Groups", "desc": "People with allergies can enjoy outdoors.", "prob": 10, "level": "Low", "recs": ["Keep usual inhalers just in case.", "Monitor pollen levels.", "No masks required."]},
            {"name": "Skin & Eye", "desc": "Clear visibility, no irritation.", "prob": 0, "level": "Low", "recs": ["No protective eyewear needed.", "Standard skincare.", "Use sunscreen."]}
        ]
    elif aqi <= 200:
        return [
            {"name": "Mild Irritation", "desc": "Sensitive people may feel throat tickle.", "prob": 40, "level": "Moderate", "recs": ["Limit prolonged exertion.", "Hydrate throat.", "Carry water."]},
            {"name": "Asthma Risk", "desc": "May trigger mild asthma symptoms.", "prob": 50, "level": "Moderate", "recs": ["Keep inhalers accessible.", "Avoid heavy traffic areas.", "Watch for wheezing."]},
            {"name": "Sinus Pressure", "desc": "Minor nasal congestion possible.", "prob": 30, "level": "Moderate", "recs": ["Consider saline rinse.", "Shower after outdoors.", "Close windows."]},
            {"name": "Fatigue", "desc": "Slight reduction in oxygen efficiency.", "prob": 25, "level": "Low", "recs": ["Take more breaks.", "Avoid heavy cardio.", "Monitor heart rate."]}
        ]
    elif aqi <= 300:
        return [
            {"name": "Bronchitis Risk", "desc": "Inflamed bronchial tubes, heavy coughing.", "prob": 65, "level": "High", "recs": ["Avoid outdoor activity.", "Wear N95 mask.", "Use air purifier."]},
            {"name": "Cardiac Stress", "desc": "Elevated blood pressure.", "prob": 50, "level": "High", "recs": ["Heart patients stay indoors.", "Low salt diet.", "Monitor BP."]},
            {"name": "Allergies", "desc": "Worsened allergy symptoms.", "prob": 70, "level": "High", "recs": ["Take antihistamines.", "Seal windows.", "Change clothes."]},
            {"name": "Eye Irritation", "desc": "Burning or watery eyes.", "prob": 60, "level": "Moderate", "recs": ["Use eye drops.", "Wear sunglasses.", "Don't rub eyes."]}
        ]
    elif aqi <= 400:
        return [
            {"name": "Lung Infection", "desc": "Compromised lung immunity.", "prob": 80, "level": "Severe", "recs": ["Strictly avoid outdoors.", "Wear N99 mask.", "Steam inhalation."]},
            {"name": "Ischemic Risk", "desc": "Reduced heart oxygen.", "prob": 75, "level": "Severe", "recs": ["Elderly stay inside.", "No physical labor.", "Watch chest pain."]},
            {"name": "Hypoxia", "desc": "Headaches and dizziness.", "prob": 60, "level": "High", "recs": ["Use oxygen/plants.", "Calm breathing.", "No smoking."]},
            {"name": "Pneumonia", "desc": "Vulnerable to bacteria.", "prob": 50, "level": "High", "recs": ["Wash hands often.", "Avoid crowds.", "Consult doctor."]}
        ]
    elif aqi <= 500:
        return [
            {"name": "Lung Impairment", "desc": "Breathing difficulty for everyone.", "prob": 90, "level": "Critical", "recs": ["Do not go out.", "Wet towels on windows.", "Max air purifier."]},
            {"name": "Stroke Risk", "desc": "Thickened blood.", "prob": 60, "level": "High", "recs": ["Hydrate heavily.", "Avoid stress.", "Emergency contacts ready."]},
            {"name": "Inflammation", "desc": "Systemic body inflammation.", "prob": 85, "level": "Critical", "recs": ["Anti-inflammatory food.", "Rest fully.", "No frying."]},
            {"name": "Pulmonary Edema", "desc": "Fluid in lungs.", "prob": 40, "level": "Severe", "recs": ["Medical care if breathing hard.", "Sleep elevated.", "Don't lie flat."]}
        ]
    else:
        return [
            {"name": "ARDS", "desc": "Lung failure potential.", "prob": 95, "level": "Emergency", "recs": ["Evacuate area.", "Medical oxygen.", "N99 respirator."]},
            {"name": "Cardiac Arrest", "desc": "Extreme heart stress.", "prob": 70, "level": "Emergency", "recs": ["Bed rest.", "Defibrillator ready.", "No exertion."]},
            {"name": "Asphyxiation", "desc": "Toxic choking feeling.", "prob": 90, "level": "Emergency", "recs": ["Clean room.", "Double filtration.", "Limit talking."]},
            {"name": "Lung Damage", "desc": "Permanent scarring risk.", "prob": 80, "level": "Critical", "recs": ["See pulmonologist.", "Lung detox.", "Relocate."]}
        ]

# --- FRONTEND TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SkySense | Pro Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
<style>
:root{--bg:#fdfbf7;--card:#fff;--text:#1c1917;--prim:#0f172a;--dang:#dc2626;}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);padding:30px 20px;margin:0;}
.container{max-width:1200px;margin:0 auto;}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px;}
.logo{font-size:1.8rem;font-weight:800;display:flex;gap:10px;align-items:center;}
.nav-tabs{display:flex;gap:10px;background:#fff;padding:8px;border-radius:50px;margin-bottom:30px;width:fit-content;box-shadow:0 2px 5px #0000000d;}
.tab-btn{border:none;background:0 0;padding:10px 20px;font-weight:600;cursor:pointer;border-radius:30px;color:#666;}
.tab-btn.active{background:var(--prim);color:#fff;}
.section{display:none;animation:fadeIn 0.3s;} .section.active{display:block;}
.grid{display:grid;grid-template-columns:1.2fr 1fr;gap:25px;}
.card{background:var(--card);border-radius:20px;padding:25px;box-shadow:0 4px 6px -1px #00000005;border:1px solid #e5e7eb;}
.aqi-box{text-align:center;} .aqi-val{font-size:5rem;font-weight:800;color:var(--dang);line-height:1;}
.stat-row{display:flex;gap:15px;margin-top:25px;} .stat{flex:1;background:#fafaf9;padding:15px;text-align:center;border-radius:10px;font-weight:700;}
.risk-card{border:1px solid #e5e7eb;border-radius:12px;padding:20px;border-left:5px solid var(--dang);margin-bottom:15px;background:#fff;}
.hist-table{width:100%;border-collapse:collapse;} .hist-table th{text-align:left;padding:10px;border-bottom:2px solid #eee;} .hist-table td{padding:10px;border-bottom:1px solid #eee;}
.upload-card{border:2px dashed #cbd5e1;padding:30px;text-align:center;border-radius:15px;cursor:pointer;transition:0.2s;background:#fafaf9;display:flex;flex-direction:column;align-items:center;gap:10px;} 
.upload-card:hover{border-color:var(--prim);background:#f1f5f9;}
.upload-icon{font-size:2rem;color:#94a3b8;}
/* FIXED ANALYTICS & UPLOAD LAYOUTS */
.anl-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;}
.sel-box{padding:8px;border-radius:8px;border:1px solid #ccc;font-family:inherit;}
.upload-container{max-width:600px;margin:0 auto;}
@keyframes fadeIn{from{opacity:0;transform:translateY(5px);}to{opacity:1;transform:translateY(0);}}
</style>
</head>
<body>
<div class="container">
 <div class="header">
  <div class="logo"><i class="fa-solid fa-cloud"></i> SkySense</div>
  <button onclick="location.reload()" style="padding:10px 20px;border-radius:20px;border:none;cursor:pointer;background:#e2e8f0;font-weight:600;">Refresh</button>
 </div>
 <div class="nav-tabs">
  <button class="tab-btn active" onclick="sw('ov')">Overview</button>
  <button class="tab-btn" onclick="sw('gps')">Charts</button>
  <button class="tab-btn" onclick="sw('anl')">Analytics</button>
  <button class="tab-btn" onclick="sw('health')">Health</button>
  <button class="tab-btn" onclick="sw('hist')">History</button>
  <button class="tab-btn" onclick="sw('esp')">ESP32</button>
  <button class="tab-btn" onclick="sw('up')">Upload</button>
  <button class="tab-btn" onclick="sw('exp')">Export</button>
 </div>

 <div id="ov" class="section active">
  <div class="grid">
   <div class="card aqi-box">
    <h3>Live Air Quality</h3>
    <div class="aqi-val" id="aqi">--</div>
    <div style="color:#666;margin-top:5px;font-weight:600;font-size:1.1rem;" id="loc">Waiting...</div>
    <div class="stat-row">
     <div class="stat"><div id="p1">--</div><small>PM1.0</small></div>
     <div class="stat"><div id="p2">--</div><small>PM2.5</small></div>
     <div class="stat"><div id="p10">--</div><small>PM10</small></div>
    </div>
   </div>
   <div class="card">
    <h3>Health Summary</h3>
    <div id="mini-health">Loading...</div>
   </div>
  </div>
 </div>

 <div id="gps" class="section">
  <div class="card"><h3>AQI Level vs Location</h3><div style="height:500px;"><canvas id="chartGps"></canvas></div></div>
 </div>

 <div id="anl" class="section">
  <div class="card">
   <div class="anl-header">
    <h3>Historical Trends</h3>
    <div>
     <label style="font-size:0.9rem;margin-right:10px;">Select Period:</label>
     <select id="trendFilter" onchange="upTr()" class="sel-box">
      <option value="7">Last 7 Days</option>
      <option value="30">Last 30 Days</option>
      <option value="120">Last 120 Days</option>
      <option value="365">Last 1 Year</option>
     </select>
    </div>
   </div>
   <div style="height:500px;"><canvas id="chartTr"></canvas></div>
  </div>
 </div>

 <div id="health" class="section"><div class="card"><h3>Detailed Analysis</h3><div id="full-health"></div></div></div>

 <div id="hist" class="section">
  <div class="card"><h3>Upload Log</h3>
   <table class="hist-table"><thead><tr><th>Date</th><th>File (Click to Download)</th><th>AQI</th></tr></thead><tbody id="tb-hist"></tbody></table>
  </div>
 </div>

 <div id="esp" class="section"><div class="card"><h3>Live Data Stream</h3><div id="logs" style="background:#000;color:#0f0;padding:15px;height:200px;overflow:auto;font-family:monospace;"></div></div></div>

 <div id="up" class="section">
  <div class="card upload-container">
   <h3 style="margin-bottom:20px;">Upload Flight Data</h3>
   <div style="margin-bottom:20px;text-align:left;">
    <label style="display:block;margin-bottom:8px;font-weight:600;color:#64748b;">Select Flight Date</label>
    <input type="date" id="dt" style="width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:10px;font-family:inherit;">
   </div>
   <label class="upload-card">
    <i class="fa-solid fa-cloud-arrow-up upload-icon"></i>
    <div id="upload-text" style="font-weight:600; font-size:1.1rem; color:#1e293b;">Click to Select CSV/Excel</div>
    <div style="color:#64748b; font-size:0.9rem;">Supported formats: .csv, .xlsx</div>
    <input type="file" id="fIn" hidden>
   </label>
  </div>
 </div>

 <div id="exp" class="section"><div class="card"><h3>Export</h3><p>Download a comprehensive report including location, averages, PM levels, and detailed health precautions.</p><a href="/export/text" style="display:inline-block;padding:12px 25px;background:#0f172a;color:#fff;text-decoration:none;border-radius:8px;margin-top:10px;"><i class="fa-solid fa-file-export"></i> Download Report</a></div></div>

</div>
<script>
 let cGps=null, cTr=null, hist=[];
 function sw(id){ document.querySelectorAll('.section').forEach(x=>x.classList.remove('active')); document.getElementById(id).classList.add('active'); document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active')); event.target.classList.add('active'); if(id==='anl') upTr(); }
 document.getElementById('dt').valueAsDate=new Date();
 setInterval(()=>{ fetch('/api/data').then(r=>r.json()).then(d=>{ hist=d.historical_stats||[]; upUI(d); }); },3000);
 document.getElementById('fIn').addEventListener('change',async(e)=>{
  let f=e.target.files[0]; if(!f)return;
  let txt=document.getElementById('upload-text'); txt.innerText="Uploading...";
  let fd=new FormData(); fd.append('file',f); fd.append('date',document.getElementById('dt').value);
  try{ const res=await fetch('/upload',{method:'POST',body:fd}); const d=await res.json(); 
       txt.innerText=d.error?"Upload Failed":"Upload Success!"; 
       if(!d.error){ upUI(d.data); setTimeout(()=>sw('ov'),800); }
  }catch(e){ txt.innerText="Error"; }
 });
 function upTr(){
  let d=parseInt(document.getElementById('trendFilter').value);
  let ctx=document.getElementById('chartTr').getContext('2d'); if(cTr)cTr.destroy();
  let cut=new Date(); cut.setDate(cut.getDate()-d);
  let f=hist.filter(x=>new Date(x.date)>=cut).sort((a,b)=>new Date(a.date)-new Date(b.date));
  cTr=new Chart(ctx,{type:'line',data:{labels:f.map(x=>x.date),datasets:[{label:'Average AQI',data:f.map(x=>x.aqi),borderColor:'#0f172a',backgroundColor:'rgba(15,23,42,0.1)',fill:true,tension:0.3}]},options:{responsive:true,maintainAspectRatio:false}});
 }
 function upUI(d){
  document.getElementById('aqi').innerText=d.aqi; document.getElementById('loc').innerText=d.location_name;
  document.getElementById('p1').innerText=d.pm1; document.getElementById('p2').innerText=d.pm25; document.getElementById('p10').innerText=d.pm10;
  
  let hDiv=document.getElementById('full-health'), mDiv=document.getElementById('mini-health');
  if(d.health_risks.length){
   hDiv.innerHTML=''; mDiv.innerHTML='';
   d.health_risks.forEach(r=>{
    let c=r.level==='Good'?'#16a34a':r.level==='Moderate'?'#ea580c':'#dc2626';
    hDiv.innerHTML+=`<div class="risk-card" style="border-left-color:${c}"><h4>${r.name} (${r.level})</h4><p>${r.desc}</p><ul>${r.recs.map(x=>`<li>${x}</li>`).join('')}</ul></div>`;
    mDiv.innerHTML+=`<div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee;"><span>${r.name}</span><span style="color:${c};font-weight:700">${r.level}</span></div>`;
   });
  }
  let tb=document.getElementById('tb-hist');
  if(d.history.length) tb.innerHTML=d.history.map(x=>`<tr><td>${x.date}</td><td><a href="/uploads/${x.filename}" target="_blank" style="color:#2563eb">${x.filename}</a></td><td>${x.aqi}</td></tr>`).join('');
  
  if(d.chart_data.aqi.length){
   let ctx=document.getElementById('chartGps').getContext('2d');
   let cleanLoc=d.location_name.split('(')[0].trim();
   let labs=d.chart_data.gps.map(g=>`${cleanLoc} (${Number(g.lat).toFixed(3)}, ${Number(g.lon).toFixed(3)})`);
   if(cGps)cGps.destroy();
   cGps=new Chart(ctx,{type:'bar',data:{labels:labs,datasets:[{label:'AQI Level',data:d.chart_data.aqi,backgroundColor:'#3b82f6',borderRadius:4}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{x:{beginAtZero:true}}}});
  }
  document.getElementById('logs').innerText=d.esp32_log.join('\\n');
 }
</script></body></html>
"""

# --- BACKEND ROUTES ---
@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

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
        
        valid = [r for i, r in df.head(100).iterrows() if r.get('lat',0) != 0]
        if not valid: raise ValueError("No GPS Data")
        
        filtered = [valid[0]]
        for r in valid[1:]:
            if has_moved(r['lat'], r['lon']): filtered.append(r)
            
        avgs = {k: round(pd.DataFrame(filtered)[k].mean(), 1) for k in ['pm1','pm25','pm10','temp','hum']}
        aqi = int(avgs['pm25']*2 + avgs['pm10']*0.5)
        loc = get_city_name(filtered[0]['lat'], filtered[0]['lon'])
        
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
    report = f"""==================================================
SKYSENSE DETAILED AIR QUALITY REPORT
==================================================
Date: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Location: {d['location_name']}

1. ENVIRONMENTAL AVERAGES
-------------------------
AQI Level: {d['aqi']}
PM 1.0 : {d.get('avg_pm1', d.get('pm1', 0))} ug/m3
PM 2.5 : {d.get('avg_pm25', d.get('pm25', 0))} ug/m3
PM 10  : {d.get('avg_pm10', d.get('pm10', 0))} ug/m3
Temp   : {d.get('avg_temp', d.get('temp', 0))} °C
Humidity: {d.get('avg_hum', d.get('hum', 0))} %

2. HEALTH RISKS & PRECAUTIONS
-----------------------------"""
    for r in d['health_risks']:
        report += f"\n\n[RISK] {r['name']} ({r['level']})\nDescription: {r['desc']}\nPrecautions:\n"
        for rec in r['recs']: report += f" - {rec}\n"
    report += "\n==================================================\nGenerated by SkySense System\n"
    return send_file(io.BytesIO(report.encode('utf-8')), mimetype='text/plain', as_attachment=True, download_name="SkySense_Report.txt")

if __name__ == '__main__':
    app.run(debug=True)
