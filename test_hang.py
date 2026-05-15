import sys
print('start')
from app import app, init_db
print('app imported')
init_db()
print('db init done')
from fastapi.testclient import TestClient
print('TestClient loading')
client = TestClient(app)
print('TestClient instantiated')
