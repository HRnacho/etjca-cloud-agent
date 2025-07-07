# health_check.py
# Copiare il contenuto dall'artifact corrispondente
#!/usr/bin/env python3
import requests
import psycopg2
import os
import json
from datetime import datetime

def check_database():
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        conn.close()
        return True, "Database OK"
    except Exception as e:
        return False, f"Database Error: {e}"

def check_web_app():
    try:
        url = os.getenv('RAILWAY_STATIC_URL', 'http://localhost:5000')
        response = requests.get(f"{url}/api/stats", timeout=10)
        return response.status_code == 200, f"Web App: {response.status_code}"
    except Exception as e:
        return False, f"Web App Error: {e}"

def main():
    checks = {
        'database': check_database(),
        'web_app': check_web_app(),
        'timestamp': datetime.now().isoformat()
    }
    
    result = {
        'status': 'healthy' if all(check[0] for check in checks.values() if isinstance(check, tuple)) else 'unhealthy',
        'checks': {k: {'status': v[0], 'message': v[1]} for k, v in checks.items() if isinstance(v, tuple)},
        'timestamp': checks['timestamp']
    }
    
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
