import re
import os

files = [
    "test_02_problem_detection.py",
    "test_03_root_cause.py",
    "test_04_strategy.py",
    "test_05_executor.py",
    "test_06_api_endpoints.py",
]

for filename in files:
    filepath = os.path.join("/home/l/rag-dashboard/tests/e2e", filename)
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Remove @pytest.mark.asyncio
    content = content.replace("@pytest.mark.asyncio\n", "")
    
    # Change async def to def
    content = re.sub(r'async def ', 'def ', content)
    
    # Change await http_client to http_client with .request()
    # Change await http_client.get() to http_client.get() with timeout
    content = re.sub(r'await http_client\.get\((.*?)\)', 
                    lambda m: f'http_client.get(f"http://localhost:8002" + {m.group(1)}, timeout=10)',
                    content)
    
    content = re.sub(r'await http_client\.post\((.*?), json=(.*?)\)',
                    lambda m: f'http_client.post(f"http://localhost:8002" + {m.group(1)}, json={m.group(2)}, timeout=10)',
                    content)
    
    # Remove asyncio.sleep calls and replace with time.sleep
    if 'asyncio.sleep' in content:
        if 'import asyncio' in content:
            content = content.replace('import asyncio\n', '')
        content = content.replace('await asyncio.sleep', 'import time; time.sleep')
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"Updated {filename}")

