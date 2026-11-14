"""Local behavioral fixtures; these are not live deployment evidence."""
import argparse
from datetime import datetime, timezone, timedelta
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
import status_readback


class Revision2(unittest.TestCase):
    def receipt(self):
        return dict(schema_version=1, state='running', observed_source_sha='a'*40,
            observed_image_id='sha256:'+'b'*64, conclusion='success',
            collected_at_utc=datetime.now(timezone.utc).isoformat(), target=d.SERVICE,
            source_sha='a'*40, image_id='sha256:'+'b'*64, healthy=True,
            message='sevenbot-flow-probe-v1', workflow_repository=d.CD_REPO,
            workflow_ref=f'{d.CD_REPO}/.github/workflows/status.yml@refs/heads/main',
            run_id='100', run_attempt='1')

    def test_status_cli_negative_nonzero_no_effect(self):
        now = datetime.now(timezone.utc)
        changes = [('schema_version', True), ('extra', 'x'), ('target', 'hermes-runtime'),
            ('source_sha', 'c'*40), ('observed_image_id', 'latest'), ('healthy', False),
            ('workflow_repository', 'evil/repo'), ('run_id', '101'), ('run_attempt', '2'),
            ('collected_at_utc', now.replace(tzinfo=None).isoformat()),
            ('collected_at_utc', (now-timedelta(seconds=301)).isoformat()),
            ('collected_at_utc', (now+timedelta(seconds=30)).isoformat())]
        for key, value in changes:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory(dir=ROOT.parent/'fixtures') as tmp:
                root = Path(tmp)
                receipt = dict(self.receipt(), **{key:value})
                (root/'status.json').write_text(json.dumps(receipt))
                result = subprocess.run([sys.executable, str(ROOT/'scripts/status_readback.py'),
                    '--receipt', str(root/'status.json'), '--source', 'a'*40,
                    '--image', 'sha256:'+'b'*64, '--run', '100', '--attempt', '1'],
                    cwd=root, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('status UNKNOWN:', result.stderr)
                self.assertEqual(sorted(p.name for p in root.iterdir()), ['status.json'])

    def test_status_api_positive_and_wrong_exact_run(self):
        receipt = self.receipt()
        api = dict(id=100, repository={'full_name':d.CD_REPO},
            path='.github/workflows/status.yml', head_branch='main', event='workflow_dispatch',
            run_attempt=1, status='completed', conclusion='success')
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'fixtures') as tmp:
            path = Path(tmp)/'status.json'
            path.write_text(json.dumps(receipt))
            argv = ['status_readback', '--receipt', str(path), '--source', 'a'*40,
                '--image', 'sha256:'+'b'*64, '--run', '100', '--attempt', '1']
            with patch.object(sys, 'argv', argv), patch.object(d, 'github_get', return_value=api):
                status_readback.main()
            with patch.object(sys, 'argv', argv), patch.object(d, 'github_get', return_value=dict(api, id=101)):
                with self.assertRaises(ValueError):
                    status_readback.main()

    def test_rollback_and_failed_forward_recover_missing_candidate(self):
        # Fixed mock Docker; exercise real operate ordering and receipts.
        for mode in ('rollback', 'forward-health-failure', 'forward-create-failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=ROOT.parent/'fixtures') as tmp:
                root = Path(tmp)
                (root/'image.tar').write_bytes(b'not a real image')
                image, old_image = 'sha256:'+'b'*64, 'sha256:'+'c'*64
                source, old_source = 'a'*40, 'd'*40
                (root/'provenance.json').write_text(json.dumps(d.make_provenance(source,
                    d.sha256(root/'image.tar'), image, '90', '1', 'e'*40)))
                previous = dict(source_sha=old_source, image_id=old_image, run_id='95',
                    run_attempt='1', message='sevenbot-flow-probe-v2')
                (root/'previous.json').write_text(json.dumps(previous))
                (root/'known.json').write_text(json.dumps(dict(source_sha=source, image_id=image,
                    run_id='80', run_attempt='1', message='sevenbot-flow-probe-v1')))
                evidence = root/'evidence'; evidence.mkdir()
                args = argparse.Namespace(artifact=str(root), source=source, artifact_run='90',
                    artifact_attempt='1', shared='e'*40, operation='rollback' if mode=='rollback' else 'deploy',
                    previous=str(root/'previous.json'), previous_run='95', previous_attempt='1',
                    known_healthy=str(root/'known.json'), known_run='80', known_attempt='1',
                    revision='flow-probe-v1', evidence=str(evidence))
                state = {'image':old_image, 'source':old_source, 'run':'95', 'attempt':'1'}
                calls=[]
                def docker(argv):
                    calls.append(argv)
                    if argv[:2]==['container','ls']: return 'id' if state else ''
                    if argv[:2]==['image','inspect']: return argv[-1]
                    if argv[:2]==['container','inspect']:
                        if not state: raise ValueError('no container')
                        return json.dumps({k:state[k] for k in ('image','source')} if 'sevenbot.run' not in argv[3] else state)
                    if argv[:2]==['container','rm']: state.clear(); return ''
                    if argv[0]=='run':
                        selected = old_image if old_image in argv else image
                        if selected==image and mode=='forward-create-failure': raise ValueError('create failed')
                        state.update(image=selected, source=old_source if selected==old_image else source,
                            run='100', attempt='1')
                    return ''
                def health(run, sha, selected, revision, c):
                    if selected==image and mode=='forward-health-failure': raise ValueError('unhealthy')
                    return dict(healthy=True, image_id=selected, source_sha=sha)
                with patch.object(d,'docker',side_effect=docker), patch.object(d,'source_gate'), patch.object(d,'artifact_gate'), patch.object(d,'known_health',side_effect=lambda value, *unused, **keywords: value), patch.object(d,'collect_status',side_effect=health):
                    if mode=='rollback':
                        d.operate(args, dict(run_id='100', attempt='1'))
                        self.assertEqual(json.loads((evidence/'status.json').read_text())['image_id'], image)
                    else:
                        with self.assertRaises(ValueError): d.operate(args, dict(run_id='100', attempt='1'))
                        self.assertEqual(json.loads((evidence/'failure.json').read_text())['recovery'], 'RESTORED_AND_HEALTH_VERIFIED')
                        self.assertEqual(state['image'], old_image)
                        self.assertFalse((evidence/'status.json').exists())


if __name__ == '__main__': unittest.main()
