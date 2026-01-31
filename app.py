from flask import Flask, render_template_string, jsonify, request, send_file
import pandas as pd
import io
import datetime

# Safe Import for Geopy
try:
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="skysense_final_v100")
except ImportError:
    geolocator = None

app = Flask(__name__)

# --- GLOBAL DATA STORE ---
history_log = [] 
current_data = {
    "aqi": 0, "pm1": 0, "pm25": 0, "pm10": 0, "temp": 0, "hum": 0,
    "status": "Waiting...", "location_name": "Waiting for Data...",
    "health_risks": [], "chart_data": {"aqi":[], "gps":[]},
    "esp32_log": ["> System Initialized...", "> Ready for connection..."],
    "last_updated": "Never"
}

# --- ROBUST FILE READER (Fixes the upload error) ---
def read_file_safely(file):
    # Your file is named .xlsx but might be CSV. This handles both.
    try:
        file.seek(0)
        return pd.read_csv(file)
    except:
        file.seek(0)
        return pd.read_excel(file)

def normalize_columns(df):
    col_map = {}
    for col in df.columns:
        c = str(col).lower().strip()
        if 'pm1.0' in c or ('pm1' in c and 'pm10' not in c): col_map[col] = 'pm1'
        elif 'pm2.5' in c or 'pm25' in c: col_map[col] = 'pm25'
        elif 'pm10' in c: col_map[col] = 'pm10'
        elif 'temp' in c: col_map[col] = 'temp'
        elif 'hum' in c: col_map[col] = 'hum'
        elif 'press' in c: col_map[col] = 'press'
        elif 'gas' in c: col_map[col] = 'gas'
        elif 'alt' in c: col_map[col] = 'alt'
        elif 'lat' in c or 'lal' in c: col_map[col] = 'lat' # Fixes 'lalitude'
        elif 'lon' in c or 'lng' in c: col_map[col] = 'lon'
    return df.rename(columns=col_map)

def get_city_name(lat, lon):
    if not geolocator or lat == 0: return "Unknown Area"
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, language='en')
        if loc:
            add = loc.raw.get('address', {})
            return add.get('suburb') or add.get('city') or add.get('town') or "Unknown Area"
    except: pass
    return "Unknown Area"

def calc_health(val):
    risks = []
    a_score = (val['pm25']*1.2) + (val['pm10']*0.5)
    risks.append({"name": "Asthma & Allergies", "prob": min(98, int(a_score)), "level": "High" if a_score>50 else "Moderate"})
    r_score = (val['pm10']*0.8) + (val['hum']<30)*20
    risks.append({"name": "Respiratory Diseases", "prob": min(95, int(r_score)), "level": "High" if r_score>60 else "Moderate"})
    c_score = (val['pm25']*0.9)
    risks.append({"name": "Cardiovascular Diseases", "prob": min(90, int(c_score)), "level": "High" if c_score>55 else "Moderate"})
    if val['temp']>30: risks.append({"name": "Heat Stress", "prob": min(100, int((val['temp']-30)*10)), "level": "High"})
    risks.sort(key=lambda x: x['prob'], reverse=True)
    return risks

# --- ORIGINAL UNTOUCHED LAYOUT ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense | Atoms Dark</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { 
            --bg: #0f172a; 
            --card-bg: #1e293b; 
            --text-main: #f1f5f9; 
            --text-muted: #94a3b8; 
            --primary: #3b82f6; 
            --orange: #f59e0b; 
            --danger: #ef4444; 
            --success: #22c55e;
            --border: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; }
        .container { max-width: 1200px; margin: 0 auto; }

        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .logo { font-size: 1.8rem; font-weight: 800; color: var(--text-main); letter-spacing: -1px; display:flex; align-items:center; gap:10px; }
        .logo i { color: var(--primary); }
        .refresh-btn { background: var(--primary); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: 0.2s; }
        .refresh-btn:hover { background: #2563eb; }

        .alert-banner { background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3);
