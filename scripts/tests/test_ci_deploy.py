import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('ci_deploy',Path(__file__).resolve().parents[1]/'ci_deploy.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class DeployChecks(unittest.TestCase):
    def settings(self):
        sha='a'*40
        return dict(DEPLOY_HOST='server.example.com',DEPLOY_USER='deploy',DEPLOY_PORT='22',GITHUB_SHA=sha,BACKEND_IMAGE='ghcr.io/example/app/backend:'+sha,WEB_IMAGE='ghcr.io/example/app/web:'+sha,DEPLOY_SSH_KEY='synthetic-private-key',DEPLOY_KNOWN_HOSTS='synthetic-known-host')
    def test_bad_inputs_never_execute(self):
        for field,value in [('DEPLOY_HOST','-oProxyCommand=bad'),('DEPLOY_USER','a;bad'),('DEPLOY_PORT','70000'),('GITHUB_SHA','main'),('BACKEND_IMAGE','other:tag'),('DEPLOY_KNOWN_HOSTS','')]:
            env=self.settings();env[field]=value
            with patch.dict(os.environ,env,clear=True),patch.object(module.subprocess,'run') as run:
                with self.assertRaises(SystemExit):module.main()
                run.assert_not_called()
    def test_transfer_exact_commit_without_secret_arguments(self):
        calls=[];env=self.settings()
        def run(args,**kw):
            calls.append(args)
            self.assertNotIn(env['DEPLOY_SSH_KEY'],' '.join(args))
            if args[0]=='ssh':
                self.assertIn('StrictHostKeyChecking=yes',args)
                key=Path(args[args.index('-i')+1]);self.assertEqual(key.stat().st_mode&0o777,0o600)
        with patch.dict(os.environ,env,clear=True),patch.object(module.subprocess,'run',side_effect=run):module.main()
        self.assertEqual(calls[0][-1],env['GITHUB_SHA'])
        self.assertEqual([x[0] for x in calls],['git','ssh','scp','ssh'])

if __name__=='__main__':unittest.main()
