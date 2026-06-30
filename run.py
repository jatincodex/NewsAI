import os
import uvicorn

# Auto-load .env file if present (for local development with Firebase credentials)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, env vars must be set manually

if __name__ == "__main__":
    # Configure eager pipeline env variables automatically
    os.environ["PYTHONPATH"] = "."
    os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"

    # Detect storage mode
    has_firebase = all([
        os.getenv("FIREBASE_PROJECT_ID"),
        os.getenv("FIREBASE_CLIENT_EMAIL"),
        os.getenv("FIREBASE_PRIVATE_KEY") or os.getenv("FIREBASE_CREDENTIALS_JSON")
    ])
    storage_mode = "🔥 Firebase Firestore (Permanent Cloud)" if has_firebase else "⚠️  SQLite Mock (Local Only — Data resets on restart)"

    print("\n=============================================")
    print("Starting NewsAI Platform on http://127.0.0.1:8081")
    print(f"Storage Mode : {storage_mode}")
    print("=============================================\n")

    # Run the application server with reload=False for instant startup
    uvicorn.run("app.main:app", host="127.0.0.1", port=8081, reload=False)
