# AntiDoze — Modern Automotive Driver Vigilance System

roadawake (file://SAM/Users/samue/.gemini/antigravity/scratch/roadawake)

**AntiDoze** is an AI-powered driver fatigue monitoring system engineered to safeguard truck drivers from micro-sleeps, inattention, and directional head slumps. It uses MediaPipe Face Mesh and OpenCV within a **modern 2026 digital cockpit HUD**, monitoring:

1. **Pre-Drive Trip Planning & Alert**:
   - The driver inputs intended driving duration before tracking begins.
   - **> 6.0 Hour Safety Alert**: If the planned duration exceeds 6 hours, the system alerts the driver that camera standby is available during Hours 0-6, after which continuous safety monitoring becomes mandatory.
2. **Camera Standby & Hour 6 Mandatory Lock**:
   - **Hours 0 - 6**: Driver can toggle the camera on/off (**`[T]`**) to enter Standby Mode (which displays a dedicated standby cockpit with live drive clock, clean driving streak, and strike healing active).
   - **Non-Invasive Standby Cockpit**: Clearly states `"Standby available for next: [time]"` and `"Driver monitoring is temporarily paused"` without invasive surveillance phrasing.
   - **Hour 6+**: Camera **must remain on**. Attempting to disable the camera after 6 hours is blocked with a warning chime and HUD alert. If in standby when crossing Hour 6, it is automatically re-enabled.
3. **Responsive Fullscreen Scaling & Razor-Sharp Typography**:
   - **Native Fullscreen Scaling**: The cockpit HUD dynamically and proportionally scales across 720p, 1080p, 1440p, and 4K displays with zero blurriness or layout distortion.
   - **Hotkey `[F]` & `--fullscreen` CLI Flag**: Toggle fullscreen anytime during driving or launch directly into native fullscreen mode.
   - **Clean ASCII Typography**: Zero question mark (`?` / `??`) font artifacts across all HUD elements, telemetry bars, status capsules, and standby screens.
4. **Dual Fatigue Timers: Continuous 2s Closure vs. Flutter Stack**:
   - **Original 2-Second Continuous Timer**: Measures unbroken eye closure. Reaching $\ge 2.0$s awards strictly **1 strike** for the entire closure episode. Continuous eye closure is **NOT** added to the flutter stack timer, eliminating double strikes.
   - **Flutter / Blink Stack Timer**: Only continuous blinking or eye fluttering ($< 2.0$s closures) accumulates into the stack. A full 2.0s stack smoothly decays at **0.20 s/s** over 10.0 seconds of open, attentive driving.
5. **Gamified Vigilance Reward System (Positive Motivation & Milestones)**:
   - Tracks continuous clean driving time without violations (**`STREAK: mm:ss`**) and session **Personal Best** (**`BEST: mm:ss`**).
   - **Gamified Vigilance Tiers**:
     * **`VIGILANT DRIVER (LVL 1)`** (< 3 min clean driving)
     * **`PRO PILOT (LVL 2)`** (3 – 10 min clean driving)
     * **`HIGHWAY MASTER (LVL 3)`** (10 – 30 min clean driving)
     * **`IRON TRUCKER (LVL 4)`** (30+ min clean driving — Master of the Road!)
   - On any strike or head nod slump, the current streak resets to 0 while preserving the driver's session Personal Best.
6. **3-Strike Safety System (Disciplinary Risk Management)**:
   - **Tier 1: TOP DRIVER (0/3 Strikes)** — Green optimal alert condition.
   - **Tier 2: CAUTION (1/3 Strikes)** — Amber first warning stage.
   - **Tier 3: WARNING (2/3 Strikes)** — Orange high-risk stage.
   - **Tier 4: CRITICAL (3/3 Strikes)** — Crimson emergency stage; **sounds the melodic chime alarm** until the driver pulls over.
7. **Strike Removal (30-Minute Clean Drive Rule)**:
   - Driving for **30 continuous minutes with no violations removes 1 strike** from the driver's active record and awards **IRON TRUCKER (LVL 4)**!
8. **Rest Stop Reset (15-Minute Rest Rule)**:
   - Stopping at a rest stop for **> 15 minutes** (via **`[R]`** Rest Stop Mode or continuous cab absence) **resets ALL strikes back to 0**, returning the driver to **Tier 1: Top Driver**.
9. **Enhanced Head Nod Detection & Multi-Channel Channel Separation**:
   - **Sustained Posture Monitoring**: Detects downward head slumps sustained for **3.0 seconds** at pitch ratio threshold **$< 0.78$** (catches ~20° downward slump while accommodating natural highway posture shifts).
   - **Dedicated HUD Posture Gauge**: Added Section B3 telemetry gauge (`HEAD NOD: 0.0s / 3.0s` / `HEAD PITCH: 1.05`), separate from EAR, Continuous Eye Closure, and Flutter Stack.
   - **Distinct Acoustic Alerts**: Upward melodic chime ($587\text{ Hz} \rightarrow 880\text{ Hz}$) for eye closure vs. urgent descending dual-pulse tone ($784\text{ Hz} \rightarrow 523\text{ Hz}$) for head nod slumps.
   - **Distinct Visual Themes**: Violet/Magenta border glow and capsule (`[HEAD NOD] POSTURE COLLAPSE!`) vs. Red/Cyan for eye closures.
   - **Distinct Upright Dismissal**: Head nod pop-up requires holding the head upright for **1.5s** (`"Raise head upright 1.5s to clear"` with violet progress meter) rather than checking eye closure.
   - **Legitimate Mirror Checks**: Legitimate mirror checks require open eyes and upright posture, preventing false alarms during highway navigation.
10. **Soothing Melodic Chime & Non-Blocking Audio Architecture**: Warm, non-annoying cabin chime run on dedicated daemon threads to guarantee zero video lag or dropped frames.

---

## 🛠️ Environment Status

- **Python Version**: Python 3.11.9 (Installed & added to User `PATH`)
- **Core Packages**: `opencv-python`, `mediapipe==0.10.14`, `numpy`
- **Project Directory**: `C:\Users\samue\.gemini\antigravity\scratch\roadawake`

---

## 🚀 Running the App

### 1. Default Webcam (Live Testing)
```bash
python antidoze.py
```
*(Or launch directly in fullscreen mode: `python antidoze.py --fullscreen`)*
*(Or pass pre-configured trip hours: `python antidoze.py --planned-hours 8.0`)*

### 2. Built-in Simulation & Demo Mode (No Webcam Needed)
Generates a 28-second test scenario verifying trip planning, standby toggle, Hour 6 mandatory lock, blocked toggle attempt, gradual stack decay, gamified reward streaks, and 3-strike ranks:
```bash
python antidoze.py --demo
```
This produces `demo_output.mp4` for video playback.

### 3. Run Algorithmic Diagnostics & Self-Tests
```bash
python antidoze.py --test
```

---

## ⌨️ In-App Hotkeys & Controls

| Key | Action | Description |
|:---:|:---|:---|
| **`F`** | **Toggle Fullscreen Mode** | Toggles native fullscreen display with dynamic UI scaling across any monitor |
| **`T`** | **Toggle Camera / Standby** | Toggles camera on/off (Hours 0-6). Locked permanently ON after Hour 6 |
| **`R`** | **Rest Stop Mode** | Parks cab tracking and accumulates rest stop time (15 mins resets all strikes) |
| **`C`** | **Auto-Calibrate** | Calibrates baseline EAR and baseline head posture over 3 seconds |
| **`M`** | **Toggle Mesh** | Shows or hides delicate contour lines and iris center points |
| **`Q`** / **`ESC`** | **Quit** | Safely cleans up resources and closes windows |

---

## 🏆 Dual System: 3-Strike Safety & Gamified Reward Matrix

| System | Indicator | Milestone / Level | Trigger Condition | Driver Impact / Reward |
|:---|:---|:---|:---|:---|
| **Reward** | `⚡ STREAK: 00:00` | **`VIGILANT DRIVER (LVL 1)`** | Clean Drive < 3 min | Baseline alert driving status |
| **Reward** | `⚡ STREAK: 03:00` | **`PRO PILOT (LVL 2)`** | Clean Drive $\ge$ 3 min | Level 2 Sky-Cyan Badge awarded |
| **Reward** | `⚡ STREAK: 10:00` | **`HIGHWAY MASTER (LVL 3)`** | Clean Drive $\ge$ 10 min | Level 3 Gold Badge awarded |
| **Reward** | `⚡ STREAK: 30:00` | **`IRON TRUCKER (LVL 4)`** | Clean Drive $\ge$ 30 min | Top Platinum Tier + **Heals 1 Strike!** |
| **Safety** | `STRIKES: 0/3` | **`TIER 1: TOP DRIVER`** | 0 active strikes | Safe operating condition |
| **Safety** | `STRIKES: 1/3` | **`TIER 2: CAUTION`** | 1st violation | Silent visual pop-up warning |
| **Safety** | `STRIKES: 2/3` | **`TIER 3: WARNING`** | 2nd violation | Silent visual pop-up warning |
| **Safety** | `STRIKES: 3/3` | **`TIER 4: CRITICAL`** | 3rd violation | **Melodic chime alarm active** (Rest required) |
| **Recovery** | `REST STOP` | **`FULL RESET (0/3)`** | Rest stop $\ge$ 15 min | All strikes cleared back to 0/3 |

---

## 🏢 Fleet Management Dynamic Database & Alert Dispatch

AntiDoze includes an enterprise SQLite dynamic database (`antidoze_fleet.db`) with Write-Ahead Logging (WAL) mode for real-time fleet manager monitoring:

### 🌟 Key Features:
1. **Automated 10-Second Telemetry Sync**:
   - The vehicle cab client logs a heartbeat to the database **every 10 seconds** (`DEFAULT_DB_SYNC_INTERVAL = 10.0`).
   - Every entry records **Driver ID**, **Date and Time Stamp**, **Strike Status** (Top Driver, Caution, Warning, Critical), EAR, Head Pitch, Clean Streak, Trip Clock, and Camera Mode.
2. **High-Visibility Critical Alert Highlighting**:
   - When strike status reaches **Tier 4: CRITICAL (3/3 Strikes)**, `is_critical` is flagged as `1`.
   - **In the Fleet Web Portal**: Critical rows are prominently highlighted with an animated, pulsing **Crimson Red glowing background**, high-contrast badges (`[!!! CRITICAL ALERT !!!]`), and a top emergency intervention banner.
   - **In the Fleet Terminal Monitor**: Critical rows render in bold white text on a bright red background (`\033[41;1;37m`).
   - Dispatches emergency incident records to the `fleet_alerts` table requiring fleet supervisor acknowledgment.
3. **Driver ID Tagging & Pre-Drive Configuration**:
   - Each entry is tied to a specific driver ID (`DRV-101`, `DRV-204`, etc.), configurable via `--driver-id` CLI flag or the pre-drive trip planner GUI.

### 🖥️ Running Fleet Manager Tools:

```bash
# Option A: Run Live AntiDoze Webcam Program with Auto-Launched HTML Dashboard (All-in-One)
python antidoze.py --open-dashboard

# Option B: Run Live AntiDoze with a custom Driver ID & launch Dashboard
python antidoze.py --driver-id DRV-ALEX --open-dashboard

# Option C: Standalone Fleet Manager Server (Open http://localhost:8080 in browser)
python fleet_manager_server.py

# Option D: Dynamic Fleet Terminal Monitor (Live console table updating every 10 seconds)
python fleet_terminal_monitor.py

# Option E: Multi-Driver Fleet Simulator (Feeds synthetic 10-second cycles across 4 trucks)
python fleet_simulator.py
```

### 🔄 How the HTML Site Connects to the Live Non-Simulation Program:
1. **Automatic Background Server**: When you run `python antidoze.py`, it automatically spins up the Fleet Manager Web Server on background daemon port 8080.
2. **Sub-Second Live Cab Stream**: As you move, blink, or nod in front of the actual webcam, the live AI model streams your Driver ID, Strike Rank, Eye Openness (EAR bar), Head Slump/Pitch, Glance Direction, and Clean Streak directly to the top Live Cab Card on the HTML site every second (`/api/live`).
3. **Automated 10-Second Database Heartbeats**: Every 10 seconds, the active program writes a persistent row to SQLite (`antidoze_fleet.db`), and immediately creates an emergency alert when 3/3 strikes (Critical) is reached.
4. **Direct Browser & File Protocol Support**: You can view the dashboard by opening `http://localhost:8080/` or by directly double-clicking `fleet_manager_dashboard.html` (`file:///...`). Both modes connect to the live cab client.
5. **Instantaneous Strike Synchronization**: The moment the driver actually triggers a strike in front of the camera (2.0s closure, flutter stack, or head nod slump) or heals a strike, the database, KPI counters, and HTML dashboard update *instantly* with visual flashing and audible chimes without waiting for the 10-second timer.
6. **Active Connection & Inactive Tracking**: The database logs `CAB CONNECTED (ACTIVE)` when AntiDoze starts and `CAB DISCONNECTED (INACTIVE)` when cleanly closed. The Fleet Manager dashboard displays real-time connection status badges (`● CONNECTED` vs `○ INACTIVE`) across the live cab stream, fleet KPI cards, and individual driver vehicle cards. Stale heartbeats (> 25s) are automatically flagged as inactive.
7. **Offline & Online Driver Toggles**: In the Fleet Drivers Overview, supervisors can filter by `All Drivers`, `● Online Only`, or `○ Offline Only` with live counter badges. Each truck card also features an interactive `○ Set Offline` / `● Set Online` toggle button for manual duty status overrides.
8. **Drive Log Removal & Clearance**: The dashboard allows fleet managers to delete individual drive logs with a single click (`🗑️ Remove` in each table row) or bulk-remove telemetry records using the `🗑️ Clear Logs` button.
9. **Inactive Driver Warning Suppression & Instant Reconnection Refresh**:
   - **Warning Suppression for Inactive Trucks**: Inactive drivers (trucks parked, off-duty, or disconnected) do NOT display active warning badges (`🚨 CRITICAL`, `⚠️ WARNING`, `🟡 CAUTION`), nor red pulsating critical glows, nor emergency dispatch buttons (`📞 Call Cab`). Inactive cards display `○ STANDBY (OFFLINE)` in calm, muted slate gray. Fleet safety KPIs and urgent incident queues strictly count actively connected vehicles (`is_connected = 1`).
   - **Instant System Refresh on State Transitions**: When any driver goes inactive or reconnects online, the dashboard immediately triggers a full system refresh (`fetchFleetData()`), updating KPI counters, driver cards, and log tables without waiting for the 10-second countdown. Reconnecting drivers start with a clean vigilance profile (`TOP DRIVER (0/3)`).

---

## 🌐 Accessing the Dashboard from Another Computer (LAN / Wi-Fi)

You can view and manage the AntiDoze Fleet Command dashboard in real time from **any other computer, laptop, tablet, or smartphone** connected to the same Wi-Fi or local area network (LAN):

### 1. Start the Server on the Host Computer
```bash
python fleet_manager_server.py
# Or run the live AI program (which auto-starts the server on 0.0.0.0:8080):
python antidoze.py
```

### 2. Check the Network Access URL
When the server starts, it automatically detects your Wi-Fi/LAN IP address and prints:
```text
========================================================================
 ANTIDOZE FLEET COMMAND PORTAL & DYNAMIC DATABASE SERVER 
========================================================================
 * Local Portal URL (This PC) : http://localhost:8080/
 * Network Access (Other PCs) : http://<YOUR_IP>:8080/ (e.g. http://10.180.128.138:8080/)
========================================================================
```

### 3. Open on Another Computer / Device
1. Ensure both computers are connected to the same Wi-Fi / local network.
2. On the other computer, open any web browser (Chrome, Edge, Safari, Firefox).
3. Type the Network Access URL:
   ```
   http://10.180.128.138:8080/
   ```
4. The other computer receives the live telemetry stream, real-time strike notifications, interactive offline toggles, and dynamic 10-second database logs.

### 4. Windows Firewall Setup (One-Time Permitted Port)
If other computers cannot connect due to Windows Defender Firewall blocking port 8080:
- Right-click `allow_firewall.bat` in this directory and select **Run as administrator**.
- *Or* in an elevated Administrator PowerShell terminal, run:
  ```powershell
  netsh advfirewall firewall add rule name="AntiDoze Fleet Server" dir=in action=allow protocol=TCP localport=8080 profile=any
  ```

### 5. Interactive Remote Cab Switcher
In the dashboard header, click the **`🌐 Host`** pill at any time to point the dashboard at any remote truck or server IP address, or pass `?host=<IP>:8080` in the browser URL.

