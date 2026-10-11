"""GitHub runner entrypoint. Secrets go to private files, never shell interpolation."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

def checked(value,pattern,label):
    if not re.fullmatch(pattern,value):raise SystemExit('Missing or invalid '+label)
    return value

def main():
    host=checked(os.getenv('DEPLOY_HOST',''),r'[a-zA-Z0-9][a-zA-Z0-9.-]*','DEPLOY_HOST')
    user=checked(os.getenv('DEPLOY_USER',''),r'[a-z_][a-zA-Z0-9_-]*','DEPLOY_USER')
    port=checked(os.getenv('DEPLOY_PORT') or '22',r'[0-9]{1,5}','DEPLOY_PORT')
    if not 1<=int(port)<=65535:raise SystemExit('Invalid DEPLOY_PORT')
    sha=checked(os.getenv('GITHUB_SHA',''),r'[a-f0-9]{40}','GITHUB_SHA')
    images=[checked(os.getenv(name,''),r'ghcr\.io/[a-z0-9._/-]+:'+sha,name) for name in ('BACKEND_IMAGE','WEB_IMAGE')]
    key=os.getenv('DEPLOY_SSH_KEY','');hosts=os.getenv('DEPLOY_KNOWN_HOSTS','')
    if not key or not hosts:raise SystemExit('Configure SSH key and verified known hosts in production secrets')
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as folder:
        temp=Path(folder);keyfile=temp/'key';known=temp/'known_hosts';archive=temp/'source.tar.gz'
        for file,content in ((keyfile,key),(known,hosts)):
            file.write_text(content+'\n');file.chmod(0o600)
        subprocess.run(['git','archive','--format=tar.gz','--output='+str(archive),sha],cwd=root,check=True)
        options=['-i',str(keyfile),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),'-o','ConnectTimeout=15']
        remote=f'{user}@{host}';release='/opt/smart-finance/releases/'+sha
        def ssh(command):subprocess.run(['ssh',*options,'-p',port,remote,command],check=True)
        ssh('mkdir -p '+shlex.quote(release))
        subprocess.run(['scp',*options,'-P',port,str(archive),remote+':'+release+'/source.tar.gz'],check=True)
        command=' && '.join(['cd '+shlex.quote(release),'tar -xzf source.tar.gz','rm source.tar.gz','bash scripts/deploy.sh '+shlex.join([sha,*images])])
        ssh(command)
    print('Deployment completed; server-side environment was not copied or printed.')

if __name__=='__main__':main()
