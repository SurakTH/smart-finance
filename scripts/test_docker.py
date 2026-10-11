"""Run real PostgreSQL tests in an isolated database, including DB-level guards."""
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
create=subprocess.run(['docker','compose','exec','-T','postgres','createdb','-U','finance','finance_test'],cwd=root,capture_output=True,text=True)
if create.returncode and 'already exists' not in create.stderr: raise SystemExit('Cannot create test database')
code="import os,subprocess; os.environ['TEST_DATABASE_URL']=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/finance_test'; subprocess.run(['python','-m','pytest','-q'],check=True)"
subprocess.run(['docker','compose','run','--rm','--no-deps','-T','api','python','-c',code],cwd=root,check=True)
