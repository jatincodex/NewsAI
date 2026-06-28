import os
import uvicorn

if __name__ == "__main__":
    # Configure eager pipeline env variables automatically
    os.environ["PYTHONPATH"] = "."
    os.environ["NEWS_AI_CELERY_TASK_ALWAYS_EAGER"] = "True"
    
    print("\n=============================================")
    print("Starting NewsAI Platform on http://127.0.0.1:8081")
    print("=============================================\n")
    
    # Run the application server with reload=False for instant startup
    uvicorn.run("app.main:app", host="127.0.0.1", port=8081, reload=False)
