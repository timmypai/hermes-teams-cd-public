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


if __name__ == '__main__':
    unittest.main()
