from datetime import datetime, timedelta
print(f"Now: {datetime.now()}")
print(f"UTC Now: {datetime.utcnow()}")
print(f"Dashboard logic (UTC+8): {datetime.utcnow() + timedelta(hours=8)}")
