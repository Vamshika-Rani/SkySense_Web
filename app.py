from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import os

# Initialize Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = 'skysense_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variable to store the latest sensor data
sensor_data = {
    "temp": 0,
    "hum": 0,
    "pm25": 0,
    "pm10": 0,
    "lat": 0.0,
    "lon": 0.0
}

# ==========================================
#  THE DASHBOARD HTML TEMPLATE
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SkySense Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121212; color: #e0e0e0; margin: 0; padding: 0; }
        .header { background-color: #1f1f1f; padding: 20px; text-align: center; border-bottom: 2px solid #333; }
        .header h1 { margin: 0; color: #4caf50; }
        
        /* Tabs */
        .tabs { display: flex; justify-content: center; background-color: #1f1f1f; padding: 10px 0; }
        .tab-btn { background: none; border: none; color: #aaa; padding: 10px 20px; cursor: pointer; font-size: 16px; transition: 0.3s; }
        .tab-btn:hover { color: #fff; }
        .tab-btn.active { color: #4caf50; border-bottom: 2px solid #4caf50; }

        /* Content */
        .container { padding: 20px; max-width: 1200px; margin: auto; }
        .tab-content { display: none; animation: fadeIn 0.5s; }
        .tab-content.active { display: block; }
        
        .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; }
        .card { background-color: #1e1e1e; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .card h3 { color: #4caf50; margin-top: 0; }
        .value { font-size: 2em; font-weight: bold; }
        .unit { font-size: 0.5em; color: #888; }
        
        /* Health Lists */
        ul { padding-left: 20px; }
        li { margin-bottom: 10px; color: #ccc; }
        
        /* Console for ESP32 Data */
        .console { background: #000; color: #0f0; font-family: monospace; padding: 15px; border-radius: 5px; height: 300px; overflow-y: auto; font-size: 0.9em; }

        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
</head>
<body>

    <div class="header">
        <h1>✈️ SkySense Monitor</h1>
        <p>Real-time Drone Telemetry & Air Quality</p>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="openTab('overview')">Overview</button>
        <button class="tab-btn" onclick="openTab('health')">Health Reports</button>
        <button class="tab-btn" onclick="openTab('raw-data')">ESP32 Data</button>
    </div>

    <div class="container">
        
        <div id="overview" class="tab-content active">
            <div class="card-grid">
                <div class="card">
                    <h3>PM 2.5</h3>
                    <div class="value"><span id="val-pm25">--</span> <span class="unit">µg/m³</span></div>
                </div>
                <div class="card">
                    <h3>PM 10</h3>
                    <div class="value"><span id="val-pm10">--</span> <span class="unit">µg/m³</span></div>
                </div>
                <div class="card">
                    <h3>Temperature</h3>
                    <div class="value"><span id="val-temp">--</span> <span class="unit">°C</span></div>
                </div>
                <div class="card">
                    <h3>Humidity</h3>
                    <div class="value"><span id="val-hum">--</span> <span class="unit">%</span></div>
                </div>
            </div>
            <br>
            <div class="card">
                <h3>Quick Health Summary</h3>
                <p id="quick-health-summary" style="font-size: 1.2em; color: #fff;">Waiting for sensor data...</p>
            </div>
        </div>

        <div id="health" class="tab-content">
            <div class="card-grid">
                <div class="card">
                    <h3>Health Impact Analysis</h3>
                    <ul id="health-report-list">
                        <li>Loading detailed health report...</li>
                    </ul>
                </div>
                <div class="card">
                    <h3>Recommended Precautions</h3>
                    <ul id="precaution-list">
                        <li>Loading safety measures...</li>
                    </ul>
                </div>
            </div>
        </div>

        <div id="raw-data" class="tab-content">
            <div class="card">
                <h3>Live Sensor Stream</h3>
                <div class="console" id="console-log">
                    <div>Waiting for ESP32 connection...</div>
                </div>
            </div>
        </div>

    </div>

    <script>
        const socket = io();

        // ===============================================
        //  DYNAMIC HEALTH LOGIC (5 LEVELS)
        // ===============================================
        const aqiRules = [
            {
                limit: 50, // GOOD
                summary: "Air quality is excellent. Conditions are ideal for outdoor activities.",
                color: "#00e400",
                reports: [
                    "Air quality is satisfactory and poses little or no risk.",
                    "Ideal conditions for outdoor exercise, running, or cycling.",
                    "No respiratory irritation or discomfort is expected for any group.",
                    "Visibility is clear, and particle pollution is at its lowest levels."
                ],
                precautions: [
                    "Ventilation: It is safe to open windows and ventilate your home.",
                    "Activities: Enjoy outdoor sports and activities without restriction.",
                    "No Equipment Needed: No masks or air purifiers are required today."
                ]
            },
            {
                limit: 100, // MODERATE
                summary: "Air quality is acceptable; however, there may be a concern for some people.",
                color: "#ffff00",
                reports: [
                    "Air quality is acceptable for the general public.",
                    "Unusually sensitive people may experience minor throat irritation.",
                    "Breathing discomfort is possible for people with severe asthma.",
                    "Long-term exposure at this level is generally safe, but monitor changes."
                ],
                precautions: [
                    "Sensitive Groups: People with asthma should reduce prolonged outdoor exertion.",
                    "Ventilation: Keep windows open, but close them if traffic is heavy nearby.",
                    "Monitoring: Watch for coughing or shortness of breath."
                ]
            },
            {
                limit: 150, // UNHEALTHY FOR SENSITIVE GROUPS
                summary: "Members of sensitive groups may experience health effects. General public is okay.",
                color: "#ff7e00",
                reports: [
                    "Children and older adults may feel slight chest tightness.",
                    "People with lung disease are at greater risk of respiratory issues.",
                    "General public is less likely to be affected but may feel fatigue.",
                    "Ozone or particle levels are high enough to trigger asthma attacks."
                ],
                precautions: [
                    "Risk Reduction: Reduce prolonged or heavy exertion outdoors.",
                    "Protection: Wear a mask if you have respiratory issues.",
                    "Indoors: Close windows during peak traffic hours."
                ]
            },
            {
                limit: 200, // UNHEALTHY
                summary: "Unhealthy! Everyone may begin to experience health effects.",
                color: "#ff0000",
                reports: [
                    "Increased aggravation of heart or lung disease.",
                    "Possible premature mortality in people with cardiopulmonary disease.",
                    "General public likely to experience coughing and throat irritation.",
                    "Reduced lung function and possible breathing difficulties for everyone."
                ],
                precautions: [
                    "Avoid Exertion: Everyone should avoid heavy outdoor exertion.",
                    "Mask Up: Wear an N95 mask if you must go outside.",
                    "Seal Home: Keep windows and doors closed; use an air purifier."
                ]
            },
            {
                limit: 9999, // HAZARDOUS
                summary: "HAZARDOUS! Emergency conditions. Serious risk for everyone.",
                color: "#7e0023",
                reports: [
                    "Significant increase in respiratory effects in the general population.",
                    "Serious risk of heart attacks and strokes for at-risk groups.",
                    "Eye irritation, wheezing, and difficulty breathing are common.",
                    "Daily activities will be impacted by poor visibility and toxic air."
                ],
                precautions: [
                    "Stay Indoors: Do not go outside unless absolutely necessary.",
                    "Purify Air: Run air purifiers on high speed constantly.",
                    "Medical Attention: Seek help immediately if you experience chest pain.",
                    "No Ventilation: Seal all window gaps with tape or towels."
                ]
            }
        ];

        function updateHealthContent(pm25, pm10) {
            // Use the higher value to decide the danger level
            let val = Math.max(pm25, pm10);
            
            // Find the matching rule
            let rule = aqiRules.find(r => val <= r.limit) || aqiRules[aqiRules.length - 1];

            // 1. Update Summary (Overview Tab)
            let summaryEl = document.getElementById("quick-health-summary");
            if (summaryEl) {
                summaryEl.innerText = rule.summary;
                summaryEl.style.color = rule.color === "#ffff00" ? "#ffff00" : rule.color; // Yellow handling
            }

            // 2. Update Health List
            let healthList = document.getElementById("health-report-list");
            if (healthList) {
                healthList.innerHTML = "";
                rule.reports.forEach(text => {
                    let li = document.createElement("li");
                    li.innerText = text;
                    healthList.appendChild(li);
                });
            }

            // 3. Update Precaution List
            let precautionList = document.getElementById("precaution-list");
            if (precautionList) {
                precautionList.innerHTML = "";
                rule.precautions.forEach(text => {
                    let li = document.createElement("li");
                    li.innerText = text;
                    precautionList.appendChild(li);
                });
            }
        }

        // ===============================================
        //  SOCKET CONNECTION & UPDATES
        // ===============================================
        socket.on('connect', () => {
            console.log("Connected to SkySense Server");
        });

        socket.on('sensor_update', (data) => {
            // 1. Update Numbers
            document.getElementById('val-pm25').innerText = data.pm25;
            document.getElementById('val-pm10').innerText = data.pm10;
            document.getElementById('val-temp').innerText = data.temp;
            document.getElementById('val-hum').innerText = data.hum;

            // 2. Update Console Log
            const logDiv = document.getElementById('console-log');
            const newEntry = document.createElement('div');
            newEntry.innerText = `[${new Date().toLocaleTimeString()}] PM2.5: ${data.pm25} | PM10: ${data.pm10} | Temp: ${data.temp}`;
            logDiv.prepend(newEntry);

            // 3. UPDATE HEALTH REPORTS DYNAMICALLY
            updateHealthContent(data.pm25, data.pm10);
        });

        // Tab Switching Logic
        function openTab(tabName) {
            var x = document.getElementsByClassName("tab-content");
            for (var i = 0; i < x.length; i++) { x[i].style.display = "none"; x[i].classList.remove("active"); }
            document.getElementById(tabName).style.display = "block";
            document.getElementById(tabName).classList.add("active");
            
            var btns = document.getElementsByClassName("tab-btn");
            for (var i = 0; i < btns.length; i++) { btns[i].classList.remove("active"); }
            event.currentTarget.classList.add("active");
        }
    </script>
</body>
</html>
"""

# ==========================================
#  FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/upload_sensor', methods=['POST'])
def upload_sensor():
    global sensor_data
    try:
        data = request.json
        # Update global data
        sensor_data = data
        
        print(f"Received Data: {data}")  # Print to Render logs
        
        # Send to all connected web clients
        socketio.emit('sensor_update', data)
        
        return jsonify({"status": "success", "message": "Data received"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# ==========================================
#  MAIN ENTRY POINT
# ==========================================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
