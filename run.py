import os
import sys

# Add the current directory to sys.path so we can import from 'app'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    # Use the import string format to support the app directory structure
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
