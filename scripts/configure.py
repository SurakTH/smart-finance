"""Create local secrets without echoing them. Does not overwrite existing .env."""
import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
template = (root/'.env.example').read_text()
template = template.replace('POSTGRES_PASSWORD=\n','POSTGRES_PASSWORD='+secrets.token_hex(32)+'\n')
template = template.replace('ENCRYPTION_KEY=\n','ENCRYPTION_KEY='+base64.urlsafe_b64encode(os.urandom(32)).decode()+'\n')
fd=os.open(root/'.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f: f.write(template)
print('Created .env (permissions 0600). Configure APP_ORIGIN before deployment.')
