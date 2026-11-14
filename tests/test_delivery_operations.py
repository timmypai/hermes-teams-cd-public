"""Behavioral controls: local mocks only, never host/deployment qualification."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import delivery as d


class Operations(unittest.TestCase):
    def test_unqualified_approval_is_not_release_authority(self):
        source = 'a' * 40
        pr = dict(number=1, merged_at='now', merge_commit_sha=source,
                  base={'ref': 'main', 'repo': {'full_name': d.SOURCE_REPO}},
                  head={'sha': 'b' * 40}, user={'id': 1})
        review = dict(state='APPROVED', commit_id='b' * 40,
                      user={'id': 2, 'type': 'User'}, author_association='NONE')
        check = dict(name='ci', head_sha=source, status='completed', conclusion='success',
                     app={'slug': 'github-actions'})
        calls = []
        def api(path):
            calls.append(path)
            if path.endswith('commits/main'):
                return {'sha': source}
            if path.endswith('/pulls'):
                return [pr]
            if path.endswith('/reviews'):
                return [review]
            return {'total_count': 1, 'check_runs': [check]}
        with patch.object(d, 'github_get', side_effect=api), patch.object(d, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'approval'):
                d.source_gate(source)
            docker.assert_not_called()

    def test_previous_receipt_must_match_download_run(self):
        receipt = dict(target=d.SERVICE, healthy=True, workflow_repository=d.CD_REPO,
                       source_sha='a' * 40, image_id='sha256:' + 'b' * 64,
                       run_id='100', run_attempt='1', message='sevenbot-flow-probe-v1',
                       workflow_ref=f'{d.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main')
        with patch.object(d, 'github_get') as api:
            with self.assertRaises(ValueError):
                d.known_health(receipt, expected_run='101', expected_attempt='1')
            api.assert_not_called()

    def test_failed_receipt_collection_does_not_start_container(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            root = Path(tmp)
            (root / 'image.tar').write_bytes(b'local fixture, not an image')
            p = d.make_provenance('a' * 40, d.sha256(root / 'image.tar'),
                                  'sha256:' + 'b' * 64, '100', '1', 'c' * 40)
            (root / 'provenance.json').write_text(json.dumps(p))
            args = argparse.Namespace(artifact=str(root), source='a' * 40, artifact_run='100',
                artifact_attempt='2', shared='c' * 40, operation='deploy', previous='',
                known_healthy='', revision='flow-probe-v1', evidence=str(root))
            with patch.object(d, 'docker') as docker, patch.object(d, 'github_get') as api:
                with self.assertRaises(ValueError):
                    d.operate(args, {})
                docker.assert_not_called()
                api.assert_not_called()
                self.assertFalse((root / 'status.json').exists())

    def test_artifact_gate_positive_and_negative(self):
        p = d.make_provenance('a' * 40, 'b' * 64, 'sha256:' + 'c' * 64, '100', '1', 'd' * 40)
        run = dict(run_attempt=1, conclusion='success', status='completed', event='workflow_dispatch',
                   head_branch='main', head_sha='d' * 40, path='.github/workflows/publish.yml',
                   repository={'full_name': d.CD_REPO})
        artifacts = dict(total_count=1, artifacts=[dict(name='image-100-1', expired=False,
                                                     digest='sha256:' + 'e' * 64)])
        with patch.object(d, 'github_get', side_effect=[run, artifacts]):
            d.artifact_gate(p)
        for key, value in [('run_attempt', 2), ('event', 'pull_request'), ('head_branch', 'evil'),
                           ('repository', {'full_name': 'evil/repo'}), ('conclusion', 'failure')]:
            with self.subTest(key=key), patch.object(d, 'github_get', return_value=dict(run, **{key: value})), patch.object(d, 'docker') as docker:
                with self.assertRaises(ValueError):
                    d.artifact_gate(p)
                docker.assert_not_called()

    def test_collect_status_real_function_assertion(self):
        image = 'sha256:' + 'c' * 64
        context = dict(repository=d.CD_REPO, workflow_ref=f'{d.CD_REPO}/.github/workflows/status.yml@refs/heads/main', run_id='102', attempt='1')
        replies = [dict(schema_version=1, source_sha='a' * 40, response_revision='flow-probe-v1'),
                   {'healthy': True}, {'message': 'sevenbot-flow-probe-v1'}]
        with patch.object(d, 'http_json', side_effect=replies):
            status = d.collect_status(lambda _: json.dumps({'image': image, 'running': True}), 'a' * 40, image, 'flow-probe-v1', context)
        d.validate_status(status, source='a' * 40, image=image, run='102', attempt='1', workflow=context['workflow_ref'])
        replies[-1] = {'message': 'wrong'}
        with patch.object(d, 'http_json', side_effect=replies), self.assertRaisesRegex(ValueError, 'function'):
            d.collect_status(lambda _: json.dumps({'image': image, 'running': True}), 'a' * 40, image, 'flow-probe-v1', context)


if __name__ == '__main__':
    unittest.main()
