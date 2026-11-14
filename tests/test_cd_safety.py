"""Local product tests; no host, Docker, or deployment qualification."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class DeliverySafety(unittest.TestCase):
    def setUp(self):
        import delivery
        self.d = delivery
        self.config = json.loads((ROOT / 'config/projects/sevenbot-flow-probe.json').read_text())

    def test_valid_config(self):
        self.assertEqual(self.d.validate_config(self.config)['service'], 'sevenbot-flow-probe')

    def test_config_negative_no_effect(self):
        for key, value in [('source_repo', 'evil/repo'), ('source_branch', 'main;id'),
                           ('dockerfile', '../Dockerfile'), ('service', 'hermes-runtime'),
                           ('runner', 'self-hosted'), ('port', 80),
                           ('test', ['bash', '-c', 'touch sentinel']), ('extra', True)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
                config = copy.deepcopy(self.config)
                config[key] = value
                path = Path(tmp) / 'config.json'
                path.write_text(json.dumps(config))
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/delivery.py'),
                                         'validate', '--config', str(path)], cwd=tmp,
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((Path(tmp) / 'sentinel').exists())

    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            p = Path(tmp) / 'bad.json'
            p.write_text('{"service":"x","service":"y"}')
            with self.assertRaises(ValueError):
                self.d.load_json(p)

    def test_paths_reject_symlink_and_dot_segments(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            root = Path(tmp)
            (root / 'file').write_text('x')
            (root / 'link').symlink_to(root / 'file')
            self.assertEqual(self.d.safe_file(root, 'file'), root / 'file')
            for path in ['../file', './file', 'a/../file', '/file', 'link', 'missing', 'a//b']:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    self.d.safe_file(root, path)

    def test_privileged_caller_exclusion(self):
        good = dict(repository='timmypai/hermes-teams-cd-public', ref='refs/heads/main',
                    event='workflow_dispatch', sha='a' * 40, run_id='123', attempt='1',
                    workflow_ref='timmypai/hermes-teams-cd-public/.github/workflows/deploy.yml@refs/heads/main')
        self.d.validate_context(good, privileged=True)
        for key, value in [('repository', 'evil/caller'), ('ref', 'refs/pull/1/merge'),
                           ('event', 'pull_request'), ('sha', 'main'), ('attempt', '0'),
                           ('workflow_ref', 'evil/caller/.github/workflows/deploy.yml@refs/heads/main')]:
            bad = dict(good, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.d.validate_context(bad, privileged=True)

    def test_activation_is_unbound(self):
        with self.assertRaisesRegex(ValueError, 'UNBOUND'):
            self.d.require_activation()

    def test_provenance_exact_binding(self):
        receipt = self.d.make_provenance('a' * 40, 'b' * 64, 'sha256:' + 'c' * 64,
                                         '123', '1', 'd' * 40)
        self.d.validate_provenance(receipt, source='a' * 40, run='123', attempt='1', shared='d' * 40)
        for key, value in [('source_sha', 'f' * 40), ('repository', 'evil/repo'),
                           ('run_attempt', '2'), ('archive_sha256', 'bad'),
                           ('image_id', 'latest'), ('shared_sha', 'e' * 40)]:
            bad = dict(receipt, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.d.validate_provenance(bad, source='a' * 40, run='123', attempt='1', shared='d' * 40)

    def test_existing_resource_no_mutation(self):
        calls = []
        def command(args):
            calls.append(args)
            return 'existing-id' if args[:2] == ['container', 'ls'] else ''
        with self.assertRaisesRegex(ValueError, 'existing'):
            self.d.install_container(command, 'sha256:' + 'c' * 64, 'a' * 40, 'flow-probe-v1')
        self.assertEqual(len(calls), 1)

    def test_container_positive_security_arguments(self):
        calls = []
        def command(args):
            calls.append(args)
            return ''
        self.d.install_container(command, 'sha256:' + 'c' * 64, 'a' * 40, 'flow-probe-v1')
        argv = calls[1]
        for value in ['127.0.0.1:18080:8080', '128m', '0.5', '64', '--read-only',
                      '65532:65532', 'ALL', 'no-new-privileges:true', '/tmp:rw,noexec,nosuid,size=16m']:
            self.assertIn(value, argv)
        for value in ['--privileged', '--network=host', '-v', '--mount']:
            self.assertNotIn(value, argv)

    def test_bad_image_stops_before_command(self):
        calls = []
        for image in ['latest', 'sha256:$(id)', 'sha256:' + 'g' * 64]:
            with self.assertRaises(ValueError):
                self.d.install_container(lambda x: calls.append(x), image, 'a' * 40, 'flow-probe-v1')
        self.assertEqual(calls, [])

    def test_status_freshness(self):
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        receipt = {'schema_version': 1, 'state': 'running', 'observed_source_sha': 'a' * 40,
                   'observed_image_id': 'sha256:' + 'c' * 64, 'conclusion': 'success',
                   'collected_at_utc': now.isoformat(), 'target': 'sevenbot-flow-probe',
                   'source_sha': 'a' * 40, 'image_id': 'sha256:' + 'c' * 64,
                   'healthy': True, 'message': 'sevenbot-flow-probe-v1',
                   'workflow_repository': 'timmypai/hermes-teams-cd-public',
                   'workflow_ref': 'timmypai/hermes-teams-cd-public/.github/workflows/status.yml@refs/heads/main',
                   'run_id': '12', 'run_attempt': '1'}
        self.d.validate_status(receipt, source='a' * 40, image='sha256:' + 'c' * 64,
                               run='12', attempt='1', workflow=receipt['workflow_ref'], now=now)
        for age in [301, -10]:
            bad = dict(receipt, collected_at_utc=(now - timedelta(seconds=age)).isoformat())
            with self.assertRaises(ValueError):
                self.d.validate_status(bad, source='a' * 40, image='sha256:' + 'c' * 64,
                                       run='12', attempt='1', workflow=receipt['workflow_ref'], now=now)

    def test_helper_binding_not_caller_checkout(self):
        self.assertEqual(self.d.helper_root(), ROOT)
        self.assertNotEqual(self.d.helper_root(), ROOT.parent / 'caller')


if __name__ == '__main__':
    unittest.main()
