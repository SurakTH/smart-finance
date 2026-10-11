"""Optional demo only. Save generated credentials locally with mode 0600."""
import json
import os
from pathlib import Path
import secrets
import subprocess

root=Path(__file__).resolve().parents[1]
output=root/'artifacts'/'demo-access.json'
output.parent.mkdir(exist_ok=True)
if output.exists(): raise SystemExit('Demo credentials already exist: artifacts/demo-access.json')
values={'email':'demo@smart-finance.local','password':secrets.token_urlsafe(24)}
subprocess.run(['docker','compose','exec','-T','api','python','-m','app.demo'],cwd=root,input=json.dumps(values),text=True,check=True)
fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: json.dump(values,f)
print('Demo credentials saved to artifacts/demo-access.json (0600). Do not share this file.')
