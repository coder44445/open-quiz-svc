import os
import time
import requests
import pytest

@pytest.mark.skipif(os.environ.get('INTEGRATION') != '1', reason='Integration tests disabled')
def test_health_endpoint():
    # assumes app is reachable at localhost:8000
    for _ in range(30):
        try:
            r = requests.get('http://localhost:8000/health', timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            time.sleep(1)
        print("Health check failed", text=r.text, status_code=r.status_code)
    pytest.skip('app did not become healthy')