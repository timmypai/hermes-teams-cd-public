"""No host execution: fixed local behavioral fixtures and entry rejection controls."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import delivery as d
import workflow_entry as entry


class EntrySafety(unittest.TestCase):
    def test_wrong_context_cli_nonzero_no_evidence(self):
        good = dict(GITHUB_REPOSITORY=d.CD_REPO, GITHUB_REF='refs/heads/main',
                    GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='a' * 40,
                    GITHUB_RUN_ID='100', GITHUB_RUN_ATTEMPT='1',
                    GITHUB_WORKFLOW_REF=f'{d.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main')
        for key, value in [('GITHUB_REPOSITORY', 'evil/repo'), ('GITHUB_REF', 'refs/pull/1/merge'),
                           ('GITHUB_SHA', 'main'), ('GITHUB_RUN_ATTEMPT', '0'),
                           ('GITHUB_EVENT_NAME', 'pull_request')]:
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
                env = dict(os.environ, **good)
                env[key] = value
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/delivery.py'), 'deploy',
                    '--config', str(ROOT / 'config/projects/sevenbot-flow-probe.json'),
                    '--shared', 'b' * 40], env=env, cwd=tmp, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('delivery stopped:', result.stderr)
                self.assertFalse((Path(tmp) / 'evidence').exists())

    def test_entry_positive_and_helper_substitution_rejected(self):
        c = dict(repository=d.CD_REPO, ref='refs/heads/main', event='workflow_dispatch',
                 sha='a' * 40, run_id='100', attempt='1',
                 workflow_ref=f'{d.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main')
        env = dict(HELPER_SHA='b' * 40, SOURCE_SHA='c' * 40, ARTIFACT_RUN='90', ARTIFACT_ATTEMPT='1')
        with patch.dict(os.environ, env, clear=True), patch.object(d, 'context', return_value=c), patch.object(d, 'command', side_effect=['b' * 40, '']):
            args, _ = entry.inputs('deploy')
            self.assertEqual(args.artifact, 'artifact')
            self.assertEqual(args.shared, 'b' * 40)
        with patch.dict(os.environ, env, clear=True), patch.object(d, 'command', return_value='d' * 40), patch.object(d, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'helper checkout'):
                entry.inputs('deploy')
            docker.assert_not_called()

    def test_deploy_positive_and_recovery_failure_stays_failed(self):
        for fail_health in (False, True):
            with self.subTest(fail_health=fail_health), tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
                root = Path(tmp)
                (root / 'image.tar').write_bytes(b'fixed mock image bytes')
                image = 'sha256:' + 'b' * 64
                source = 'a' * 40
                p = d.make_provenance(source, d.sha256(root / 'image.tar'), image, '90', '1', 'c' * 40)
                (root / 'provenance.json').write_text(json.dumps(p))
                evidence = root / 'evidence'
                evidence.mkdir()
                args = argparse.Namespace(artifact=str(root), source=source, artifact_run='90',
                    artifact_attempt='1', shared='c' * 40, operation='deploy', previous='',
                    known_healthy='', revision='flow-probe-v1', evidence=str(evidence))
                calls = []
                def docker(argv):
                    calls.append(argv)
                    if argv[:2] == ['container', 'ls']:
                        return ''
                    if argv[:2] == ['image', 'inspect']:
                        return image
                    return 'candidate'
                receipt = {'healthy': True, 'target': d.SERVICE}
                with patch.object(d, 'docker', side_effect=docker), patch.object(d, 'artifact_gate'), patch.object(d, 'source_gate'), patch.object(d, 'collect_status', side_effect=ValueError('health fail') if fail_health else None, return_value=receipt):
                    if fail_health:
                        with self.assertRaises(ValueError):
                            d.operate(args, dict(run_id='100', attempt='1'))
                        failure = json.loads((evidence / 'failure.json').read_text())
                        self.assertEqual(failure['result'], 'FAIL')
                        self.assertEqual(failure['recovery'], 'NOT_AVAILABLE_INITIAL_DEPLOY')
                        self.assertFalse((evidence / 'status.json').exists())
                    else:
                        d.operate(args, dict(run_id='100', attempt='1'))
                        self.assertEqual(json.loads((evidence / 'status.json').read_text()), receipt)
                self.assertTrue(any(x[0] == 'run' for x in calls))
                self.assertFalse(any(x[:2] == ['container', 'rm'] for x in calls))


if __name__ == '__main__':
    unittest.main()
