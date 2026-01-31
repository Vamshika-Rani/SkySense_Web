from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import datetime

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v21")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- DATA STORE ---
history_log = [] 
current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized..."], "last_updated": "Never"
}

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'lat' in c or 'lal' in c: col_map[col] = 'lat' # Fixes 'lalitude'
        elif 'lon' in c or 'lng' in c: col_map[col] = 'lon'
    return df.rename(columns=col_map)

def get_city_name(lat, lon):
    if not geolocator or lat == 0: return "Unknown Area"
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en')
        if loc: return loc.raw.get('address', {}).get('city') or loc.raw.get('address', {}).get('town') or "Unknown Area"
    except: pass
    return "Unknown Area"

def calc_health(val):
    risks = []
    a_score = (val['pm25']*1.2) + (val['pm10']*0.5)
    risks.append({"name": "Asthma Risk", "prob": min(98, int(a_score)), "level": "High" if a_score>50 else "Moderate"})
    r_score = (val['pm10']*0.8) + (val['hum']<30)*20
    risks.append({"name": "Respiratory", "prob": min(95, int(r_score)), "level": "High" if r_score>60 else "Moderate"})
    c_score = (val['pm25']*0.9)
    risks.append({"name": "Cardiovascular", "prob": min(90, int(c_score)), "level": "High" if c_score>55 else "Moderate"})
    if val['temp']>30: risks.append({"name": "Heat Stress", "prob": min(100, int((val['temp']-30)*10)), "level": "High"})
    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- COMPACT HTML/CSS TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SkySense | Atoms Dark</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
    :root { --bg:#0f172a; --card:#1e293b; --text:#f1f5f9; --muted:#94a3b8; --p:#3b82f6; --o:#f59e0b; --d:#ef4444; --s:#22c55e; --b:#334155; }
    * { box-sizing:border-box; margin:0; padding:0; }
    body { font-family:'Inter',sans-serif; background:var(--bg); color:var(--text); padding:20px; }
    .container { max-width:1200px; margin:0 auto; }
    .header { display:flex; justify-content:space-between; margin-bottom:20px; align-items:center; }
    .logo { font-size:1.5rem; font-weight:800; } .logo i { color:var(--p); margin-right:10px; }
    .refresh-btn { background:var(--p); color:white; border:none; padding:8px 16px; border-radius:8px; cursor:pointer; font-weight:600; }
    .alert-banner { background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); color:var(--o); padding:15px; border-radius:12px; margin-bottom:20px; display:flex; align-items:center; gap:10px; }
    .nav-tabs { display:flex; gap:10px; margin-bottom:20px; overflow-x:auto; padding-bottom:5px; }
    .tab-btn { background:var(--card); border:1px solid var(--b); color:var(--muted); padding:8px 20px; border-radius:8px; cursor:pointer; white-space:nowrap; }
    .tab-btn.active { background:var(--p); color:white; border-color:var(--p); }
    .section { display:none; } .section.active { display:block; }
    .grid { display:grid; grid-template-columns:1.5fr 1fr; gap:20px; }
    @media(max-width:800px){ .grid { grid-template-columns:1fr; } }
    .card { background:var(--card); border-radius:16px; padding:25px; border:1px solid var(--b); height:100%; }
    .card-head { display:flex; justify-content:space-between; font-weight:700; margin-bottom:20px; font-size:1.1rem; }
    .aqi-box { text-align:center; padding:10px 0; }
    .aqi-num { font-size:5rem; font-weight:800; color:var(--o); line-height:1; }
    .bar-row { margin-bottom:12px; }
    .bar-head { display:flex; justify-content:space-between; font-size:0.9rem; margin-bottom:4px; }
    .bar-track { height:6px; background:var(--bg); border-radius:3px; }
    .bar-fill { height:100%; background:var(--p); border-radius:3px; }
    .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:20px; }
    .stat-box { background:var(--bg); padding:15px; border-radius:12px; text-align:center; border:1px solid var(--b); }
    .risk-item { display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid var(--b); font-size:0.95rem; }
    .upload-area { display:block; border:2px dashed var(--b); padding:40px; text-align:center; border-radius:16px; cursor:pointer; background:var(--bg); margin-top:15px; }
    .date-input { width:100%; padding:10px; background:var(--bg); border:1px solid var(--b); color:var(--text); border-radius:8px; margin-bottom:10px; }
    .history-row { display:flex; justify-content:space-between; padding:12px; background:var(--bg); border:1px solid var(--b); border-radius:8px; margin-bottom:8px; }
    .btn-main { background:var(--p); color:white; padding:10px 20px; border-radius:8px; text-decoration:none; display:inline-block; font-weight:600; }
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="logo"><i class="fa-solid fa-drone"></i> SkySense</div>
        <button class="refresh-btn" onclick="location.reload()">Refresh</button>
    </div>
    <div class="alert-banner"><i class="fa-solid fa-circle-info"></i> <span id="alert-msg">System Ready</span></div>
    <div class="nav-tabs">
        <button class="tab-btn active" onclick="sw('overview')">Overview</button>
        <button class="tab-btn" onclick="sw('charts')">GPS Charts</button>
        <button class="tab-btn" onclick="sw('history')">History</button>
        <button class="tab-btn" onclick="sw('esp32')">ESP32</button>
        <button class="tab-btn" onclick="sw('upload')">Upload</button>
        <button class="tab-btn" onclick="sw('export')">Export</button>
    </div>

    <div id="overview" class="section active">
        <div class="grid">
            <div class="card">
                <div class="card-head"><span>Air Quality</span> <span style="color:var(--s);font-size:0.8rem">● LIVE</span></div>
                <div class="aqi-box">
                    <div class="aqi-num" id="aqi-val">--</div>
                    <div style="color:var(--muted); margin-top:5px;">US AQI Standard</div>
                    <div style="margin-top:15px; font-size:0.9rem"><i class="fa-solid fa-location-dot"></i> <span id="loc-name">Unknown</span></div>
                </div>
                <div style="margin-top:20px;" id="metrics"></div>
            </div>
            <div class="card">
                <div class="card-head">Health Summary</div>
                <div class="stat-grid">
                    <div class="stat-box"><div style="font-size:1.5rem; font-weight:800; color:var(--p);" id="aqi-score">--</div><div style="font-size:0.8rem; color:var(--muted)">AQI Level</div></div>
                    <div class="stat-box"><div style="font-size:1.5rem; font-weight:800; color:var(--o);" id="risk-count">--</div><div style="font-size:0.8rem; color:var(--muted)">Risks</div></div>
                </div>
                <div class="card-head" style="font-size:1rem; margin-bottom:10px;">Detected Risks</div>
                <div id="risks"></div>
            </div>
        </div>
    </div>

    <div id="charts" class="section">
        <div class="card">
            <div class="card-head">Pollution vs Location</div>
            <div style="height:400px"><canvas id="chart"></canvas></div>
        </div>
    </div>

    <div id="history" class="section">
        <div class="card">
            <div class="card-head">History</div>
            <div id="hist-list" style="text-align:center; color:var(--muted)">No Data</div>
        </div>
    </div>

    <div id="esp32" class="section">
        <div class="card">
            <div class="card-head">Live Logs</div>
            <div id="logs" style="font-family:monospace; color:var(--s); height:200px; overflow-y:auto;"></div>
        </div>
    </div>

    <div id="upload" class="section">
        <div class="card">
            <div class="card-head">Upload File</div>
            <p style="color:var(--muted); margin-bottom:5px;">Date</p>
            <input type="date" id="u-date" class="date-input">
            <label class="upload-area">
                <i class="fa-solid fa-cloud-arrow-up" style="font-size:2rem; color:var(--muted); margin-bottom:10px;"></i>
                <div style="font-weight:600">Click to Upload CSV/Excel</div>
                <input type="file" id="u-file" style="display:none">
            </label>
        </div>
    </div>

    <div id="export" class="section">
        <div class="card">
            <div class="card-head">Export</div>
            <a href="/export" class="btn-main">Download Report</a>
        </div>
    </div>
