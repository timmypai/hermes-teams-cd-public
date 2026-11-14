"""Bounded delivery helpers. No shell interpreter, registry discovery, or Kanban API.

Bindings are reviewed code, never caller inputs. Activation is intentionally absent:
feature/cost/isolation/identity qualification must be reviewed before a later binding.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.request

CD_REPO = 'timmypai/hermes-teams-cd-public'
SOURCE_REPO = 'timmypai/hermes-teams'
SERVICE = 'sevenbot-flow-probe'
ENVIRONMENT = 'oracle-sevenbot-test'
# No runtime parameter, environment variable, or project config can activate CD.
ACTIVATION: dict | None = None
SHA = re.compile(r'[0-9a-f]{40}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
POSITIVE = re.compile(r'[1-9][0-9]{0,19}\Z')
TEST = ['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_flow_probe*.py', '-v']


def helper_root():
    return Path(__file__).resolve().parents[1]


def need(condition, message):
    if not condition:
        raise ValueError(message)


def exact_keys(value, keys):
    need(type(value) is dict and set(value) == set(keys), 'unknown or missing fields')


def pairs(items):
    result = {}
    for key, value in items:
        need(key not in result, 'duplicate field')
        result[key] = value
    return result


def load_json(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536, 'unsafe JSON file')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def safe_file(root, raw):
    need(type(raw) is str and re.fullmatch(r'[A-Za-z0-9_./*-]+', raw) is not None,
         'unsafe path characters')
    need(not raw.startswith('/') and all(x not in ('', '.', '..') for x in raw.split('/')), 'unsafe path segments')
    root = Path(root).resolve(strict=True)
    result = root
    for part in PurePosixPath(raw).parts:
        result = result / part
        need(not result.is_symlink(), 'symlink rejected')
    need(result.is_file(), 'missing regular file')
    need(result.resolve().is_relative_to(root), 'path escape')
    return result


def validate_config(c):
    expected = load_json(helper_root() / 'config/projects/sevenbot-flow-probe.json')
    exact_keys(c, expected)
    # JSON bool equals 1 in Python: compare canonical bytes as well as values.
    need(json.dumps(c, sort_keys=True, separators=(',', ':')) ==
         json.dumps(expected, sort_keys=True, separators=(',', ':')), 'unapproved project binding')
    return c


def validate_context(c, privileged):
    exact_keys(c, ['repository', 'ref', 'event', 'sha', 'run_id', 'attempt', 'workflow_ref'])
    need(bool(SHA.fullmatch(c['sha'])), 'invalid head')
    need(bool(POSITIVE.fullmatch(c['run_id'])) and bool(POSITIVE.fullmatch(c['attempt'])), 'invalid run/attempt')
    if privileged:
        need(c['repository'] == CD_REPO and c['ref'] == 'refs/heads/main' and
             c['event'] == 'workflow_dispatch', 'untrusted privileged caller')
        need(c['workflow_ref'] in [f'{CD_REPO}/.github/workflows/{x}.yml@refs/heads/main'
                                   for x in ['deploy', 'rollback', 'status', 'publish', 'health']], 'untrusted workflow')
    else:
        need(c['repository'] in (SOURCE_REPO, CD_REPO), 'unapproved CI repository')
        need(c['event'] in ('pull_request', 'push', 'workflow_dispatch'), 'unapproved CI event')
    return c


def context():
    return dict(repository=os.environ.get('GITHUB_REPOSITORY', ''), ref=os.environ.get('GITHUB_REF', ''),
                event=os.environ.get('GITHUB_EVENT_NAME', ''), sha=os.environ.get('GITHUB_SHA', ''),
                run_id=os.environ.get('GITHUB_RUN_ID', ''), attempt=os.environ.get('GITHUB_RUN_ATTEMPT', ''),
                workflow_ref=os.environ.get('GITHUB_WORKFLOW_REF', ''))


def require_activation():
    if ACTIVATION is None:
        raise ValueError('UNBOUND: protection/cost/host/identity/image qualification not accepted')
    # A future reviewed binding must fix IDs, not accept caller-selected entitlements.
    need(ACTIVATION.get('repository') == CD_REPO and ACTIVATION.get('environment') == ENVIRONMENT,
         'invalid activation binding')


def make_provenance(source, archive_hash, image, run, attempt, shared, workflow_sha=None):
    return dict(schema_version=1, repository=SOURCE_REPO, source_sha=source,
                archive_sha256=archive_hash, image_id=image, run_id=run,
                run_attempt=attempt, shared_sha=shared, workflow_repository=CD_REPO,
                workflow_sha=workflow_sha if workflow_sha is not None else shared)


def validate_provenance(p, *, source, run, attempt, shared):
    exact_keys(p, make_provenance('', '', '', '', '', ''))
    need(type(p['schema_version']) is int and p['schema_version'] == 1, 'provenance schema')
    need(p['repository'] == SOURCE_REPO and p['workflow_repository'] == CD_REPO, 'wrong artifact repo')
    need(bool(SHA.fullmatch(source)) and p['source_sha'] == source, 'wrong artifact source')
    need(bool(SHA.fullmatch(shared)) and p['shared_sha'] == shared, 'wrong shared version')
    need(bool(POSITIVE.fullmatch(run)) and p['run_id'] == run and
         bool(POSITIVE.fullmatch(attempt)) and p['run_attempt'] == attempt, 'wrong artifact run/attempt')
    need(bool(SHA.fullmatch(p['workflow_sha'])), 'invalid workflow revision')
    need(bool(HASH.fullmatch(p['archive_sha256'])) and bool(IMAGE.fullmatch(p['image_id'])), 'nonimmutable artifact')
    return p


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def command(args, cwd=None):
    # No shell=True, no caller-supplied executable. Never dump Docker output/errors.
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    need(result.returncode == 0, 'command failed: ' + args[0])
    return result.stdout.strip()


def docker(args):
    need(os.getuid() != 0 and os.environ.get('USER') == 'sevenbot-deploy', 'wrong host account')
    need(os.environ.get('DOCKER_HOST') == f'unix:///run/user/{os.getuid()}/docker.sock', 'wrong daemon')
    # Confirm actual daemon rootless identity without exposing full inspect or Env.
    security = json.loads(command(['docker', 'info', '--format', '{{json .SecurityOptions}}']))
    need('name=rootless' in security, 'daemon not rootless')
    return command(['docker', *args])


def install_container(run, image, source, revision, run_id='1', attempt='1'):
    need(bool(IMAGE.fullmatch(image)) and bool(SHA.fullmatch(source)), 'invalid immutable identity')
    need(revision in ('flow-probe-v1', 'flow-probe-v2'), 'invalid revision')
    existing = run(['container', 'ls', '-aq', '--filter', 'name=^/' + SERVICE + '$'])
    need(not existing, 'existing resource: inspect and stop')
    need(bool(POSITIVE.fullmatch(run_id)) and bool(POSITIVE.fullmatch(attempt)), 'invalid operation owner')
    return run(['run', '--detach', '--name', SERVICE, '--label', 'sevenbot.source=' + source,
                '--label', 'sevenbot.run=' + run_id, '--label', 'sevenbot.attempt=' + attempt,
                '--publish', '127.0.0.1:18080:8080', '--memory', '128m', '--cpus', '0.5',
                '--pids-limit', '64', '--read-only', '--user', '65532:65532', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                '--network', 'bridge', '--restart', 'no', image,
                '--host', '0.0.0.0', '--port', '8080', '--source-sha', source,
                '--response-revision', revision])


def http_json(path):
    # Fixed loopback origin, no proxies, no redirects, bounded reads.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError('health redirect rejected')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open('http://127.0.0.1:18080' + path, timeout=5) as response:
        need(response.status == 200, 'unhealthy HTTP status')
        raw = response.read(8193)
        need(len(raw) <= 8192, 'oversized health response')
        return json.loads(raw, object_pairs_hook=pairs)


def collect_status(run, source, image, revision, c):
    need(bool(SHA.fullmatch(source)) and bool(IMAGE.fullmatch(image)), 'invalid health identity')
    need(revision in ('flow-probe-v1', 'flow-probe-v2'), 'invalid health revision')
    observed = json.loads(run(['container', 'inspect', '--format',
                              '{"image":{{json .Image}},"running":{{json .State.Running}}}', SERVICE]))
    need(observed == {'image': image, 'running': True}, 'wrong running image')
    version, health, function = http_json('/version'), http_json('/healthz'), http_json('/')
    need(version == {'schema_version': 1, 'source_sha': source, 'response_revision': revision}, 'version mismatch')
    need(type(health) is dict and health.get('healthy') is True, 'function health failed')
    message = 'sevenbot-' + revision
    need(type(function) is dict and function.get('message') == message, 'function mismatch')
    return dict(schema_version=1, state='running', observed_source_sha=version['source_sha'],
                observed_image_id=observed['image'], conclusion='success',
                collected_at_utc=datetime.now(timezone.utc).isoformat(), target=SERVICE,
                source_sha=source, image_id=image, healthy=True, message=message,
                workflow_repository=c['repository'], workflow_ref=c['workflow_ref'],
                run_id=c['run_id'], run_attempt=c['attempt'])


def validate_status(s, *, source, image, run, attempt, workflow, now=None):
    exact_keys(s, ['schema_version', 'state', 'observed_source_sha', 'observed_image_id', 'conclusion',
                   'collected_at_utc', 'target', 'source_sha', 'image_id', 'healthy', 'message',
                   'workflow_repository', 'workflow_ref', 'run_id', 'run_attempt'])
    need(type(s['schema_version']) is int and s['schema_version'] == 1 and
         s['state'] == 'running' and s['conclusion'] == 'success' and
         s['observed_source_sha'] == source and s['observed_image_id'] == image, 'wrong observed status')
    need(bool(SHA.fullmatch(source)) and bool(IMAGE.fullmatch(image)), 'bad expected status identity')
    need(s['source_sha'] == source and s['image_id'] == image and s['target'] == SERVICE, 'status target mismatch')
    need(s['workflow_repository'] == CD_REPO and s['workflow_ref'] == workflow and
         workflow == f'{CD_REPO}/.github/workflows/status.yml@refs/heads/main', 'status workflow mismatch')
    need(s['run_id'] == run and s['run_attempt'] == attempt and
         bool(POSITIVE.fullmatch(run)) and bool(POSITIVE.fullmatch(attempt)), 'status attempt mismatch')
    need(s['healthy'] is True and s['message'] in ('sevenbot-flow-probe-v1', 'sevenbot-flow-probe-v2'), 'unhealthy status')
    collected = datetime.fromisoformat(s['collected_at_utc'])
    offset = collected.utcoffset()
    need(offset is not None and offset.total_seconds() == 0, 'non UTC status')
    age = ((now or datetime.now(timezone.utc)) - collected).total_seconds()
    need(0 <= age <= 300, 'stale/future status')
    return age


def github_get(path):
    need(path.startswith('/repos/') and '..' not in path and '?' not in path, 'unsafe API path')
    token = os.environ.get('GH_TOKEN', '')
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com' + path, headers=headers)
    # No token or raw response/errors emitted by caller.
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(1048577)
        need(len(raw) <= 1048576, 'oversized API receipt')
        return json.loads(raw)


def source_gate(source, historical=False):
    need(bool(SHA.fullmatch(source)), 'bad source SHA')
    main = github_get(f'/repos/{SOURCE_REPO}/commits/main')
    if historical:
        comparison = github_get(f'/repos/{SOURCE_REPO}/compare/{source}...{main["sha"]}')
        need(comparison.get('status') in ('ahead', 'identical'), 'rollback source not on main ancestry')
    else:
        need(main['sha'] == source, 'source is not exact current main')
    pulls = github_get(f'/repos/{SOURCE_REPO}/commits/{source}/pulls')
    qualifying = [p for p in pulls if p.get('merged_at') and p.get('merge_commit_sha') == source and
                  p.get('base', {}).get('ref') == 'main' and p.get('base', {}).get('repo', {}).get('full_name') == SOURCE_REPO]
    need(len(pulls) < 30 and len(qualifying) == 1, 'unique merged PR required')
    pr = qualifying[0]
    reviews = github_get(f'/repos/{SOURCE_REPO}/pulls/{pr["number"]}/reviews')
    # API default page may truncate: fail closed instead of assuming unseen evidence.
    need(len(reviews) < 30, 'review pagination requires qualification')
    latest = {}
    for review in reviews:
        if review.get('state') in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[review['user']['id']] = review
    approved = [r for r in latest.values() if r['state'] == 'APPROVED' and
                r.get('commit_id') == pr['head']['sha'] and r['user']['id'] != pr['user']['id'] and
                r['user'].get('type') == 'User' and
                r.get('author_association') in ('OWNER', 'MEMBER', 'COLLABORATOR')]
    need(bool(approved), 'distinct exact-head approval missing')
    for head in {source, pr['head']['sha']}:
        need(bool(SHA.fullmatch(head)), 'bad approved head')
        checks = github_get(f'/repos/{SOURCE_REPO}/commits/{head}/check-runs')
        need(checks.get('total_count', 0) == len(checks.get('check_runs', [])), 'checks truncated')
        named = [x for x in checks.get('check_runs', []) if x.get('name') == 'ci']
        need(bool(named) and all(x['head_sha'] == head and x['status'] == 'completed' and
                 x['conclusion'] == 'success' and x['app']['slug'] == 'github-actions'
                 for x in named), 'exact head CI missing')


def artifact_gate(p):
    run = github_get(f'/repos/{CD_REPO}/actions/runs/{p["run_id"]}')
    need(str(run.get('run_attempt')) == p['run_attempt'] and run.get('conclusion') == 'success' and
         run.get('status') == 'completed' and run.get('event') == 'workflow_dispatch' and
         run.get('head_branch') == 'main' and run.get('path') == '.github/workflows/publish.yml' and
         run.get('repository', {}).get('full_name') == CD_REPO and
         run.get('head_sha') == p['workflow_sha'], 'untrusted publication run')
    artifacts = github_get(f'/repos/{CD_REPO}/actions/runs/{p["run_id"]}/artifacts')
    need(artifacts.get('total_count') == len(artifacts.get('artifacts', [])), 'artifact inventory truncated')
    matches = [a for a in artifacts['artifacts'] if a.get('name') ==
               f'image-{p["run_id"]}-{p["run_attempt"]}' and not a.get('expired')]
    need(len(matches) == 1 and re.fullmatch(r'sha256:[0-9a-f]{64}', matches[0].get('digest', '')) is not None,
         'immutable publication artifact missing')


def known_health(receipt, source=None, image=None, *, expected_run='', expected_attempt=''):
    need(bool(POSITIVE.fullmatch(expected_run)) and bool(POSITIVE.fullmatch(expected_attempt)),
         'expected health download identity required')
    need(type(receipt) is dict and receipt.get('run_id') == expected_run and
         receipt.get('run_attempt') == expected_attempt, 'health download identity mismatch')
    need(receipt.get('message') in ('sevenbot-flow-probe-v1', 'sevenbot-flow-probe-v2'),
         'invalid known healthy function')
    need(type(receipt) is dict and receipt.get('target') == SERVICE and receipt.get('healthy') is True and
         receipt.get('workflow_repository') == CD_REPO, 'untrusted health receipt')
    need(bool(SHA.fullmatch(receipt.get('source_sha', ''))) and
         bool(IMAGE.fullmatch(receipt.get('image_id', ''))), 'bad health identity')
    need(source is None or receipt['source_sha'] == source, 'wrong known healthy source')
    need(image is None or receipt['image_id'] == image, 'wrong known healthy image')
    need(bool(POSITIVE.fullmatch(receipt.get('run_id', ''))) and
         bool(POSITIVE.fullmatch(receipt.get('run_attempt', ''))), 'bad health run')
    trusted = [f'{CD_REPO}/.github/workflows/{w}.yml@refs/heads/main' for w in ['deploy', 'rollback']]
    need(receipt.get('workflow_ref') in trusted, 'bad health workflow')
    run = github_get(f'/repos/{CD_REPO}/actions/runs/{receipt["run_id"]}')
    need(run.get('conclusion') == 'success' and str(run.get('run_attempt')) == receipt['run_attempt'] and
         run.get('head_branch') == 'main' and run.get('event') == 'workflow_dispatch' and
         f'{CD_REPO}/{run.get("path")}@refs/heads/main' == receipt['workflow_ref'], 'health run mismatch')
    return receipt


def write_receipt(directory, name, value):
    directory = Path(directory)
    need(directory.is_dir() and not directory.is_symlink(), 'missing evidence directory')
    path = directory / name
    # No overwrite/replay of prior evidence.
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.write('\n')


def publish(args, c):
    source_gate(args.source)
    app = Path(args.app).resolve(strict=True)
    need(command(['git', 'rev-parse', 'HEAD'], cwd=app) == args.source, 'checkout head mismatch')
    need(not command(['git', 'status', '--porcelain'], cwd=app), 'dirty application checkout')
    safe_file(app, 'apps/sevenbot-flow-probe/server.py')
    dockerfile = safe_file(helper_root(), 'docker/Dockerfile')
    # A Dockerfile is intentionally absent until actual base/ARM64 pin qualification.
    need('FROM ' in dockerfile.read_text() and '@sha256:' in dockerfile.read_text(), 'unqualified Dockerfile')
    need(command(['uname', '-m']) == 'aarch64', 'native ARM64 execution required')
    image_tag = SERVICE + ':' + args.source
    docker(['build', '--platform', 'linux/arm64', '--pull=false', '--network=none',
             '-f', str(dockerfile), '-t', image_tag, str(app)])
    image = docker(['image', 'inspect', '--format', '{{.Id}}', image_tag])
    need(bool(IMAGE.fullmatch(image)), 'invalid built image')
    archive = Path(args.evidence) / 'image.tar'
    need(not archive.exists() and not archive.is_symlink(), 'existing archive')
    docker(['image', 'save', '-o', str(archive), image])
    p = make_provenance(args.source, sha256(archive), image, c['run_id'], c['attempt'], args.shared, c['sha'])
    write_receipt(args.evidence, 'provenance.json', p)


def operate(args, c):
    p = load_json(safe_file(args.artifact, 'provenance.json'))
    validate_provenance(p, source=args.source, run=args.artifact_run,
                        attempt=args.artifact_attempt, shared=args.shared)
    archive = safe_file(args.artifact, 'image.tar')
    need(sha256(archive) == p['archive_sha256'], 'archive hash mismatch')
    artifact_gate(p)
    source_gate(args.source, historical=args.operation in ('rollback', 'health', 'status'))
    if args.operation in ('health', 'status'):
        receipt = collect_status(docker, args.source, p['image_id'], args.revision, c)
        write_receipt(args.evidence, 'status.json', receipt)
        return
    previous = None
    if args.operation == 'rollback' or args.previous:
        need(bool(args.previous), 'known healthy receipt required')
        previous = known_health(load_json(args.previous), expected_run=args.previous_run,
                                expected_attempt=args.previous_attempt)
        need(int(previous['run_id']) < int(c['run_id']), 'stale operation')
        if args.operation == 'rollback':
            need(bool(args.known_healthy), 'known healthy rollback target required')
            target = known_health(load_json(args.known_healthy), args.source, p['image_id'],
                                  expected_run=args.known_run, expected_attempt=args.known_attempt)
            need(int(target['run_id']) < int(c['run_id']), 'stale rollback target')
            # The receipt qualifies the image AND functional configuration. Caller input
            # cannot turn the known-good image into a never-qualified configuration.
            need(args.revision == target['message'].removeprefix('sevenbot-'),
                 'rollback configuration does not match known healthy target')
        # Recovery requires the actual old image to remain locally available.
        need(docker(['image', 'inspect', '--format', '{{.Id}}', previous['image_id']]) ==
             previous['image_id'], 'previous image unavailable')
    # Validate all inputs before loading. Existing resource is never implicitly adopted.
    existing = docker(['container', 'ls', '-aq', '--filter', 'name=^/' + SERVICE + '$'])
    if existing:
        if previous is None:
            raise ValueError('existing resource: previous receipt required')
        observed = json.loads(docker(['container', 'inspect', '--format',
                                     '{"image":{{json .Image}},"source":{{json (index .Config.Labels "sevenbot.source")}},"run":{{json (index .Config.Labels "sevenbot.run")}},"attempt":{{json (index .Config.Labels "sevenbot.attempt")}}}', SERVICE]))
        need(observed == {'image': previous['image_id'], 'source': previous['source_sha'],
                          'run': previous['run_id'], 'attempt': previous['run_attempt']}, 'existing resource conflict')
    docker(['image', 'load', '--input', str(archive)])
    loaded = docker(['image', 'inspect', '--format', '{{.Id}}', p['image_id']])
    need(loaded == p['image_id'], 'loaded image mismatch')
    try:
        # Stop/remove can fail AFTER taking effect. Include both in the failure
        # boundary; inspect once during recovery, never replay a failed mutation.
        if existing:
            docker(['container', 'stop', '--time', '10', SERVICE])
            docker(['container', 'rm', SERVICE])
        install_container(docker, p['image_id'], args.source, args.revision, c['run_id'], c['attempt'])
        receipt = collect_status(docker, args.source, p['image_id'], args.revision, c)
        write_receipt(args.evidence, 'status.json', receipt)
    except Exception:
        recovery = 'NOT_AVAILABLE_INITIAL_DEPLOY'
        if previous is not None:
            try:
                # Remove only this operation's candidate. A remaining previous
                # container (possibly stopped) or any ambiguous/conflicting identity
                # is preserved for an incident, not stopped/removed a second time.
                remaining = docker(['container', 'ls', '-aq', '--filter', 'name=^/' + SERVICE + '$'])
                if remaining:
                    failed = json.loads(docker(['container', 'inspect', '--format',
                        '{"image":{{json .Image}},"source":{{json (index .Config.Labels "sevenbot.source")}},"run":{{json (index .Config.Labels "sevenbot.run")}},"attempt":{{json (index .Config.Labels "sevenbot.attempt")}}}', SERVICE]))
                    need(failed == {'image': p['image_id'], 'source': args.source,
                                    'run': c['run_id'], 'attempt': c['attempt']}, 'recovery candidate conflict')
                    docker(['container', 'stop', '--time', '10', SERVICE])
                    docker(['container', 'rm', SERVICE])
                old_revision = previous['message'].removeprefix('sevenbot-')
                install_container(docker, previous['image_id'], previous['source_sha'], old_revision,
                                  c['run_id'], c['attempt'])
                restored = collect_status(docker, previous['source_sha'], previous['image_id'], old_revision, c)
                write_receipt(args.evidence, 'recovery.json', restored)
                recovery = 'RESTORED_AND_HEALTH_VERIFIED'
            except Exception:
                recovery = 'FAILED_STOP_INCIDENT_REQUIRED'
        write_receipt(args.evidence, 'failure.json', {'target': SERVICE, 'result': 'FAIL',
                      'recovery': recovery, 'run_id': c['run_id'], 'run_attempt': c['attempt']})
        # Original release always fails even when recovery is healthy.
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['validate', 'ci', 'gate', 'publish', 'deploy', 'health', 'rollback', 'status'])
    parser.add_argument('--config', required=True)
    parser.add_argument('--source', default='')
    parser.add_argument('--shared', default='')
    parser.add_argument('--app', default='app')
    parser.add_argument('--artifact', default='artifact')
    parser.add_argument('--artifact-run', default='')
    parser.add_argument('--artifact-attempt', default='')
    parser.add_argument('--previous', default='')
    parser.add_argument('--known-healthy', default='')
    parser.add_argument('--previous-run', default='')
    parser.add_argument('--previous-attempt', default='')
    parser.add_argument('--known-run', default='')
    parser.add_argument('--known-attempt', default='')
    parser.add_argument('--revision', choices=['flow-probe-v1', 'flow-probe-v2'], default='flow-probe-v1')
    parser.add_argument('--evidence', default='evidence')
    args = parser.parse_args()
    validate_config(load_json(args.config))
    if args.operation == 'validate':
        print('validated project binding; activation not implied')
        return
    c = validate_context(context(), privileged=args.operation != 'ci')
    need(bool(SHA.fullmatch(args.shared)), 'immutable shared helper revision required')
    need(command(['git', 'rev-parse', 'HEAD'], cwd=helper_root()) == args.shared, 'helper checkout mismatch')
    if args.operation == 'ci':
        app = Path(args.app).resolve(strict=True)
        safe_file(app, 'apps/sevenbot-flow-probe/server.py')
        # Bounded approved argv only, on GitHub-hosted public CI, never a host executor.
        result = subprocess.run(TEST, cwd=app, timeout=600, check=False)
        need(result.returncode == 0, 'application tests failed')
        return
    require_activation()
    need(c['attempt'] == '1', 'manual reruns not authorized')
    if args.operation == 'gate':
        return
    if args.operation == 'publish':
        publish(args, c)
    else:
        operate(args, c)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never serialize secret-bearing API, URL, Docker error or raw exception.
        print('delivery stopped: ' + (str(exc) if type(exc) is ValueError else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
