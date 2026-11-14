"""Fixed public hosted ARM64 publisher. Never an Oracle/rootless host adapter.

Invoked only by workflow_entry after admission; no CLI, commands or selectors
from dispatch inputs. Local tests replace the command boundary, never run Docker.
"""
import json
import os
from pathlib import Path
import time
import delivery as d

APP_SHA = 'eb3c70b0b520a955a014ea883c137db604ec0492'
BASE = 'python@sha256:aed314f1f0c7e988b7aee5d889414ec977430bad37770966c52aff5366a13a06'
SERVER_HASH = 'f5385d64984bdf0455a2bb72f06a970499062f98a8dd7896d580d09027d6928e'
RECIPE = ('FROM ' + BASE + '\nWORKDIR /app\n'
          'COPY apps/sevenbot-flow-probe/server.py /app/server.py\n'
          'USER 65532:65532\nENTRYPOINT ["python3", "-I", "-B", "/app/server.py"]\n')
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def admit(args, c):
    d.validate_context(c, privileged=True)
    d.need(c['workflow_ref'] == f'{d.CD_REPO}/.github/workflows/publish.yml@refs/heads/main'
           and c['attempt'] == '1', 'untrusted publication workflow/attempt')
    d.need(args.source == APP_SHA and args.revision == 'flow-probe-v1', 'unapproved publication source/revision')
    repo = d.github_get(f'/repos/{d.CD_REPO}')
    d.need(repo.get('id') == 1457341852 and repo.get('full_name') == d.CD_REPO and
           repo.get('private') is False and repo.get('default_branch') == 'main', 'public standard-runner eligibility missing')
    branch = d.github_get(f'/repos/{d.CD_REPO}/branches/main')
    d.need(branch.get('protected') is True and branch.get('commit', {}).get('sha') == c['sha'],
           'publication is not current protected main')
    pulls = d.github_get(f'/repos/{d.CD_REPO}/commits/{c["sha"]}/pulls')
    qualifying = [p for p in pulls if p.get('merged_at') and p.get('merge_commit_sha') == c['sha'] and
                  p.get('base', {}).get('ref') == 'main' and
                  p.get('base', {}).get('repo', {}).get('full_name') == d.CD_REPO]
    d.need(len(pulls) < 30 and len(qualifying) == 1, 'unique reviewed publication merge required')
    pr = qualifying[0]
    reviews = d.github_get(f'/repos/{d.CD_REPO}/pulls/{pr["number"]}/reviews')
    d.need(len(reviews) < 30, 'publication review inventory truncated')
    latest = {}
    for review in reviews:
        if review.get('state') in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[review['user']['id']] = review
    d.need(any(r['state'] == 'APPROVED' and r.get('commit_id') == pr['head']['sha'] and
               r['user']['id'] != pr['user']['id'] and r['user'].get('type') == 'User' and
               r.get('author_association') in ('OWNER', 'MEMBER', 'COLLABORATOR')
               for r in latest.values()), 'independent publication approval missing')
    for head in {c['sha'], pr['head']['sha']}:
        d.need(bool(d.SHA.fullmatch(head)), 'invalid publication head')
        checks = d.github_get(f'/repos/{d.CD_REPO}/commits/{head}/check-runs')
        d.need(checks.get('total_count') == len(checks.get('check_runs', [])), 'publication checks truncated')
        named = [x for x in checks.get('check_runs', []) if x.get('name') == 'ci']
        d.need(bool(named) and all(x.get('head_sha') == head and x.get('status') == 'completed' and
               x.get('conclusion') == 'success' and x.get('app', {}).get('id') == 15368 and
               x.get('app', {}).get('slug') == 'github-actions' for x in named), 'publication exact head CI missing')


