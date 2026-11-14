"""Workflow wiring checks plus executable exact-check gate; not hosted Actions proof."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import delivery as delivery
import workflow_entry as entry


def entrypoint_contract(operation):
    """Closed, deliberately literal thin-caller grammar; not a general YAML parser.

    Comparing all nonblank lines rejects extra YAML keys/aliases/jobs as well as
    privileged selectors. actionlint separately validates the actual YAML graph.
    """
    fields = ('source-sha',) if operation == 'publish' else (
        'source-sha', 'artifact-run', 'artifact-attempt', 'revision')
    lines = [f'name: Protected {operation}', 'on:', '  workflow_dispatch:', '    inputs:']
    for field in fields:
        lines += [f'      {field}:', '        required: true',
                  '        type: choice' if field == 'revision' else '        type: string']
        if field == 'revision':
            lines += ['        options: [flow-probe-v1, flow-probe-v2]']
    lines += ['permissions:', '  contents: read']
    if operation == 'health':
        lines += ['  actions: read']
    lines += ['  checks: read', '  pull-requests: read', 'jobs:', f'  {operation}:',
        "    if: github.repository == 'timmypai/hermes-teams-cd-public' && github.ref == 'refs/heads/main' && github.run_attempt == 1 && github.event_name == 'workflow_dispatch'",
        f'    uses: ./.github/workflows/reusable-{operation}.yml', '    with:']
    lines += [f'      {field}: ${{{{ inputs.{field} }}}}' for field in fields]
    return '\n'.join(lines) + '\n'


def validate_entrypoint(operation, text):
    if [line.rstrip() for line in text.splitlines() if line.strip()] != entrypoint_contract(operation).splitlines():
        raise ValueError('closed thin-caller contract mismatch')


def validate_consumer(operation, text):
    """Source graph invariants in the unchanged reusable consumer."""
    required = [
        "github.repository == 'timmypai/hermes-teams-cd-public'",
        "github.ref == 'refs/heads/main'", "github.event_name == 'workflow_dispatch'",
        'github.run_attempt == 1',
        f"github.workflow_ref == 'timmypai/hermes-teams-cd-public/.github/workflows/{operation}.yml@refs/heads/main'",
        'HELPER_SHA: ' + HELPER, 'needs: admit', "if: needs.admit.result == 'success'",
        'environment: oracle-sevenbot-test',
        ('runs-on: ubuntu-24.04-arm' if operation == 'publish' else
         'runs-on: [self-hosted, Linux, ARM64, sevenbot-isolated]'),
        'group: oracle-sevenbot-test-sevenbot-flow-probe', 'cancel-in-progress: false',
        f'run: python3 shared/scripts/workflow_entry.py gate {operation}',
        f'run: python3 shared/scripts/workflow_entry.py run {operation}']
    if any(fragment not in text for fragment in required):
        raise ValueError('consumer admission/binding contract mismatch')
    if set(re.findall(r'          ref: ([0-9a-f]{40})', text)) != {HELPER}:
        raise ValueError('consumer helper checkout mismatch')
    if text.index(f'gate {operation}') > text.index(
            'runs-on: ubuntu-24.04-arm' if operation == 'publish' else 'runs-on: [self-hosted'):
        raise ValueError('build/host scheduled before admission')
    if 'secrets: inherit' in text or 'pull_request' + '_target:' in text:
        raise ValueError('privileged public route')

ROOT = Path(__file__).resolve().parents[1]
HELPER = '74cbd88e1f53d3832be3c4c6c5c8512a0be37249'
PINS = {'actions/checkout':'11d5960a326750d5838078e36cf38b85af677262',
    'actions/upload-artifact':'ea165f8d65b6e75b540449e92b4886f43607fa02',
    'actions/download-artifact':'d3f86a106a0bac45b974a628896c90dbdf5c8093'}


class WorkflowContracts(unittest.TestCase):
    def test_own_immutable_helper_bytes(self):
        for operation in ('ci','publish','deploy','health','rollback','status'):
            text = (ROOT/f'.github/workflows/reusable-{operation}.yml').read_text()
            self.assertIn('HELPER_SHA: '+HELPER, text)
            self.assertEqual(set(re.findall(r'          ref: ([0-9a-f]{40})', text)), {HELPER})
            self.assertNotIn('github.workflow_sha', text.split('env:')[-1])
        for path in ('scripts/delivery.py','scripts/workflow_entry.py','scripts/status_readback.py',
                     'config/project.schema.json','config/projects/sevenbot-flow-probe.json',
                     'scripts/publication_build.py','docker/Dockerfile'):
            result = subprocess.run(['git','show',f'{HELPER}:{path}'], cwd=ROOT,
                capture_output=True, timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertEqual(result.stdout,(ROOT/path).read_bytes())

    def test_pins_timeouts_credentials_and_no_public_host(self):
        for path in (ROOT/'.github/workflows').glob('*.yml'):
            text = path.read_text()
            for action, sha in re.findall(r'uses: (actions/[a-z-]+)@([^\s]+)',text):
                self.assertEqual(sha,PINS[action])
            self.assertNotIn('pull_request_target',text)
            self.assertNotIn('secrets: inherit',text)
            for minutes in re.findall(r'timeout-minutes: (\d+)',text):
                self.assertLessEqual(int(minutes),10)
            self.assertEqual(text.count('uses: actions/checkout@'), text.count('persist-credentials: false'))
            if 'self-hosted' in text:
                self.assertIn("github.repository == 'timmypai/hermes-teams-cd-public'",text)
                self.assertIn("github.event_name == 'workflow_dispatch'",text)
                self.assertIn('needs: admit',text)
                self.assertIn("if: needs.admit.result == 'success'",text)
                self.assertIn('environment: oracle-sevenbot-test',text)
                self.assertIn('cancel-in-progress: false',text)
                self.assertIn('group: oracle-sevenbot-test-sevenbot-flow-probe',text)
                self.assertIn('if-no-files-found: error',text)

    def test_private_thin_callers_same_revision_no_privilege_inputs(self):
        for operation in ('deploy','rollback','status'):
            text = (ROOT/f'.github/workflows/{operation}.yml').read_text()
            self.assertIn(f'uses: ./.github/workflows/reusable-{operation}.yml',text)
            self.assertIn("github.ref == 'refs/heads/main'",text)
            for forbidden in ('runs-on:', 'secrets:', 'runner:', 'command:', 'environment:', 'ref:'):
                self.assertNotIn(forbidden,text)

    def test_publish_health_actual_graphs(self):
        for operation in ('publish', 'health'):
            with self.subTest(operation=operation):
                caller = ROOT/f'.github/workflows/{operation}.yml'
                self.assertTrue(caller.is_file(), f'missing supported {operation} caller')
                validate_entrypoint(operation, caller.read_text())
                validate_consumer(operation, (ROOT/f'.github/workflows/reusable-{operation}.yml').read_text())

    def test_publish_health_caller_mutations_rejected(self):
        for operation in ('publish', 'health'):
            text = (ROOT/f'.github/workflows/{operation}.yml').read_text()
            mutations = [
                text.replace("'timmypai/hermes-teams-cd-public'", "'outsider/public'"),
                text.replace('refs/heads/main', 'refs/pull/1/merge'),
                text.replace('github.run_attempt == 1', 'github.run_attempt == 2'),
                text.replace('workflow_dispatch', 'pull_request'),
                text.replace(f'reusable-{operation}.yml', 'reusable-deploy.yml'),
                text.replace(f'    uses: ./.github/workflows/reusable-{operation}.yml',
                             f'    uses: outsider/public/.github/workflows/reusable-{operation}.yml@main'),
                text.replace('    with:', '    secrets: inherit\n    with:'),
                text.replace('  contents: read', '  contents: write'),
                text + '  injected:\n    runs-on: self-hosted\n    steps:\n      - run: arbitrary\n',
            ]
            for selector in ('runner', 'environment', 'command', 'secret', 'ref', 'helper'):
                mutations.append(text.replace('    inputs:',
                    f'    inputs:\n      {selector}:\n        type: string'))
                mutations.append(text + f'      {selector}: arbitrary\n')
            if operation == 'health':
                mutations += [text.replace('type: choice', 'type: string'),
                              text.replace('[flow-probe-v1, flow-probe-v2]', '[arbitrary]'),
                              text.replace('artifact-run: ${{ inputs.artifact-run }}', 'artifact-run: 999')]
            for index, changed in enumerate(mutations):
                with self.subTest(operation=operation, mutation=index):
                    self.assertNotEqual(changed, text)
                    with self.assertRaises(ValueError):
                        validate_entrypoint(operation, changed)

    def test_publish_health_consumer_mutations_rejected(self):
        for operation in ('publish', 'health'):
            text = (ROOT/f'.github/workflows/reusable-{operation}.yml').read_text()
            changes = [("'timmypai/hermes-teams-cd-public'", "'outsider/public'"),
                ('refs/heads/main', 'refs/pull/1/merge'),
                ('github.run_attempt == 1', 'github.run_attempt == 2'),
                ("github.event_name == 'workflow_dispatch'", "github.event_name == 'pull_request'"),
                (f'workflows/{operation}.yml@', 'workflows/deploy.yml@'),
                ('HELPER_SHA: ' + HELPER, 'HELPER_SHA: ' + 'a'*40),
                ('ref: ' + HELPER, 'ref: ' + 'a'*40),
                ('needs: admit', 'needs: unrelated'),
                ("if: needs.admit.result == 'success'", 'if: always()'),
                ('environment: oracle-sevenbot-test', 'environment: arbitrary'),
                ('cancel-in-progress: false', 'cancel-in-progress: true')]
            for old, new in changes:
                with self.subTest(operation=operation, mutation=old):
                    self.assertIn(old, text)
                    with self.assertRaises(ValueError):
                        validate_consumer(operation, text.replace(old, new))

    def test_publish_health_real_input_context_rejections_and_controls(self):
        # Exercise unchanged production inputs/validate_context; only Git checkout
        # identity is a fixed fixture. No source_gate/Docker/API/health is mocked
        # into acceptance: this is input validation, not live operation proof.
        for operation in ('publish', 'health'):
            good = dict(HELPER_SHA=HELPER, SOURCE_SHA='c'*40, ARTIFACT_RUN='90',
                ARTIFACT_ATTEMPT='1', REVISION='flow-probe-v1',
                GITHUB_REPOSITORY=delivery.CD_REPO, GITHUB_REF='refs/heads/main',
                GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='b'*40,
                GITHUB_RUN_ID='100', GITHUB_RUN_ATTEMPT='1',
                GITHUB_WORKFLOW_REF=f'{delivery.CD_REPO}/.github/workflows/{operation}.yml@refs/heads/main')
            for revision in ('flow-probe-v1', 'flow-probe-v2'):
                with patch.dict(os.environ, dict(good, REVISION=revision), clear=True), patch.object(delivery, 'command', side_effect=[HELPER, '']):
                    args, context = entry.inputs(operation)
                    self.assertEqual(args.source, 'c'*40)
                    self.assertEqual(args.revision, revision)
                    self.assertEqual(context['attempt'], '1')
            negatives = [('GITHUB_REPOSITORY', delivery.SOURCE_REPO),
                ('GITHUB_REF', 'refs/pull/1/merge'), ('GITHUB_RUN_ATTEMPT', '2'),
                ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'pull_request_target'),
                ('GITHUB_WORKFLOW_REF', f'{delivery.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main'),
                ('HELPER_SHA', 'a'*40), ('SOURCE_SHA', 'main'), ('REVISION', 'arbitrary')]
            if operation == 'health':
                negatives += [('ARTIFACT_RUN', '../90'), ('ARTIFACT_ATTEMPT', '0')]
            for key, value in negatives:
                with self.subTest(operation=operation, key=key, value=value), patch.dict(os.environ, dict(good, **{key:value}), clear=True), patch.object(delivery, 'command', side_effect=[HELPER, '']), patch.object(delivery, 'docker') as docker, patch.object(delivery, 'github_get') as api:
                    with self.assertRaises(ValueError):
                        entry.inputs(operation)
                    docker.assert_not_called()
                    api.assert_not_called()
            with patch.dict(os.environ, good, clear=True), patch.object(delivery, 'command', side_effect=[HELPER, '']), patch.object(sys, 'argv', ['workflow_entry.py', 'gate', operation]), patch.object(delivery, 'docker') as docker, patch.object(delivery, 'github_get') as api:
                with self.assertRaisesRegex(ValueError,
                        'unapproved publication source/revision' if operation == 'publish' else 'UNBOUND'):
                    entry.main()
                docker.assert_not_called()
                api.assert_not_called()

    def test_exact_ci_gate_real_shell_result_matrix(self):
        text = (ROOT/'.github/workflows/cd-ci.yml').read_text()
        self.assertIn('name: ci',text)
        self.assertIn('if: always()',text)
        self.assertIn('needs: [validate, app-tests]',text)
        shell = re.search(r'        run: (test "\$VALIDATION_RESULT" = success && test "\$APP_RESULT" = success)',text).group(1)
        with tempfile.TemporaryDirectory(dir=ROOT.parent/'fixtures') as tmp:
            path = Path(tmp)/'gate.sh'; path.write_text(shell+'\n')
            results = ('success','failure','cancelled','skipped','', 'success; touch sentinel')
            for value in results:
                for app in results:
                    result = subprocess.run(['bash',str(path)], cwd=tmp,
                        env=dict(os.environ,VALIDATION_RESULT=value, APP_RESULT=app),capture_output=True,timeout=10)
                    self.assertEqual(result.returncode == 0,value == app == 'success')
                    self.assertFalse((Path(tmp)/'sentinel').exists())


if __name__ == '__main__': unittest.main()
