"""Portable demo import; safe to repeat, no extra packages required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import demo_data

if __name__ == '__main__':
    server.init_db()
    demo_data.seed_office_history(server)
