"""Trusted main deployment on the Ubuntu runner; registry auth is temporary."""
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


def main():
    sha = os.environ.get('GITHUB_SHA', '')
    repository = os.environ.get('GITHUB_REPOSITORY', '').lower()
    if not re.fullmatch(r'[a-f0-9]{40}', sha) or not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repository):
        raise SystemExit('Invalid commit or repository')
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise SystemExit('Only tested main releases may deploy')
    images = [f'ghcr.io/{repository}/{kind}:{sha}' for kind in ('backend', 'web')]
    path = os.environ.get('LOCAL_DEPLOY_PATH', '')
    if not path or not Path(path).is_absolute():
        raise SystemExit('Set LOCAL_DEPLOY_PATH to the existing server app directory')
    root = Path(path).resolve()
    if root == Path('/') or not (root / '.env').is_file() or not (root / 'compose.yaml').is_file():
        raise SystemExit('Existing app directory with .env and compose.yaml required')
    gateway = os.environ.get('LOCAL_DEPLOY_GATEWAY', 'caddy') or 'caddy'
    if gateway not in ('caddy', 'nginx'):
        raise SystemExit('LOCAL_DEPLOY_GATEWAY must be caddy or nginx')
    token, actor = os.environ.get('REGISTRY_TOKEN', ''), os.environ.get('GITHUB_ACTOR', '')
    if not token or not actor:
        raise SystemExit('Workflow registry authentication required')
    source = Path(__file__).resolve().parents[1]
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, check=True, capture_output=True, text=True).stdout.strip()
    if head != sha:
        raise SystemExit('Checkout differs from the tested commit')
    release = root / 'releases' / sha
    # The runner deploys repository source only, never its untracked files or .env.
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        temp.chmod(0o700)
        archive = temp / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(archive), sha], cwd=source, check=True)
        release.mkdir(parents=True, exist_ok=True)
        # Protect extraction even if a repository later contains unsafe symlinks.
        with tarfile.open(archive) as tar:
            tar.extractall(release, filter='data')
        env = os.environ.copy()
        env.update(DOCKER_CONFIG=str(temp / 'docker'), SF_DEPLOY_ROOT=str(root),
                   SF_DEPLOY_LOCAL='1', SF_DEPLOY_GATEWAY=gateway)
        # Keep the short-lived GITHUB_TOKEN out of argv, logs and server .docker.
        env.pop('REGISTRY_TOKEN', None)
        subprocess.run(['docker', 'login', 'ghcr.io', '-u', actor, '--password-stdin'],
                       input=token, text=True, check=True, env=env, capture_output=True)
        try:
            subprocess.run(['bash', str(release / 'scripts/deploy.sh'), sha, *images], check=True, env=env)
        finally:
            subprocess.run(['docker', 'logout', 'ghcr.io'], env=env, capture_output=True)


if __name__ == '__main__':
    main()
