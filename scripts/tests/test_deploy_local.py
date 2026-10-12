import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

scripts = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy_local', scripts / 'deploy_local.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = 'a' * 40


class LocalDeployChecks(unittest.TestCase):
    def settings(self, root):
        return dict(GITHUB_SHA=SHA, GITHUB_REPOSITORY='SurakTH/smart-finance',
                    GITHUB_REF='refs/heads/main', GITHUB_ACTOR='SurakTH',
                    REGISTRY_TOKEN='synthetic-workflow-token', LOCAL_DEPLOY_PATH=str(root))

    def test_bad_inputs_do_not_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('SERVER_SECRET=keep-here')
            (root / 'compose.yaml').touch()
            for key, value in [('GITHUB_SHA', 'main'), ('GITHUB_REF', 'refs/pull/1/merge'),
                               ('GITHUB_REPOSITORY', 'bad;command'), ('LOCAL_DEPLOY_PATH', ''),
                               ('LOCAL_DEPLOY_GATEWAY', 'invalid'), ('REGISTRY_TOKEN', '')]:
                env = self.settings(root)
                env[key] = value
                with patch.dict(os.environ, env, clear=True), patch.object(module.subprocess, 'run') as run:
                    with self.assertRaises(SystemExit):
                        module.main()
                    run.assert_not_called()

    def test_exact_images_temporary_auth_and_unchanged_server_environment(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / '.env').write_text('SERVER_SECRET=keep-here')
                (root / 'compose.yaml').touch()
                calls, config_paths = [], []
                def run(args, **kwargs):
                    calls.append(args)
                    self.assertNotIn('synthetic-workflow-token', ' '.join(args))
                    if args[:2] == ['git', 'rev-parse']:
                        return subprocess.CompletedProcess(args, 0, stdout=SHA + '\n')
                    if args[:2] == ['git', 'archive']:
                        archive = Path(next(a.split('=', 1)[1] for a in args if a.startswith('--output=')))
                        with tarfile.open(archive, 'w') as tar:
                            data = b'echo deploy\n'
                            item = tarfile.TarInfo('scripts/deploy.sh')
                            item.size = len(data)
                            tar.addfile(item, io.BytesIO(data))
                    if args[0] in ('docker', 'bash'):
                        env = kwargs['env']
                        self.assertNotIn('REGISTRY_TOKEN', env)
                        config_paths.append(env['DOCKER_CONFIG'])
                        self.assertEqual(Path(env['DOCKER_CONFIG']).parent.stat().st_mode & 0o777, 0o700)
                    if args[:2] == ['docker', 'login']:
                        self.assertEqual(kwargs['input'], 'synthetic-workflow-token')
                        self.assertTrue(kwargs['capture_output'])
                    if args[0] == 'bash':
                        self.assertEqual(args[-2:], [f'ghcr.io/surakth/smart-finance/{kind}:{SHA}' for kind in ('backend', 'web')])
                        self.assertEqual(kwargs['env']['SF_DEPLOY_GATEWAY'], 'caddy')
                        if fail:
                            raise subprocess.CalledProcessError(1, args)
                    return subprocess.CompletedProcess(args, 0)
                with patch.dict(os.environ, self.settings(root), clear=True), patch.object(module.subprocess, 'run', side_effect=run):
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError):
                            module.main()
                    else:
                        module.main()
                self.assertEqual(calls[-1][:2], ['docker', 'logout'])
                self.assertEqual((root / '.env').read_text(), 'SERVER_SECRET=keep-here')
                self.assertFalse((root / 'releases' / SHA / '.env').exists())
                self.assertTrue(all(not Path(p).parent.exists() for p in config_paths))

    def test_shell_preserves_telegram_and_backs_up_before_upgrade(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                release = root / 'releases' / SHA
                (release / 'scripts').mkdir(parents=True)
                (root / '.env').write_text('APP_ORIGIN=http://192.168.25.5:8080\n')
                for name in ('deploy.sh', 'backup.sh'):
                    (release / 'scripts' / name).write_bytes((scripts / name).read_bytes())
                binary = root / 'bin'
                binary.mkdir()
                log = root / 'commands'
                docker = binary / 'docker'
                docker.write_text('#!/bin/sh\necho "$COMPOSE_PROJECT_NAME $COMPOSE_FILE $*" >> "$COMMAND_LOG"\n'
                                  'case "$*" in\n*"ps --status running --services"*) echo telegram;;\n'
                                  '*pg_dump*) [ "$FAIL_BACKUP" = 1 ] && exit 1; echo synthetic-dump;;\nesac\nexit 0\n')
                docker.chmod(0o700)
                # flock is Linux-specific; this test only models successful acquisition.
                flock = binary / 'flock'
                flock.write_text('#!/bin/sh\nexit 0\n')
                flock.chmod(0o700)
                env = os.environ | dict(PATH=str(binary) + ':' + os.environ['PATH'],
                    SF_DEPLOY_ROOT=str(root), SF_DEPLOY_LOCAL='1', SF_DEPLOY_GATEWAY='caddy',
                    COMMAND_LOG=str(log), FAIL_BACKUP=str(int(fail)))
                result = subprocess.run(['bash', str(release / 'scripts/deploy.sh'), SHA,
                    f'ghcr.io/example/app/backend:{SHA}', f'ghcr.io/example/app/web:{SHA}'], env=env, capture_output=True)
                self.assertEqual(result.returncode, int(fail), result.stderr)
                lines = log.read_text().splitlines()
                stop = next(i for i, row in enumerate(lines) if 'stop api worker telegram' in row)
                backup = next(i for i, row in enumerate(lines) if 'pg_dump' in row)
                self.assertLess(stop, backup)
                self.assertTrue(all('smart-finance compose.yaml:compose.release.yaml' in row for row in lines))
                if fail:
                    self.assertTrue(any('start api worker telegram' in row for row in lines))
                    self.assertFalse(any('up -d' in row for row in lines))
                    self.assertFalse((root / 'current-commit').exists())
                else:
                    upgrade = next(i for i, row in enumerate(lines) if 'up -d --no-build' in row)
                    self.assertLess(backup, upgrade)
                    self.assertIn('api worker web proxy telegram', lines[upgrade])
                    self.assertEqual((root / 'current-commit').read_text().strip(), SHA)


if __name__ == '__main__':
    unittest.main()
