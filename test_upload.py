import requests

url = "http://127.0.0.1:8000/api/chat"
files = [
    ("files", ("Kw_vs_Throughput_T1-31_FINAL.xlsx", open("C:/Users/Asus/Downloads/T1-31/T1-31/Kw vs Throughput T1-31 FINAL.xlsx", "rb"))),
    ("files", ("W-O_Centrifuge_Capillary_Pressure_Imbibition_T1-31.xls", open("C:/Users/Asus/Downloads/T1-31/T1-31/W-O Centrifuge Capillary Pressure, Imbibition Cycle, Final (T1-31).xls", "rb"))),
    ("files", ("Mercury_Injection_Well_T1-31.xls", open("C:/Users/Asus/Downloads/T1-31/T1-31/Mercury Injection Well T1-31.xls", "rb")))
]
data = {
    "user_email": "test@example.com",
    "message": "Generate Report for T1-31",
    "engineer_name": "Test Engineer"
}

print("Uploading files via chat...")
r = requests.post(url, data=data, files=files)
print(f"Chat status: {r.status_code}")
if r.status_code != 200:
    print(r.text)

print("Checking db...")
