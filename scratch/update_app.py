
import os
path = r'c:\Users\Asus\Downloads\scal-ai-pipeline\app.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Add user_email to model response inserts
# Using more robust replacement
target1 = 'db("INSERT INTO m (sid, role, text, url, ts) VALUES (?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time()))'
replace1 = 'db("INSERT INTO m (sid, role, text, url, ts, user_email) VALUES (?, ?, ?, ?, ?, ?)", (sid, "model", clean_resp, url, time.time(), user_email))'

target2 = 'db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "model", resp, time.time()))'
replace2 = 'db("INSERT INTO m (sid, role, text, ts, user_email) VALUES (?, ?, ?, ?, ?)", (sid, "model", resp, time.time(), user_email))'

content = content.replace(target1, replace1)
content = content.replace(target2, replace2)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated app.py successfully")
