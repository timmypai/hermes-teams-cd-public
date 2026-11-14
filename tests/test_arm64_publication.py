"""Offline Dockerfile/build-context regression; NEVER native image acceptance.

No Docker executable is invoked. The existing host build wrapper remains intact.
The official immutable base was independently qualified from manifest/config bytes.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import delivery as d

BASE = 'python@sha256:aed314f1f0c7e988b7aee5d889414ec977430bad37770966c52aff5366a13a06'


class DockerfileContract(unittest.TestCase):
    def recipe(self):
        path = ROOT / 'docker/Dockerfile'
        self.assertTrue(path.is_file(), 'missing real docker/Dockerfile at accepted source')
        self.assertFalse(path.is_symlink())
        return [line.strip() for line in path.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#')]

    def test_official_qualified_immutable_arm64_base(self):
        lines = self.recipe()
        self.assertEqual(lines[0], 'FROM ' + BASE)
        self.assertEqual(sum(line.startswith('FROM ') for line in lines), 1)
        self.assertRegex(BASE, r'^python@sha256:[0-9a-f]{64}$')

    def test_actual_application_copy_not_stub_or_context_wildcard(self):
        copies = [line for line in self.recipe() if line.startswith('COPY ')]
        self.assertEqual(copies, ['COPY apps/sevenbot-flow-probe/server.py /app/server.py'])

    def test_no_build_shell_network_install_or_mutable_inputs(self):
        lines = self.recipe()
        self.assertEqual({line.split()[0] for line in lines},
                         {'FROM', 'WORKDIR', 'COPY', 'USER', 'ENTRYPOINT'})
        self.assertFalse(any('$' in line or 'https://' in line for line in lines))

    def test_nonroot_exec_entrypoint_retains_runtime_version_arguments(self):
        lines = self.recipe()
        self.assertIn('USER 65532:65532', lines)
        self.assertIn('WORKDIR /app', lines)
        entry = [line for line in lines if line.startswith('ENTRYPOINT ')]
        self.assertEqual(len(entry), 1)
        self.assertEqual(json.loads(entry[0].removeprefix('ENTRYPOINT ')),
                         ['python3', '-I', '-B', '/app/server.py'])
        # No default fabricated source SHA; install_container supplies the exact identity.
        self.assertFalse(any(re.search(r'[0-9a-f]{40}', line) for line in lines[1:]))


class ExistingBuildConsumer(unittest.TestCase):
    def test_real_dockerfile_reaches_fixed_offline_build_context(self):
        self.assertTrue((ROOT / 'docker/Dockerfile').is_file(),
                        'missing real docker/Dockerfile prevents intended image build')
        source = 'a' * 40
        image = 'sha256:' + 'b' * 64
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            app = Path(tmp) / 'app'
            (app / 'apps/sevenbot-flow-probe').mkdir(parents=True)
            # Deliberately not an image or application acceptance fixture.
            (app / 'apps/sevenbot-flow-probe/server.py').write_text('# offline build-context fixture\n')
            evidence = Path(tmp) / 'evidence'
            evidence.mkdir()
            args = argparse.Namespace(source=source, app=str(app), evidence=str(evidence), shared='c' * 40)
            calls = []
            def command(argv, **kwargs):
                if argv == ['git', 'rev-parse', 'HEAD']:
                    self.assertEqual(kwargs['cwd'], app)
                    return source
                if argv == ['git', 'status', '--porcelain']:
                    return ''
                self.assertEqual(argv, ['uname', '-m'])
                return 'aarch64'
            def docker(argv):
                calls.append(argv)
                if argv[:2] == ['image', 'inspect']:
                    return image
                if argv[:2] == ['image', 'save']:
                    Path(argv[3]).write_bytes(b'OFFLINE FIXTURE NOT AN IMAGE')
                return ''
            with patch.object(d, 'source_gate') as gate, patch.object(d, 'helper_root', return_value=ROOT), \
                    patch.object(d, 'command', side_effect=command), patch.object(d, 'docker', side_effect=docker):
                d.publish(args, {'run_id': '100', 'attempt': '1', 'sha': 'd' * 40})
            gate.assert_called_once_with(source)
            self.assertEqual(calls[0], ['build', '--platform', 'linux/arm64', '--pull=false', '--network=none',
                             '-f', str(ROOT / 'docker/Dockerfile'), '-t', 'sevenbot-flow-probe:' + source, str(app)])
            self.assertEqual(calls[-1], ['image', 'save', '-o', str(evidence / 'image.tar'), image])
            receipt = json.loads((evidence / 'provenance.json').read_text())
            self.assertEqual(receipt['archive_sha256'], d.sha256(evidence / 'image.tar'))
            self.assertEqual(receipt['image_id'], image)

    def test_missing_or_unqualified_recipe_never_builds(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            root = Path(tmp)
            (root / 'apps/sevenbot-flow-probe').mkdir(parents=True)
            (root / 'apps/sevenbot-flow-probe/server.py').write_text('# fixture\n')
            args = argparse.Namespace(source='a' * 40, app=str(root))
            with patch.object(d, 'source_gate'), patch.object(d, 'helper_root', return_value=root), \
                    patch.object(d, 'command', side_effect=['a' * 40, '']), patch.object(d, 'docker') as docker:
                with self.assertRaises(ValueError):
                    d.publish(args, {})
                docker.assert_not_called()
            (root / 'docker').mkdir()
            (root / 'docker/Dockerfile').write_text('FROM python:latest\n')
            with patch.object(d, 'source_gate'), patch.object(d, 'helper_root', return_value=root), \
                    patch.object(d, 'command', side_effect=['a' * 40, '']), patch.object(d, 'docker') as docker:
                with self.assertRaisesRegex(ValueError, 'unqualified Dockerfile'):
                    d.publish(args, {})
                docker.assert_not_called()

    def test_source_rejection_precedes_build_and_output(self):
        args = argparse.Namespace(source='a' * 40)
        with patch.object(d, 'source_gate', side_effect=ValueError('source rejected')), \
                patch.object(d, 'docker') as docker, patch.object(d, 'write_receipt') as receipt:
            with self.assertRaisesRegex(ValueError, 'source rejected'):
                d.publish(args, {})
            docker.assert_not_called()
            receipt.assert_not_called()


class HostedRouteRegression(unittest.TestCase):
    def test_publisher_is_native_standard_hosted_not_oracle_runner(self):
        text = (ROOT / '.github/workflows/reusable-publish.yml').read_text()
        self.assertIn('runs-on: ubuntu-24.04-arm', text)
        self.assertNotIn('self-hosted', text)
        self.assertIn('environment: oracle-sevenbot-test', text)

    def test_publish_gate_independent_of_host_activation(self):
        import os
        import workflow_entry as entry
        env = dict(HELPER_SHA='b' * 40, SOURCE_SHA='eb3c70b0b520a955a014ea883c137db604ec0492',
            GITHUB_REPOSITORY=d.CD_REPO, GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='a' * 40,
            GITHUB_RUN_ID='100', GITHUB_RUN_ATTEMPT='1',
            GITHUB_WORKFLOW_REF=f'{d.CD_REPO}/.github/workflows/publish.yml@refs/heads/main')
        # Fixed approved-main fixture, not live platform/protection evidence.
        def api(path):
            if path == f'/repos/{d.CD_REPO}':
                return dict(id=1457341852, full_name=d.CD_REPO, private=False, default_branch='main')
            if path.endswith('/branches/main'):
                return dict(protected=True, commit={'sha': 'a' * 40})
            if path.endswith('/commits/main'):
                return {'sha': 'a' * 40}
            if path.endswith('/pulls'):
                return [dict(number=2, merged_at='now', merge_commit_sha='a' * 40,
                    base={'ref':'main','repo':{'full_name':d.CD_REPO}},
                    head={'sha':'d'*40}, user={'id':1})]
            if path.endswith('/reviews'):
                return [dict(state='APPROVED', commit_id='d'*40,
                    user={'id':2,'type':'User'}, author_association='COLLABORATOR')]
            if path.endswith('/check-runs'):
                head = path.split('/commits/')[1].split('/')[0]
                return dict(total_count=1, check_runs=[dict(name='ci', head_sha=head,
                    status='completed', conclusion='success', app={'slug':'github-actions','id':15368})])
            raise AssertionError('unexpected fixed API path ' + path)
        error = None
        with patch.dict(os.environ, env, clear=True), patch.object(d, 'command', side_effect=['b'*40, '']), \
                patch.object(d, 'github_get', side_effect=api), patch.object(d, 'source_gate') as source, \
                patch.object(d, 'require_activation', side_effect=ValueError('HOST_ACTIVATION_SENTINEL')), \
                patch.object(d, 'docker') as host_docker, patch.object(sys, 'argv', ['entry', 'gate', 'publish']):
            try:
                entry.main()
            except ValueError as exc:
                error = str(exc)
            self.assertIsNone(error, 'publication must not depend on host ACTIVATION')
            source.assert_called_once_with(env['SOURCE_SHA'], historical=False)
            host_docker.assert_not_called()

    def test_host_operations_stay_unbound(self):
        self.assertIsNone(d.ACTIVATION)
        with self.assertRaisesRegex(ValueError, 'UNBOUND'):
            d.require_activation()


class HostedEntryFixtures(unittest.TestCase):
    """Real CLI entry with fixed external-boundary fixtures, never Docker acceptance."""
    def probe(self, case):
        import os
        import subprocess
        with tempfile.TemporaryDirectory(dir=ROOT.parent / 'fixtures') as tmp:
            root = Path(tmp)
            env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                '--entry-fixture', case], cwd=root, env=env, capture_output=True, text=True, timeout=20)
            if case == 'good' and result.returncode == 0:
                import publication_build as pb
                evidence = root / 'evidence'
                p = json.loads((evidence / 'provenance.json').read_text())
                native = json.loads((evidence / 'native.json').read_text())
                d.validate_provenance(p, source=pb.APP_SHA, run='100', attempt='1', shared='b'*40)
                self.assertEqual(p['archive_sha256'], d.sha256(evidence / 'image.tar'))
                for key in ('source_sha', 'workflow_sha', 'image_id', 'archive_sha256'):
                    self.assertEqual(native[key], p[key])
                self.assertEqual(native['helper_sha'], 'b'*40)
                self.assertEqual(native['base'], pb.BASE)
                self.assertEqual(native['uname'], 'aarch64')
                self.assertEqual(native['runner'], 'ubuntu-24.04-arm')
                self.assertEqual(native['archive_bytes'], (evidence / 'image.tar').stat().st_size)
                self.assertEqual(native['smoke'], dict(version=dict(schema_version=1,
                    source_sha=pb.APP_SHA, response_revision='flow-probe-v1'), healthy=True,
                    message='sevenbot-flow-probe-v1', platform='linux/arm64'))
            return result, (root / 'build-sentinel').exists(), (root / 'evidence/provenance.json').exists()

    def test_control_executes_new_helper_and_preserves_schema1(self):
        result, built, output = self.probe('good')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(built)
        self.assertTrue(output)

    def test_rejections_nonzero_before_build_or_publication(self):
        for case in ('repo', 'ref', 'workflow', 'source', 'attempt', 'helper', 'dirty-helper',
                'platform', 'emulated', 'daemon', 'base-recipe', 'namespace', 'app-substitution',
                'app-head', 'app-dirty', 'private', 'unprotected', 'stale-main', 'review',
                'self-review', 'check', 'wrong-check-app', 'source-review', 'source-check',
                'source-main', 'base-platform', 'alternate-daemon', 'self-hosted-runner'):
            with self.subTest(case=case):
                result, built, output = self.probe(case)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('workflow stopped:', result.stderr)
                self.assertFalse(built, result.stderr)
                self.assertFalse(output)

    def test_build_verification_and_archive_failure_never_publish_success(self):
        # These errors arise AFTER creation, so require no published success,
        # not the logically impossible claim that no prior build occurred.
        for case in ('built-platform', 'smoke-version', 'smoke-health', 'smoke-function',
                     'archive-digest', 'archive-workflow', 'archive-size', 'cleanup-conflict',
                     'cleanup-failure', 'create-after-effect'):
            with self.subTest(case=case):
                result, built, output = self.probe(case)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('workflow stopped:', result.stderr)
                self.assertTrue(built)
                self.assertFalse(output)


def entry_fixture(case):
    """Private disposable fixture process; production entry catches real failures."""
    import os
    import runpy
    import publication_build as pb
    helper, workflow, source, head = 'b'*40, 'a'*40, pb.APP_SHA, 'd'*40
    image, container = 'sha256:' + 'e'*64, 'f'*64
    root = Path.cwd()
    (root / 'app/apps/sevenbot-flow-probe').mkdir(parents=True)
    server = root / 'app/apps/sevenbot-flow-probe/server.py'
    server.write_text('# OFFLINE FIXTURE NOT APPLICATION ACCEPTANCE\n')
    env = dict(HELPER_SHA=helper, SOURCE_SHA=source, GITHUB_ACTIONS='true',
        GITHUB_REPOSITORY=d.CD_REPO, GITHUB_REF='refs/heads/main',
        GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA=workflow,
        GITHUB_RUN_ID='100', GITHUB_RUN_ATTEMPT='1', USER='runner',
        GITHUB_WORKFLOW_REF=f'{d.CD_REPO}/.github/workflows/publish.yml@refs/heads/main',
        RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux', RUNNER_ARCH='ARM64', ImageOS='ubuntu24')
    mutations = dict(repo=('GITHUB_REPOSITORY','evil/repo'), ref=('GITHUB_REF','refs/pull/1/merge'),
        workflow=('GITHUB_WORKFLOW_REF',f'{d.CD_REPO}/.github/workflows/deploy.yml@refs/heads/main'),
        source=('SOURCE_SHA','c'*40), attempt=('GITHUB_RUN_ATTEMPT','2'), helper=('HELPER_SHA','c'*40),
        platform=('RUNNER_ARCH','X64'), alternate_daemon=('DOCKER_HOST','tcp://127.0.0.1:2375'))
    if case == 'alternate-daemon': env['DOCKER_HOST'] = 'tcp://127.0.0.1:2375'
    if case == 'self-hosted-runner': env['RUNNER_ENVIRONMENT'] = 'self-hosted'
    if case in mutations:
        key, value = mutations[case]
        env[key] = value
    present = False
    def api(path):
        repo = d.CD_REPO if path.startswith('/repos/' + d.CD_REPO) else d.SOURCE_REPO
        current = workflow if repo == d.CD_REPO else source
        if path == '/repos/' + d.CD_REPO:
            return dict(id=1457341852, full_name=d.CD_REPO, private=case == 'private', default_branch='main')
        if path.endswith('/branches/main'):
            return dict(protected=case != 'unprotected', commit={'sha':'c'*40 if case=='stale-main' else workflow})
        if path.endswith('/commits/main'):
            return {'sha': 'c'*40 if case == 'source-main' and repo == d.SOURCE_REPO else current}
        if path.endswith('/pulls'):
            return [dict(number=2, merged_at='now', merge_commit_sha=current,
                base={'ref':'main','repo':{'full_name':repo}}, head={'sha':head}, user={'id':1})]
        if path.endswith('/reviews'):
            if case == ('review' if repo == d.CD_REPO else 'source-review'): return []
            return [dict(state='APPROVED', commit_id=head, user={'id':1 if case=='self-review' else 2,'type':'User'},
                author_association='COLLABORATOR')]
        if path.endswith('/check-runs'):
            checked = path.split('/commits/')[1].split('/')[0]
            bad = case == ('check' if repo == d.CD_REPO else 'source-check')
            return dict(total_count=1, check_runs=[dict(name='ci', head_sha=checked, status='completed',
                conclusion='failure' if bad else 'success', app={'slug':'github-actions',
                'id':0 if case=='wrong-check-app' else 15368})])
        raise AssertionError('unknown fixture API path')
    def command(argv, cwd=None):
        nonlocal present
        if argv == ['git','rev-parse','HEAD']:
            return ('c'*40 if case=='app-head' else source) if cwd == Path('app').resolve() else helper
        if argv == ['git','status','--porcelain']:
            return ' M server.py' if case=='app-dirty' else ''
        if argv == ['git','status','--porcelain','--untracked-files=no']:
            return ' M script' if case=='dirty-helper' else ''
        if argv == ['uname','-m']: return 'x86_64' if case=='emulated' else 'aarch64'
        if argv[:3] != ['docker','--host','unix:///var/run/docker.sock']:
            raise AssertionError('unqualified fixture command')
        args = argv[3:]
        if args[0] == 'info': return json.dumps(dict(os='linux',arch='x86_64' if case=='daemon' else 'aarch64'))
        if args[0] == 'pull': return ''
        if args[0] == 'build':
            (root/'build-sentinel').write_text('MOCK BUILD ONLY\n')
            return ''
        if args[:2] == ['image','inspect']:
            if args[-1] == pb.BASE:
                return json.dumps(dict(os='linux',arch='amd64' if case=='base-platform' else 'arm64',digests=['python@' + pb.BASE.split('@')[1]]))
            return json.dumps(dict(id=image,os='linux',arch='amd64' if case=='built-platform' else 'arm64',user='65532:65532'))
        if args[:2] == ['image','save']:
            Path(args[3]).write_bytes(b'OFFLINE FIXTURE NOT AN IMAGE')
            return ''
        if args[0] == 'run':
            present = True
            if case == 'create-after-effect': raise ValueError('fixture create failed after effect')
            return container
        if args[:2] == ['container','ls']: return container if present else ''
        if args[:2] == ['container','inspect']:
            if 'running' in args[3]: return json.dumps(dict(id=container,image=image,running=True))
            return json.dumps(dict(id=container,image=image,run='999' if case=='cleanup-conflict' else '100',attempt='1'))
        if args[:2] == ['container','rm']:
            if case == 'cleanup-failure': raise ValueError('fixture cleanup failure')
            present = False
            return ''
        raise AssertionError('unexpected fixture docker command')
    def http(path):
        if path == '/version': return dict(schema_version=1, source_sha='c'*40 if case=='smoke-version' else source,
            response_revision='flow-probe-v1')
        if path == '/healthz': return {'healthy':case != 'smoke-health'}
        if path == '/': return {'message':'wrong' if case=='smoke-function' else 'sevenbot-flow-probe-v1'}
        raise AssertionError('unexpected HTTP path')
    real_hash = d.sha256
    reads = 0
    def hash_file(path):
        nonlocal reads
        if Path(path) == server: return '0'*64 if case=='app-substitution' else pb.SERVER_HASH
        reads += 1
        return '0'*64 if case=='archive-digest' and reads==1 else real_hash(path)
    original_make = d.make_provenance
    def make(*args):
        p = original_make(*args)
        if case == 'archive-workflow': p['workflow_sha'] = 'c'*40
        return p
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        for obj, attr, value in ((d,'github_get',api),(d,'command',command),(d,'http_json',http),
                (d,'sha256',hash_file),(d,'make_provenance',make)):
            stack.enter_context(patch.object(obj,attr,side_effect=value))
        stack.enter_context(patch.object(pb.os,'getuid',return_value=1001))
        if case == 'namespace': stack.enter_context(patch.object(d,'SERVICE','wrong-namespace'))
        if case == 'archive-size': stack.enter_context(patch.object(pb,'MAX_ARCHIVE_BYTES',1))
        if case == 'base-recipe':
            bad = root/'bad'
            (bad/'docker').mkdir(parents=True)
            (bad/'docker/Dockerfile').write_text('FROM python:latest\n')
            # inputs still validates the real helper/config; recipe sees this substituted file.
            original_safe = d.safe_file
            stack.enter_context(patch.object(d,'safe_file',side_effect=lambda r,p:
                bad/'docker/Dockerfile' if p=='docker/Dockerfile' else original_safe(r,p)))
        sys.argv = ['workflow_entry.py','run','publish']
        runpy.run_path(str(ROOT/'scripts/workflow_entry.py'),run_name='__main__')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--entry-fixture':
        entry_fixture(sys.argv[2])
    else:
        unittest.main()