</div>

<script>
    Chart.defaults.color='#94a3b8'; Chart.defaults.borderColor='#334155';
    function sw(id){
        document.querySelectorAll('.section').forEach(e=>e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.querySelectorAll('.tab-btn').forEach(e=>e.classList.remove('active'));
        document.querySelector(`button[onclick="sw('${id}')"]`).classList.add('active');
    }
    
    // Set default date to today to prevent upload errors
    document.getElementById('u-date').valueAsDate = new Date();

    setInterval(()=>{ fetch('/api/data').then(r=>r.json()).then(d=>upd(d)) }, 3000);

    document.getElementById('u-file').addEventListener('change', async (e)=>{
        const f = e.target.files[0];
        const d = document.getElementById('u-date').value;
        if(!f) return;
        const fd = new FormData(); fd.append('file', f); fd.append('date', d);
        try {
            const res = await fetch('/upload', {method:'POST', body:fd});
            const js = await res.json();
            if(js.error) alert(js.error);
            else { alert("Uploaded!"); sw('overview'); upd(js.data); }
        } catch(err){ alert("Upload Failed"); }
    });

    let mc;
    function upd(d){
        document.getElementById('aqi-val').innerText = d.aqi;
        document.getElementById('aqi-score').innerText = d.aqi;
        document.getElementById('risk-count').innerText = d.health_risks.length;
        document.getElementById('loc-name').innerText = d.location_name;
        document.getElementById('alert-msg').innerText = d.aqi>100 ? "Warning" : "Good";

        const m = document.getElementById('metrics'); m.innerHTML='';
        [{k:'pm25',l:'PM2.5',max:100}, {k:'pm10',l:'PM10',max:150}, {k:'temp',l:'Temp',max:50}, {k:'hum',l:'Hum',max:100}].forEach(i=>{
            const v = d[i.k]||0, p = Math.min((v/i.max)*100, 100);
            m.innerHTML += `<div class="bar-row"><div class="bar-head"><span>${i.l}</span><span>${v}</span></div><div class="bar-track"><div class="bar-fill" style="width:${p}%"></div></div></div>`;
        });

        const r = document.getElementById('risks'); r.innerHTML = d.health_risks.length ? '' : 'None';
        d.health_risks.forEach(x=> r.innerHTML+=`<div class="risk-item"><span>${x.name}</span><span style="color:${x.level=='High'?'var(--d)':'var(--o)'}">${x.level}</span></div>`);

        const h = document.getElementById('hist-list');
        if(d.history && d.history.length) {
            h.innerHTML=''; 
            d.history.forEach(x=> h.innerHTML+=`<div class="history-row"><span>${x.date} | ${x.filename}</span><strong style="color:var(--p)">AQI ${x.aqi}</strong></div>`);
        }

        if(d.chart_data.aqi.length){
            const ctx = document.getElementById('chart').getContext('2d');
            const labs = d.chart_data.gps.map(g=>`${Number(g.lat).toFixed(2)},${Number(g.lon).toFixed(2)}`);
            if(mc) mc.destroy();
            mc = new Chart(ctx, {
                type: 'bar',
                data: {labels:labs, datasets:[{label:'AQI', data:d.chart_data.aqi, backgroundColor:'#3b82f6', borderRadius:4}]},
                options: {responsive:true, maintainAspectRatio:false, scales:{x:{ticks:{maxRotation:45, minRotation:45}}}} 
            });
        }
        document.getElementById('logs').innerHTML = d.esp32_log.join('<br>');
    }
</script>
</body>
</html>
"""

@app.route('/')
def home(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def api_data():
    current_data['history'] = history_log
    return jsonify(current_data)

@app.route('/upload', methods=['POST'])
def upload():
    global current_data
    if 'file' not in request.files: return jsonify({"error":"No file"}), 400
    f = request.files['file']
    dt = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    try:
        if f.filename.lower().endswith('.csv'): df = pd.read_csv(f)
        else: df = pd.read_excel(f)
        
        df = normalize_columns(df)
        cols = ['pm1','pm25','pm10','temp','hum','lat','lon']
        for c in cols: 
            if c not in df.columns: df[c] = 0
            
        val = {k: round(df[k].mean(), 1) for k in cols}
        aqi = int((val['pm25']*2) + (val['pm10']*0.5))
        
        valid = df[df['lat']!=0]
        loc = get_city_name(valid.iloc[0]['lat'], valid.iloc[0]['lon']) if not valid.empty else "No GPS"
        
        gps, aqis = [], []
        for i, r in df.head(50).iterrows():
            aqis.append(int((r['pm25']*2)+(r['pm10']*0.5)))
            gps.append({"lat":r['lat'], "lon":r['lon']})
            
        history_log.insert(0, {"date":dt, "filename":f.filename, "aqi":aqi})
        current_data.update({"aqi":aqi, **val, "location_name":loc, "health_risks":calc_health(val), "chart_data":{"aqi":aqis,"gps":gps}, "last_updated":datetime.now().strftime("%H:%M")})
        
        return jsonify({"msg":"OK", "data":current_data})
    except Exception as e: return jsonify({"error":str(e)}), 500

@app.route('/api/upload_sensor', methods=['POST'])
def sensor():
    try:
        d = request.json
        current_data.update(d)
        aqi = int((d.get('pm25',0)*2) + (d.get('pm10',0)*0.5))
        current_data['aqi'] = aqi
        current_data['health_risks'] = calc_health(current_data)
        current_data['location_name'] = get_city_name(d.get('lat',0), d.get('lon',0))
        current_data['last_updated'] = datetime.now().strftime("%H:%M")
        
        current_data['chart_data']['aqi'].append(aqi)
        current_data['chart_data']['gps'].append({"lat":d.get('lat',0),"lon":d.get('lon',0)})
        if len(current_data['chart_data']['aqi'])>50: 
            current_data['chart_data']['aqi'].pop(0)
            current_data['chart_data']['gps'].pop(0)
            
        current_data['esp32_log'].insert(0, f"> AQI:{aqi} | T:{d.get('temp')}")
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"error":str(e)}), 400

@app.route('/export')
def export():
    out = io.StringIO()
    out.write(f"Date,AQI,Location\n{datetime.now()},{current_data['aqi']},{current_data['location_name']}")
    mem = io.BytesIO()
    mem.write(out.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name="report.csv", mimetype="text/csv")

if __name__ == '__main__':
    app.run(debug=True)
