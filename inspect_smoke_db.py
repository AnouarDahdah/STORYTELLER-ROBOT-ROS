import sqlite3

path = "/tmp/imaginarium_smoke.sqlite3"
db = sqlite3.connect(path)
print("TOYS", db.execute("select toy_id,main_class,sub_class,story_count,session_count from toys").fetchall())
print("INTERACTIONS", db.execute("select toy_id,event_type,timestamp from interactions").fetchall())
db.close()
