"""Disposable command/state fixtures; never host enforcement or Oracle evidence.

Every host command is a stand-in in an owned temporary directory. The actual
Bash scripts execute as subprocesses. Unknown stand-in calls fail closed.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
STANDIN = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path(os.environ['SB_FIXTURE'])
s = json.loads(p.read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with p.with_suffix('.calls').open('a') as f:
    f.write(json.dumps([name, *args]) + '\n')
def save(): p.write_text(json.dumps(s))
def out(x): print(x); sys.exit(0)
def fail(): sys.exit(1)
if name == 'id': out(s.get('operator_uid', '0'))
if name == 'hostname': out(s.get('host', 'dot-vm-a1'))
if name == 'uname': out(s.get('arch', 'aarch64'))
if name == 'ss': out('foreign-listener' if s.get('port_busy') else '')
if name == 'readlink':
    path = args[-1]
    out('/production' if path in s.get('symlinks', []) else path)
if name == 'stat':
    path = args[-1]
    if path in s.get('symlinks', []): out('symbolic link:0:0:777')
    if path == '/home': out('directory:0:0:755')
    if path == '/home/sevenbot-deploy' and s.get('account'):
        out('directory:999:999:700' if s.get('wrong_owner') else 'directory:1000:1000:700')
    if path == '/run/user/1000' and s.get('runtime'): out('directory:1000:1000:700')
    if path == '/run/user/1000/docker.sock' and s.get('daemon'):
        out('socket:0:0:660' if s.get('wrong_socket') else 'socket:1000:1000:660')
    if path == '/home/sevenbot-deploy/.local/share/docker' and s.get('daemon'):
        out('1000:1000' if args[0] == '--format=%u:%g' else 'directory:1000:1000:700')
    if path in s.get('collisions', []): out('directory:999:999:755')
    fail()
if name == 'cat':
    path = args[-1]
    if path == '/etc/login.defs':
        if s.get('bad_policy'): out('UID_MIN 0')
        out('UID_MIN 1000\nUID_MAX 60000\nSUB_UID_MIN '+str(s.get('sub_min',100000))+'\nSUB_UID_MAX '+str(s.get('sub_max',600100000))+'\nSUB_UID_COUNT 65536\nSUB_GID_MIN 100000\nSUB_GID_MAX 600100000\nSUB_GID_COUNT 65536')
    if path in ['/etc/subuid', '/etc/subgid']:
        rows = 'other:100000:65536\n'
        if s.get('overlap'): rows += 'foreign:100001:65536\n'
        if s.get('account') and not s.get('missing_subids'): rows += 'sevenbot-deploy:165536:65536\n'
        out(rows)
    if path.endswith('/memory.max'): out('max' if s.get('daemon_only') else '1073741824')
    if path.endswith('/memory.swap.max'): out(s.get('kernel_swap', '0'))
    if path.endswith('/cpu.max'): out('100000 100000')
    if path.endswith('/pids.max'): out('256')
    fail()
if name == 'findmnt':
    if args == ['-rn', '-o', 'TARGET']: out('/\n/run\n'+s.get('submount', ''))
    field = args[args.index('-o')+1]
    runtime = args[-1].startswith('/run/user/')
    if field == 'FSTYPE': out('tmpfs' if runtime else s.get('fs', 'ext4'))
    if field == 'OPTIONS': out('rw' if s.get('capacity_only') else 'rw,usrquota')
    if field == 'TARGET': out(args[-1] if runtime else '/')
    if field == 'SIZE': out(str(s.get('runtime_size', 268435456)))
    fail()
if name == 'quotaon': out('user quota on / (/dev/root) is ' + ('off' if s.get('quota_off') else 'on'))
if name == 'repquota':
    if not s.get('quota'): out('')
    out('#1000 -- 0 0 ' + ('0' if s.get('soft_only') else '3145728') + ' 0 0 262144')
if name == 'getent':
    kind, *selector = args
    if not selector:
        row = 'root:x:0:0:root:/root:/bin/bash' if kind == 'passwd' else 'root:x:0:'
        if s.get('primary_collision'): row += '\nforeign:x:165536:165536:foreign:/foreign:/bin/false' if kind == 'passwd' else '\nforeign:x:165536:'
        out(row)
    if s.get('account') and selector[0] in ['sevenbot-deploy', '1000']:
        if kind == 'group': out('sevenbot-deploy:x:1000:')
        home = '/production' if s.get('foreign_account') else '/home/sevenbot-deploy'
        out('sevenbot-deploy:x:1000:1000:sevenbot-v1-isolated:'+home+':/usr/sbin/nologin')
    fail()
if name == 'systemctl':
    if args[0] in ['daemon-reload', 'start']:
        if args[0] == 'start': s['runtime'] = True; save()
        sys.exit(0)
    unit = args[1]
    prop = args[args.index('-p')+1]
    if prop == 'LoadState': out('not-found')
    if prop == 'ActiveState': out(s.get('active', 'inactive'))
    if prop == 'SubState': out('dead')
    if prop in ['FragmentPath', 'DropInPaths']: out(s.get(prop, ''))
    if s.get('fresh_slice'):
        if prop == 'ControlGroup': out(s.get('fresh_cgroup', ''))
        if prop in ['MemoryMax', 'MemorySwapMax', 'CPUQuotaPerSecUSec', 'TasksMax']: out(s.get('fresh_limit', 'infinity'))
    if prop == 'MemorySwapMax': out(s.get('effective_swap', '0'))
    if prop == 'MemoryMax': out('infinity' if s.get('daemon_only') else '1073741824')
    if prop == 'CPUQuotaPerSecUSec': out('1s')
    if prop == 'TasksMax': out('256')
    if prop == 'Delegate': out('no' if s.get('no_delegation') else 'cpu memory pids')
    if prop == 'ControlGroup':
        out('/user.slice/user-1000.slice'+('/user@1000.service' if unit.startswith('user@') else ''))
    fail()
if name == 'runuser':
    payload = args[args.index('PATH=/usr/local/bin:/usr/bin:/bin')+1:]
    cmd, *a = payload
    if cmd == 'systemctl':
        prop = a[a.index('-p')+1]
        if prop == 'LoadState': out('not-found')
        if prop == 'ControlGroup': out('/user.slice/user-1000.slice/user@1000.service/app.slice/docker.service')
        fail()
    if cmd == 'docker':
        if '{{json .SecurityOptions}}' in a: out('["name=seccomp","name=rootless"]' if not s.get('rootful') else '["name=seccomp"]')
        out('/production' if s.get('production_data') else '/home/sevenbot-deploy/.local/share/docker')
    if cmd == 'systemd-run':
        if 'dockerd-rootless-setuptool.sh' in a: s['daemon'] = True
        if '/usr/bin/install' in a: s['runner'] = True
        save(); sys.exit(0)
    fail()
if name == 'sha256sum':
    sys.stdin.read()
    if s.get('bad_checksum'): fail()
    out('/home/sevenbot-deploy/actions-runner/runner.tar.gz: OK')
if name in ['useradd', 'usermod', 'setquota', 'install', 'loginctl']:
    if s.get('fail_before') == name: fail()
    if name == 'useradd': s['account'] = True
    if name == 'setquota': s['quota'] = True
    if name == 'install' and '/dev/stdin' in args: sys.stdin.read()
    save()
    if s.get('fail_after') == name: fail()
    sys.exit(0)
# Prerequisites exist in this fake PATH but must not execute outside fixed payloads.
fail()
'''


class HostBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='host-bootstrap-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('id hostname uname ss readlink stat cat findmnt quotaon repquota '
                     'getent systemctl runuser sha256sum useradd usermod setquota '
                     'install loginctl systemd-run curl tar dockerd-rootless-setuptool.sh').split():
            script = self.bin / name
            script.write_text(STANDIN)
            script.chmod(0o755)
        self.state = self.root / 'state.json'

    def run_script(self, script, state, *args):
        self.state.write_text(json.dumps(state))
        calls = self.state.with_suffix('.calls')
        calls.unlink(missing_ok=True)
        env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'], SB_FIXTURE=str(self.state))
        env.pop('GH_TOKEN', None)
        env.pop('GITHUB_TOKEN', None)
        result = subprocess.run(['/bin/bash', str(SOURCE/'scripts'/script), *args],
                                capture_output=True, text=True, env=env, timeout=30)
        self.calls = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        self.after = json.loads(self.state.read_text())
        return result

    def assert_stopped(self, result, reason=None):
        self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('STOP', result.stderr)
        if reason:
            self.assertIn(reason, result.stderr)

    def assert_no_mutation(self):
        names = {call[0] for call in self.calls}
        self.assertFalse(names & {'useradd', 'usermod', 'setquota', 'install', 'loginctl', 'runuser'}, self.calls)
        self.assertFalse(any(c[0] == 'systemctl' and c[1] in ('start', 'daemon-reload') for c in self.calls))

    def component(self, function, state):
        # Fixed test-only read-only validator entrypoints. No install gate is
        # overridden and no mutation function is exposed by this harness.
        self.assertIn(function, ('sb_runtime', 'sb_daemon', 'sb_slice_fresh', 'sb_account'))
        harness = self.root / 'component.sh'
        harness.write_text('source "'+str(SOURCE/'scripts/readback-isolated-host.sh')+'"\nsb_policy\nSB_UID=1000\nSB_MOUNT=/\n'+function+'\n')
        return self.run_script(harness, state)

    def test_discovery_positive_is_read_only_and_not_installation(self):
        r = self.run_script('readback-isolated-host.sh', {}, 'discover')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('mutation=none', r.stdout)
        self.assertIn('registration=HOLD', r.stdout)
        self.assert_no_mutation()

    def test_storage_requires_active_hard_quota_not_capacity(self):
        for state in ({'capacity_only': True}, {'quota_off': True}, {'fs': 'xfs'}):
            with self.subTest(state=state):
                r = self.run_script('bootstrap-test-account.sh', state)
                self.assert_stopped(r, 'missing_existing_active_home_user_quota')
                self.assert_no_mutation()

    def test_wrong_host_arch_user_and_policy_no_mutation(self):
        for state in ({'host': 'production'}, {'arch': 'x86_64'}, {'operator_uid': '1000'}, {'bad_policy': True}):
            with self.subTest(state=state):
                self.assert_stopped(self.run_script('bootstrap-test-account.sh', state))
                self.assert_no_mutation()

    def test_account_path_symlink_port_and_subid_collisions(self):
        for state in ({'account': True}, {'collisions': ['/home/sevenbot-deploy']},
                      {'symlinks': ['/home/sevenbot-deploy']}, {'port_busy': True}, {'overlap': True}):
            with self.subTest(state=state):
                self.assert_stopped(self.run_script('bootstrap-test-account.sh', state))
                self.assert_no_mutation()

    def test_real_account_script_positive_initialization(self):
        # The previous fixture's success was unsound: UID quota is not total
        # storage isolation. Even an otherwise fresh host must stop pre-mutation.
        r = self.run_script('bootstrap-test-account.sh', {'fresh_slice': True})
        self.assert_stopped(r, 'aggregate_storage_unenforced_subids_and_job_temporary_stores')
        self.assert_no_mutation()
        self.assertNotIn('ACCOUNT_INITIALIZED', r.stdout)

    def test_partial_create_before_and_after_effect_preserved_no_replay(self):
        for command in ('useradd', 'usermod', 'setquota', 'install', 'loginctl', 'start', 'daemon-reload'):
            for key in ('fail_before', 'fail_after'):
                with self.subTest(command=command, key=key):
                    state = {'fresh_slice': True, key: command, 'foreign_sentinel': 'preserve'}
                    r = self.run_script('bootstrap-test-account.sh', state)
                    self.assert_stopped(r, 'aggregate_storage_unenforced')
                    self.assertIn('retained=yes replay=no', r.stderr)
                    self.assert_no_mutation()
                    self.assertEqual(self.after, state)

    def test_missing_subids_quota_owner_foreign_home_block_daemon(self):
        for bad in ('missing_subids', 'soft_only', 'wrong_owner', 'foreign_account'):
            with self.subTest(bad=bad):
                r = self.run_script('bootstrap-rootless-runner.sh', {'account': True, 'quota': True, 'runtime': True, bad: True})
                self.assert_stopped(r)
                self.assert_no_mutation()

    def test_delegation_aggregate_and_runtime_size_not_daemon_only(self):
        for extra in ({'no_delegation': True}, {'daemon_only': True}, {'runtime_size': 1073741825}):
            with self.subTest(extra=extra):
                r = self.run_script('bootstrap-rootless-runner.sh', dict(account=True, quota=True, runtime=True, **extra))
                self.assert_stopped(r)
                self.assert_no_mutation()

    def test_daemon_readback_socket_rootless_and_production_data(self):
        for bad in ('wrong_socket', 'rootful', 'production_data'):
            with self.subTest(bad=bad):
                r = self.run_script('readback-isolated-host.sh', dict(account=True, quota=True, runtime=True, daemon=True, **{bad: True}), 'daemon')
                self.assert_stopped(r)
                self.assertFalse(any(c[0] in ('useradd', 'usermod', 'setquota', 'install', 'loginctl') for c in self.calls))
                self.assertFalse(any(c[0] == 'runuser' and 'systemd-run' in c for c in self.calls))

    def test_rootless_positive_commands_limited_and_registration_never_started(self):
        r = self.run_script('bootstrap-rootless-runner.sh', dict(account=True, quota=True, runtime=True))
        self.assert_stopped(r, 'aggregate_storage_unenforced')
        self.assert_no_mutation()
        self.assertNotIn('DAEMON_PREPARED', r.stdout)
        # A matching daemon validator remains a real positive component control,
        # not an installer success or proof of total hard storage.
        r = self.component('sb_daemon', dict(account=True, quota=True, runtime=True, daemon=True))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('registration=HOLD', r.stdout)

    def test_unknown_resource_and_checksum_failure_preserve_state(self):
        base = dict(account=True, quota=True, runtime=True)
        r = self.run_script('bootstrap-rootless-runner.sh', dict(base, collisions=['/home/sevenbot-deploy/actions-runner']))
        self.assert_stopped(r, 'aggregate_storage_unenforced')
        self.assert_no_mutation()
        r = self.run_script('bootstrap-rootless-runner.sh', dict(base, bad_checksum=True))
        self.assert_stopped(r)
        self.assert_no_mutation()
        self.assertFalse(self.after.get('runner', False))
        self.assertFalse(self.after.get('daemon', False))

    def test_implicit_loaded_slice_positive_and_foreign_effective_state(self):
        r = self.component('sb_slice_fresh', {'fresh_slice': True})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_no_mutation()
        for extra in ({'FragmentPath': '/foreign'}, {'DropInPaths': '/foreign'},
                      {'fresh_cgroup': '/foreign'}, {'active': 'active'},
                      {'fresh_limit': '42'}, {'collisions': ['/sys/fs/cgroup/user.slice/user-1000.slice']}):
            r = self.component('sb_slice_fresh', dict(fresh_slice=True, **extra))
            self.assert_stopped(r)
            self.assert_no_mutation()

    def test_swap_effective_and_kernel_with_matching_runtime_control(self):
        base = dict(account=True, quota=True, runtime=True)
        r = self.component('sb_runtime', base)
        self.assertEqual(r.returncode, 0, r.stderr)
        for extra in ({'kernel_swap': 'max'}, {'effective_swap': 'infinity'}):
            r = self.component('sb_runtime', dict(base, **extra))
            self.assert_stopped(r)
            self.assert_no_mutation()

    def test_ancestor_symlinks_and_home_submounts(self):
        base = dict(account=True, quota=True, runtime=True, daemon=True)
        for path in ('/home', '/home/sevenbot-deploy/.local', '/run/user', '/sys/fs/cgroup/user.slice'):
            function = 'sb_daemon' if '/.local' in path else 'sb_runtime'
            if path == '/home': function = 'sb_account'
            r = self.component(function, dict(base, symlinks=[path]))
            self.assert_stopped(r)
        for path in ('/home/sevenbot-deploy', '/home/sevenbot-deploy/.local/share/docker'):
            r = self.run_script('readback-isolated-host.sh', dict(base, submount=path), 'account')
            self.assert_stopped(r, 'home_submount')
            self.assert_no_mutation()

    def test_subordinate_primary_collision_and_policy_bounds(self):
        for extra in ({'primary_collision': True}, {'sub_min': 1}, {'sub_min': 200000, 'sub_max': 100000}):
            r = self.run_script('readback-isolated-host.sh', dict(account=True, quota=True, **extra), 'account')
            self.assert_stopped(r)
            self.assert_no_mutation()

    def test_component_account_positive_not_overall_storage_qualification(self):
        r = self.component('sb_account', dict(account=True, quota=True))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_no_mutation()
        self.assertNotIn('total_max_bytes', r.stdout)

    def test_same_assertion_baseline_storage_red(self):
        r = self.run_script('bootstrap-rootless-runner.sh', dict(account=True, quota=True, runtime=True))
        self.assert_stopped(r, 'aggregate_storage_unenforced_subids_and_job_temporary_stores')
        self.assert_no_mutation()

    def test_no_magic_environment_qualification_or_downstream_replay(self):
        for key in ('fail_before', 'fail_after'):
            for command in ('runuser', 'curl', 'tar', 'sha256sum', 'dockerd-rootless-setuptool.sh'):
                state = dict(account=True, quota=True, runtime=True, foreign_sentinel='preserve', **{key: command})
                r = self.run_script('bootstrap-rootless-runner.sh', state)
                self.assert_stopped(r, 'aggregate_storage_unenforced')
                self.assert_no_mutation()
                self.assertEqual(self.after, state)

    def test_closed_arguments_and_stage_controls(self):
        for script in ('bootstrap-test-account.sh', 'bootstrap-rootless-runner.sh'):
            r = self.run_script(script, {}, '/production')
            self.assert_stopped(r)
            self.assertEqual(self.calls, [])
        self.assert_stopped(self.run_script('readback-isolated-host.sh', {}, 'arbitrary-shell'))
        self.assertEqual(self.calls, [])

if __name__ == '__main__':
    unittest.main()