def runner():
    d.need(os.environ.get('GITHUB_ACTIONS') == 'true' and
           os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and
           os.environ.get('RUNNER_OS') == 'Linux' and os.environ.get('RUNNER_ARCH') == 'ARM64' and
           os.environ.get('ImageOS') == 'ubuntu24' and os.environ.get('USER') == 'runner' and
           os.getuid() != 0, 'standard hosted ARM64 runner required')
    d.need(not any(os.environ.get(k) for k in
           ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')),
           'alternate daemon rejected')
    d.need(d.command(['uname', '-m']) == 'aarch64', 'native ARM64 execution required')


def docker(argv):
    # Fixed local standard-hosted socket; never inherited contexts/remote hosts.
    return d.command(['docker', '--host', 'unix:///var/run/docker.sock', *argv])


def recipe():
    path = d.safe_file(d.helper_root(), 'docker/Dockerfile')
    lines = '\n'.join(line.strip() for line in path.read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith('#')) + '\n'
    d.need(lines == RECIPE, 'unqualified publication Dockerfile')
    return path


def validate_archive(directory, p, args, c):
    d.validate_provenance(p, source=args.source, run=c['run_id'], attempt=c['attempt'], shared=args.shared)
    d.need(p['workflow_sha'] == c['sha'], 'archive workflow substitution')
    archive = d.safe_file(directory, 'image.tar')
    d.need(0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES, 'archive size outside publication allowance')
    d.need(d.sha256(archive) == p['archive_sha256'], 'publication archive digest mismatch')


def smoke(image, source, c):
    name = 'sevenbot-image-' + c['run_id'] + '-' + c['attempt']
    d.need(not docker(['container', 'ls', '-aq', '--filter', 'name=^/' + name + '$']), 'existing smoke candidate')
    candidate = None
    try:
        # run may fail after taking effect; cleanup reconciles by exact owned name.
        candidate = docker(['run', '--detach', '--name', name,
            '--label', 'sevenbot.run=' + c['run_id'], '--label', 'sevenbot.attempt=' + c['attempt'],
            '--publish', '127.0.0.1:18080:8080', '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64',
            '--read-only', '--user', '65532:65532', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
            '--network', 'bridge', '--restart', 'no', image,
            '--host', '0.0.0.0', '--port', '8080', '--source-sha', source,
            '--response-revision', 'flow-probe-v1'])
        d.need(bool(d.HASH.fullmatch(candidate)), 'invalid smoke container identity')
        observed = json.loads(docker(['container', 'inspect', '--format',
            '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}}}', name]))
        d.need(observed == dict(id=candidate, image=image, running=True), 'smoke candidate mismatch')
        version = None
        for attempt in range(10):
            try:
                version = d.http_json('/version')
                break
            except (OSError, ValueError):
                if attempt == 9:
                    raise ValueError('hosted smoke startup failed') from None
                time.sleep(0.5)
        health, function = d.http_json('/healthz'), d.http_json('/')
        d.need(version == dict(schema_version=1, source_sha=source, response_revision='flow-probe-v1'),
               'hosted smoke version mismatch')
        d.need(type(health) is dict and health.get('healthy') is True and
               type(function) is dict and function.get('message') == 'sevenbot-flow-probe-v1',
               'hosted smoke function unhealthy')
        return dict(version=version, healthy=True, message=function['message'], platform='linux/arm64')
    finally:
        remaining = docker(['container', 'ls', '-aq', '--filter', 'name=^/' + name + '$'])
        if remaining:
            owned = json.loads(docker(['container', 'inspect', '--format',
                '{"id":{{json .Id}},"image":{{json .Image}},"run":{{json (index .Config.Labels "sevenbot.run")}},"attempt":{{json (index .Config.Labels "sevenbot.attempt")}}}', name]))
            d.need(bool(d.HASH.fullmatch(remaining)) and owned == dict(id=remaining, image=image,
                   run=c['run_id'], attempt=c['attempt']) and (candidate is None or candidate == remaining),
                   'STOP: smoke cleanup ownership conflict')
            docker(['container', 'rm', '--force', remaining])
            d.need(not docker(['container', 'ls', '-aq', '--filter', 'name=^/' + name + '$']),
                   'STOP: smoke cleanup failed')


def publish(args, c):
    # Recheck at the real mutation boundary, not just in the admission job.
    admit(args, c)
    d.source_gate(args.source)
    runner()
    app = Path(args.app).resolve(strict=True)
    d.need(d.command(['git', 'rev-parse', 'HEAD'], cwd=app) == args.source, 'checkout head mismatch')
    d.need(not d.command(['git', 'status', '--porcelain'], cwd=app), 'dirty application checkout')
    server = d.safe_file(app, 'apps/sevenbot-flow-probe/server.py')
    d.need(d.sha256(server) == SERVER_HASH, 'application byte substitution')
    dockerfile = recipe()
    evidence = Path(args.evidence)
    d.need(not evidence.exists() and not evidence.is_symlink(), 'existing publication output')
    daemon = json.loads(docker(['info', '--format', '{"os":{{json .OSType}},"arch":{{json .Architecture}}}']))
    d.need(daemon.get('os') == 'linux' and daemon.get('arch') == 'aarch64', 'non-native hosted daemon')
    # Only this previously-qualified immutable official base may be fetched.
    docker(['pull', '--platform', 'linux/arm64', BASE])
    base = json.loads(docker(['image', 'inspect', '--format',
        '{"os":{{json .Os}},"arch":{{json .Architecture}},"digests":{{json .RepoDigests}}}', BASE]))
    d.need(base.get('os') == 'linux' and base.get('arch') == 'arm64' and
           any(x.endswith('@sha256:' + BASE.split('@sha256:')[1]) for x in base.get('digests', [])),
           'qualified native base mismatch')
    tag = d.SERVICE + ':' + args.source
    d.need(tag == 'sevenbot-flow-probe:' + APP_SHA, 'publication namespace mismatch')
    docker(['build', '--platform', 'linux/arm64', '--pull=false', '--network=none',
            '-f', str(dockerfile), '-t', tag, str(app)])
    built = json.loads(docker(['image', 'inspect', '--format',
        '{"id":{{json .Id}},"os":{{json .Os}},"arch":{{json .Architecture}},"user":{{json .Config.User}}}', tag]))
    image = built.get('id', '')
    d.need(bool(d.IMAGE.fullmatch(image)) and built == dict(id=image, os='linux', arch='arm64', user='65532:65532'),
           'built native image mismatch')
    result = smoke(image, args.source, c)
    evidence.mkdir(mode=0o700)
    archive = evidence / 'image.tar'
    docker(['image', 'save', '-o', str(archive), image])
    p = d.make_provenance(args.source, d.sha256(archive), image, c['run_id'], c['attempt'], args.shared, c['sha'])
    validate_archive(evidence, p, args, c)
    # Keep consumer schema1 unchanged. Native/base/smoke evidence is a separate receipt.
    d.write_receipt(evidence, 'native.json', dict(source_sha=args.source, helper_sha=args.shared,
        workflow_sha=c['sha'], run_id=c['run_id'], run_attempt=c['attempt'], base=BASE,
        image_id=image, archive_sha256=p['archive_sha256'], archive_bytes=archive.stat().st_size,
        uname='aarch64', runner='ubuntu-24.04-arm', smoke=result))
    d.write_receipt(evidence, 'provenance.json', p)
