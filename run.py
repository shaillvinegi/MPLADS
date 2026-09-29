"""
Startup runner for the Nirakshan MPLADS Platform.
Usage: python run.py
Access the platform at: http://localhost:8000
"""
import sys
import os
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("=" * 65)
    print("   NIRAKSHAN MPLADS MONITORING & TRANSPARENCY PLATFORM (MVP)")
    print("   Ministry of Statistics & Programme Implementation (MoSPI)")
    print("=" * 65)
    print(" • Connected Historical Projects : 41,086 (all_states_projects.csv)")
    print(" • Connected Payment Events      : 49,990 (all_states_payment_events.csv)")
    print(" • Live Application DB           : data/mplads_live.db")
    print(" • Starting server at            : http://localhost:8000")
    print("=" * 65)

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False)
