"""Destructive-transition regressions: disposable fixed mocks, NOT live proof."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import delivery as d


class TransitionSafety(unittest.TestCase):
    def exercise(self, mode='forward', revision='flow-probe-v1'):
        with tempfile.TemporaryDirectory(prefix='run117-', dir=ROOT.parent/'fixtures') as tmp:
            root = Path(tmp)
            source, image = 'a'*40, 'sha256:'+'b'*64
            old_source, old_image = 'c'*40, 'sha256:'+'d'*64
            (root/'image.tar').write_bytes(b'fixed disposable archive; not a Docker image')
            (root/'provenance.json').write_text(json.dumps(d.make_provenance(
                source, d.sha256(root/'image.tar'), image, '70', '1', 'e'*40)))

            def receipt(sha, img, run, rev):
                return dict(target=d.SERVICE, source_sha=sha, image_id=img, healthy=True,
                    message='sevenbot-'+rev, workflow_repository=d.CD_REPO,
                    workflow_ref=f'{d.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main',
                    run_id=run, run_attempt='1')

            previous = receipt(old_source, old_image, '95', 'flow-probe-v2')
            known = receipt(source, image, '80', 'flow-probe-v1')
            (root/'previous.json').write_text(json.dumps(previous))
            (root/'known.json').write_text(json.dumps(known))
            evidence = root/'evidence'; evidence.mkdir()
            args = argparse.Namespace(artifact=str(root), source=source, artifact_run='70',
                artifact_attempt='1', shared='e'*40,
                operation='rollback' if mode=='rollback' else 'deploy',
                previous=str(root/'previous.json'), previous_run='95', previous_attempt='1',
                known_healthy=str(root/'known.json'), known_run='80', known_attempt='1',
                revision=revision, evidence=str(evidence))
            state = dict(image=old_image, source=old_source, run='95', attempt='1', running=True)
            calls, health_calls = [], []
            injected = False

            def docker(argv):
                nonlocal injected
                calls.append(argv)
                if argv[:2]==['container','ls']: return 'fixed-owned-id' if state else ''
                if argv[:2]==['image','inspect']: return argv[-1]
                if argv[:2]==['container','inspect']:
                    return json.dumps({k:state[k] for k in ('image','source','run','attempt')})
                if argv[:2]==['container','stop']:
                    if mode=='stop_before' and not injected:
                        injected=True
                        raise ValueError('fixed stop failure')
                    state['running']=False
                    if mode=='stop_after' and not injected:
                        injected=True
                        raise ValueError('fixed ambiguous stop')
                if argv[:2]==['container','rm']:
                    if mode=='remove_before' and not injected:
                        injected=True
                        raise ValueError('fixed remove failure')
                    state.clear()
                    if mode=='remove_after' and not injected:
                        injected=True
                        raise ValueError('fixed ambiguous removal')
                if argv[0]=='run':
                    selected = image if image in argv else old_image
                    if selected==image and mode in ('recovery_failure', 'candidate_conflict'):
                        if mode=='candidate_conflict':
                            state.update(image=old_image, source=old_source, run='999', attempt='1', running=True)
                        raise ValueError('fixed candidate failure')
                    if selected==old_image and mode=='recovery_failure':
                        raise ValueError('fixed recovery failure')
                    state.update(image=selected, source=source if selected==image else old_source,
                        run='100', attempt='1', running=True, revision=argv[-1])
                return ''

            def api(path):
                run = path.rsplit('/',1)[-1]
                return dict(id=int(run), repository={'full_name':d.CD_REPO}, status='completed',
                    conclusion='success', run_attempt=1, head_branch='main', event='workflow_dispatch',
                    path='.github/workflows/deploy.yml')

            def health(run, sha, img, rev, context):
                health_calls.append((sha, img, rev))
                self.assertTrue(state['running'])
                self.assertEqual(state['image'], img)
                # Original old container has no explicit fixture revision; replacement does.
                if 'revision' in state:
                    self.assertEqual(state['revision'], rev)
                return receipt(sha, img, context['run_id'], rev)

            error = None
            with patch.object(d,'docker',side_effect=docker), patch.object(d,'artifact_gate'), \
                 patch.object(d,'source_gate'), patch.object(d,'github_get',side_effect=api), \
                 patch.object(d,'collect_status',side_effect=health):
                try:
                    d.operate(args, dict(run_id='100', attempt='1'))
                except ValueError as exc:
                    error = str(exc)
            return dict(error=error, state=dict(state), calls=calls, health=health_calls,
                evidence={p.name:json.loads(p.read_text()) for p in evidence.iterdir()},
                mutations=[x for x in calls if x[0]=='run' or x[:2] in (
                    ['image','load'], ['container','stop'], ['container','rm'])])

    def test_valid_forward_and_exact_configuration_rollback(self):
        for mode in ('forward','rollback'):
            with self.subTest(mode=mode):
                result = self.exercise(mode)
                self.assertIsNone(result['error'])
                self.assertEqual(set(result['evidence']), {'status.json'})
                self.assertEqual(result['evidence']['status.json']['message'], 'sevenbot-flow-probe-v1')
                self.assertEqual(result['health'], [('a'*40, 'sha256:'+'b'*64, 'flow-probe-v1')])

    def test_rollback_wrong_configuration_has_zero_mutations(self):
        result = self.exercise('rollback', 'flow-probe-v2')
        self.assertIsNotNone(result['error'])
        self.assertEqual(result['mutations'], [])
        self.assertEqual(result['evidence'], {})
        self.assertTrue(result['state']['running'])
        self.assertEqual(result['state']['run'], '95')
        self.assertEqual(result['health'], [])

    def test_stop_and_remove_errors_emit_incident_without_retouching_old_container(self):
        for mode, running in (('stop_before',True), ('stop_after',False), ('remove_before',False)):
            with self.subTest(mode=mode):
                result = self.exercise(mode)
                self.assertIsNotNone(result['error'])
                self.assertEqual(set(result['evidence']), {'failure.json'})
                self.assertEqual(result['evidence']['failure.json']['recovery'], 'FAILED_STOP_INCIDENT_REQUIRED')
                self.assertEqual(result['state']['run'], '95')
                self.assertEqual(result['state']['running'], running)
                self.assertEqual(sum(x[:2]==['container','stop'] for x in result['calls']), 1)
                self.assertEqual(sum(x[:2]==['container','rm'] for x in result['calls']), int(mode=='remove_before'))
                self.assertFalse(any(x[0]=='run' for x in result['calls']))

    def test_ambiguous_remove_completed_restores_bound_previous_configuration(self):
        result = self.exercise('remove_after')
        self.assertIsNotNone(result['error'])
        self.assertEqual(set(result['evidence']), {'failure.json','recovery.json'})
        self.assertEqual(result['evidence']['failure.json']['recovery'], 'RESTORED_AND_HEALTH_VERIFIED')
        self.assertEqual(result['state']['revision'], 'flow-probe-v2')
        self.assertEqual(result['health'], [('c'*40, 'sha256:'+'d'*64, 'flow-probe-v2')])
        self.assertEqual(sum(x[:2]==['container','rm'] for x in result['calls']), 1)

    def test_recovery_failure_and_conflict_preserve_failure_not_false_success(self):
        for mode in ('recovery_failure','candidate_conflict'):
            with self.subTest(mode=mode):
                result = self.exercise(mode)
                self.assertIsNotNone(result['error'])
                self.assertEqual(set(result['evidence']), {'failure.json'})
                self.assertEqual(result['evidence']['failure.json']['recovery'], 'FAILED_STOP_INCIDENT_REQUIRED')
                self.assertEqual(sum(x[:2]==['container','rm'] for x in result['calls']), 1)
                if mode=='candidate_conflict':
                    self.assertEqual(result['state']['run'], '999')
                    self.assertTrue(result['state']['running'])

    def test_transition_errors_remain_nonzero_in_disposable_subprocess(self):
        # Run the real operate path with only fixed API/Docker/HTTP fixtures.
        import subprocess
        for mode, revision in (('stop_after','flow-probe-v1'),
                               ('remove_before','flow-probe-v1'),
                               ('remove_after','flow-probe-v1'),
                               ('recovery_failure','flow-probe-v1'),
                               ('rollback','flow-probe-v2')):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    '--fixture', mode, revision], cwd=ROOT, capture_output=True,
                    text=True, timeout=20)
                self.assertEqual(result.returncode, 1, result.stderr)
                observed = json.loads(result.stdout)
                self.assertNotIn('status.json', observed['evidence'])
                if mode=='rollback':
                    self.assertEqual(observed['mutations'], [])
                    self.assertEqual(observed['evidence'], {})
                else:
                    self.assertIn('failure.json', observed['evidence'])
        control = subprocess.run([sys.executable, str(Path(__file__).resolve()),
            '--fixture', 'rollback', 'flow-probe-v1'], cwd=ROOT, capture_output=True,
            text=True, timeout=20)
        self.assertEqual(control.returncode, 0, control.stderr)
        self.assertIn('status.json', json.loads(control.stdout)['evidence'])

    def test_current_config_schema_have_no_author_repair_quota(self):
        config = d.load_json(ROOT/'config/projects/sevenbot-flow-probe.json')
        schema = d.load_json(ROOT/'config/project.schema.json')
        self.assertNotIn('repairs', config['budget'])
        self.assertEqual(schema['properties']['budget']['const'], config['budget'])
        self.assertEqual(set(config['budget']), {'job_seconds', 'initial', 'forward', 'rollback'})
        d.validate_config(config)
        config['budget']['repairs'] = 2
        with self.assertRaises(ValueError):
            d.validate_config(config)


if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--fixture':
        result = TransitionSafety().exercise(sys.argv[2], sys.argv[3])
        print(json.dumps(result, sort_keys=True))
        sys.exit(1 if result['error'] is not None else 0)
    unittest.main(verbosity=2)
