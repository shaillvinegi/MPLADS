# MPLADS Monitoring & Transparency Platform

> **Integrated Project Life-Cycle & Citizen Transparency Portal**

An end-to-end digital governance platform built for Member of Parliament Local Area Development Scheme (MPLADS) project tracking, administrative scrutiny, physical execution monitoring, and open public financial audit.

---

## 🌟 Key Features

1. **Public Works Explorer**: Transparent lookup across 41,000+ sanctioned works and 49,000+ vendor payment events. Supports multi-level filtering by State, District, Category, Status, and Work ID.
2. **Member of Parliament (MP) Portal**: Enables MPs to submit development work recommendations, track sanction progress, and view constituency expenditure metrics.
3. **District Authority Portal**: Administrative scrutiny workspace for District Magistrates / Collectors to review MP proposals, issue formal sanction orders, and assign Implementing Agencies. Supports state-to-district cascading dropdown filters.
4. **Implementing Agency Portal**: Field execution division workspace for updating physical progress percentage, recording structural milestones, and submitting payment vouchers.
5. **Data Analytics & Charts**: Real-time calculated state distribution charts, execution status breakdowns, and financial summary statistics.
6. **100% Data-Driven**: Zero hardcoded records or synthetic mock data. All statistics, tables, and metrics are calculated dynamically from backend SQLite database queries.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.10+) & SQLite3
- **Frontend**: HTML5, TailwindCSS (CDN), JavaScript (ES6+), Chart.js, Lucide Icons
- **Data Pipeline**: Automated ETL script (`backend/etl_historical.py`) indexing real project & payment event CSV datasets.

---

## 📂 Project Structure

```
.
├── backend/
│   ├── main.py              # FastAPI REST endpoints & core business logic
│   ├── database.py          # Database connections & initializers
│   └── etl_historical.py    # ETL script for indexing historical CSV datasets
├── data/
│   ├── all_states_projects.csv          # Historical projects dataset
│   ├── all_states_payment_events.csv    # Vendor payment events dataset
│   ├── mplads_historical.db             # Indexed SQLite database for historical data
│   └── mplads_live.db                   # Live application database for new works & progress
├── static/
│   ├── index.html           # Main single-page application interface
│   ├── css/
│   │   └── style.css        # Government UI branding styles
│   └── js/
│       └── app.js           # Dynamic frontend application script
├── run.py                   # Application entry point script
├── .gitignore               # Git ignore rules
└── README.md                # Project documentation
```

---

## 🚀 Quick Start & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/shaillvinegi/MPLADS.git
cd MPLADS
```

### 2. Install Dependencies
```bash
pip install fastapi uvicorn
```

### 3. Initialize & Run Application
```bash
python run.py
```

Open your browser and navigate to `http://localhost:8000`.

---

## 📊 Core Workflow

```
MP Recommends Work ──► District Authority Scrutiny & Sanction ──► Implementing Agency Executes & Updates ──► Public Transparency Audit
```
