"""Public-target regressions; local controls are not hosted or infrastructure proof."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

# A read-only snapshot override supports the exact same baseline RED assertion.
ROOT = Path(os.environ.get('PUBLIC_TARGET_TEST_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'scripts'))
import delivery as d

PUBLIC = 'timmypai/hermes-teams-cd-public'
PRIVATE = PUBLIC.removesuffix('-public')
HELPER = '4d92b63e419eb4a1db5ccf28b1d06779a53a55ac'
SEED = '0c9c61c5cf9d8f7e611e5e5c6b328f7ebb8b4ae1'
APP = 'eb3c70b0b520a955a014ea883c137db604ec0492'
OPERATIONS = ('ci', 'publish', 'deploy', 'health', 'rollback', 'status')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, timeout=10).strip()


def public_workflow(text):
    if not re.search(r'^          repository: ' + re.escape(PUBLIC) + r'$', text, re.M):
        raise ValueError('public helper repository required')
    if set(re.findall(r'^          ref: ([0-9a-f]{40})$', text, re.M)) != {HELPER}:
        raise ValueError('public frozen helper required')
    if 'HELPER_SHA: ' + HELPER not in text:
        raise ValueError('helper environment mismatch')


class PublicTarget(unittest.TestCase):
    def test_public_target_and_caller_context(self):
        self.assertEqual(d.CD_REPO, PUBLIC)
        good = dict(repository=PUBLIC, ref='refs/heads/main', event='workflow_dispatch',
            sha='a'*40, run_id='10', attempt='1',
            workflow_ref=PUBLIC+'/.github/workflows/deploy.yml@refs/heads/main')
        d.validate_context(good, privileged=True)
        for key, value in [('repository', PRIVATE), ('repository', 'outsider/repo'),
                ('ref', 'refs/pull/1/merge'), ('event', 'pull_request'),
                ('workflow_ref', PRIVATE+'/.github/workflows/deploy.yml@refs/heads/main')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                d.validate_context(dict(good, **{key:value}), privileged=True)
        with self.assertRaisesRegex(ValueError, 'UNBOUND'):
            d.require_activation()

    def test_public_helper_checkout_and_negative_controls(self):
        for operation in OPERATIONS:
            text = (ROOT/f'.github/workflows/reusable-{operation}.yml').read_text()
            public_workflow(text)
            for changed in [text.replace(PUBLIC, PRIVATE), text.replace(HELPER, 'a'*40),
                    text.replace(HELPER, 'main'), text.replace('repository: '+PUBLIC, 'repository: outsider/repo')]:
                with self.subTest(operation=operation), self.assertRaises(ValueError):
                    public_workflow(changed)

    def test_fresh_seed_ancestry_and_no_imported_private_history(self):
        self.assertEqual(git('rev-list', '--max-parents=0', 'HEAD'), SEED)
        self.assertEqual(set(git('ls-tree', '-r', '--name-only', SEED).splitlines()),
            {'README.md', '.gitignore', 'docs/public-source-provenance.md'})
        self.assertEqual(git('rev-parse', HELPER+'^'), SEED)
        self.assertEqual(git('merge-base', '--is-ancestor', HELPER, 'HEAD'), '')
        for sha in ('a238cea4f2b763db21411ecd656cf8cb9e36abbd',
                    '4295d21ced3a02ef2b82c60f07eb6abcbb3edab9'):
            result = subprocess.run(['git', 'cat-file', '-e', sha+'^{commit}'], cwd=ROOT,
                capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
        self.assertIn(HELPER, (ROOT/'docs/shared-delivery.md').read_text())

    def test_public_inventory_allowlist_modes_and_no_secret_material(self):
        allowed = {'.gitignore', 'README.md', '.github/actionlint.yaml',
            'config/project.schema.json', 'config/projects/sevenbot-flow-probe.json',
            'skills/team-delivery/SKILL.md', 'skills/team-delivery/references/operations.md'}
        allowed |= {'.github/workflows/'+n+'.yml' for n in
            ('cd-ci','deploy','health','publish','rollback','status',
             'reusable-ci','reusable-deploy','reusable-health','reusable-publish','reusable-rollback','reusable-status')}
        allowed |= {'docs/'+n+'.md' for n in ('acceptance','bootstrap','host-initialization',
            'onboarding','shared-delivery','trust-boundary','public-source-provenance')}
        allowed |= {'scripts/'+n for n in ('bootstrap-rootless-runner.sh','bootstrap-test-account.sh',
            'delivery.py','host-preflight.sh','readback-isolated-host.sh','status_readback.py','workflow_entry.py')}
        allowed |= {'tests/test_'+n+'.py' for n in ('cd_safety','delivery_operations','host_bootstrap',
            'revision2','transition_safety','workflow_contracts','workflow_entry','public_target')}
        self.assertEqual(set(git('ls-files').splitlines()), allowed)
        forbidden = re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|'
            r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
            r'https?://[^\s/]+:[^\s/]+@|[?&](?:X-Amz-Signature|sig|token)=', re.I)
        for path in allowed:
            obj = ROOT/path
            self.assertFalse(obj.is_symlink(), path)
            self.assertIsNone(forbidden.search(obj.read_text()), path)
        for line in git('ls-files', '--stage').splitlines():
            self.assertEqual(line.split()[0], '100644')

    def test_no_withdrawn_delivery_quotas_in_current_binding(self):
        config = d.load_json(ROOT/'config/projects/sevenbot-flow-probe.json')
        self.assertEqual(config['budget'], dict(job_seconds=600, initial=1, forward=1, rollback=1))
        schema = d.load_json(ROOT/'config/project.schema.json')
        self.assertEqual(schema['properties']['budget']['const'], config['budget'])
        for field in ('pull_requests', 'pushes', 'ci_runs', 'repairs', 'total_runs'):
            modified = dict(config, budget=dict(config['budget'], **{field:1}))
            with self.assertRaises(ValueError):
                d.validate_config(modified)

    def test_hosted_ci_runs_full_cd_and_actual_app_suite_no_privileged_pr(self):
        text = (ROOT/'.github/workflows/cd-ci.yml').read_text()
        self.assertIn("timeout 600 python3 -m unittest discover -s tests -p 'test_*.py' -v", text)
        self.assertIn('uses: ./.github/workflows/reusable-ci.yml', text)
        self.assertIn('source-sha: '+APP, text)
        self.assertIn('needs: [validate, app-tests]', text)
        self.assertNotIn('self-hosted', text)
        ci = (ROOT/'.github/workflows/reusable-ci.yml').read_text()
        self.assertIn('run: python3 shared/scripts/workflow_entry.py run ci', ci)
        self.assertNotIn('self-hosted', ci)
        self.assertEqual(d.TEST, ['python3','-m','unittest','discover','-s','tests','-p','test_flow_probe*.py','-v'])
        for operation in OPERATIONS[1:]:
            caller = (ROOT/f'.github/workflows/{operation}.yml').read_text()
            consumer = (ROOT/f'.github/workflows/reusable-{operation}.yml').read_text()
            self.assertIn('workflow_dispatch:', caller)
            self.assertNotIn('pull_request:', caller)
            self.assertIn('needs: admit', consumer)
            self.assertIn("if: needs.admit.result == 'success'", consumer)
            self.assertIn('environment: oracle-sevenbot-test', consumer)
            self.assertIn("github.event_name == 'workflow_dispatch'", consumer)

    def test_protection_evidence_missing_wrong_checks_and_qualified_control(self):
        source, head = 'a'*40, 'b'*40
        pr = dict(number=1, merged_at='now', merge_commit_sha=source,
            base={'ref':'main','repo':{'full_name':d.SOURCE_REPO}}, head={'sha':head}, user={'id':1})
        good = dict(state='APPROVED', commit_id=head, user={'id':2,'type':'User'}, author_association='COLLABORATOR')
        cases = [('good', [good]), ('missing-review', []),
            ('self-review', [dict(good, user={'id':1,'type':'User'})]),
            ('stale-review', [dict(good, commit_id='c'*40)]),
            ('unqualified', [dict(good, author_association='NONE')]),
            ('missing-check', [good]), ('wrong-app', [good]), ('failed-check', [good])]
        for mode, reviews in cases:
            def api(path):
                if path.endswith('/commits/main'): return {'sha':source}
                if path.endswith('/pulls'): return [pr]
                if path.endswith('/reviews'): return reviews
                current = path.split('/commits/')[1].split('/')[0]
                check = dict(name='ci', head_sha=current, status='completed',
                    conclusion='failure' if mode=='failed-check' else 'success',
                    app={'slug':'outsider' if mode=='wrong-app' else 'github-actions'})
                return {'total_count':0 if mode=='missing-check' else 1,
                    'check_runs':[] if mode=='missing-check' else [check]}
            with self.subTest(mode=mode), patch.object(d, 'github_get', side_effect=api), patch.object(d, 'docker') as docker:
                if mode == 'good': d.source_gate(source)
                else:
                    with self.assertRaises(ValueError): d.source_gate(source)
                docker.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
