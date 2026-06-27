import sys
import os

# Make sure the root project path is on the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["PYTHONPATH"] = "."
os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"

from app.main import app
