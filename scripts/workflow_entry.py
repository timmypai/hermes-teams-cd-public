"""Fixed workflow entry, not a controller. Inputs never become commands or paths."""
import argparse
import os
from pathlib import Path
import sys
import delivery as d


def inputs(operation):
    shared = os.environ.get('HELPER_SHA', '')
    d.need(bool(d.SHA.fullmatch(shared)), 'immutable helper revision required')
    d.need(d.command(['git', 'rev-parse', 'HEAD'], cwd=d.helper_root()) == shared, 'helper checkout mismatch')
    d.need(not d.command(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=d.helper_root()),
           'modified shared helper checkout')
    d.validate_config(d.load_json(d.helper_root() / 'config/projects/sevenbot-flow-probe.json'))
    c = d.validate_context(d.context(), privileged=operation != 'ci')
    source = os.environ.get('SOURCE_SHA', '')
    d.need(bool(d.SHA.fullmatch(source)), 'invalid source')
    revision = os.environ.get('REVISION', 'flow-probe-v1')
    d.need(revision in ('flow-probe-v1', 'flow-probe-v2'), 'invalid revision')
    if operation != 'ci':
        d.need(c['workflow_ref'] == f'{d.CD_REPO}/.github/workflows/{operation}.yml@refs/heads/main',
               'wrong operation workflow')
        d.need(c['attempt'] == '1', 'manual rerun not authorized')
    args = argparse.Namespace(operation=operation, source=source, shared=shared,
        app='app', artifact='artifact', evidence='evidence', revision=revision,
        artifact_run=os.environ.get('ARTIFACT_RUN', ''),
        artifact_attempt=os.environ.get('ARTIFACT_ATTEMPT', ''),
        previous_run=os.environ.get('PREVIOUS_RUN', ''),
        previous_attempt=os.environ.get('PREVIOUS_ATTEMPT', ''),
        known_run=os.environ.get('KNOWN_RUN', ''), known_attempt=os.environ.get('KNOWN_ATTEMPT', ''),
        previous='', known_healthy='')
    if operation not in ('ci', 'publish'):
        for value in (args.artifact_run, args.artifact_attempt):
            d.need(bool(d.POSITIVE.fullmatch(value)), 'invalid artifact identity')
    for run, attempt in ((args.previous_run, args.previous_attempt), (args.known_run, args.known_attempt)):
        d.need((run == '' and attempt == '') or
               (bool(d.POSITIVE.fullmatch(run)) and bool(d.POSITIVE.fullmatch(attempt))), 'bad health download identity')
    if args.previous_run:
        args.previous = 'previous/status.json'
    if args.known_run:
        args.known_healthy = 'known/status.json'
    if operation == 'rollback':
        d.need(bool(args.previous) and bool(args.known_healthy), 'rollback receipts required')
    return args, c


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['gate', 'run'])
    parser.add_argument('operation', choices=['ci', 'publish', 'deploy', 'health', 'rollback', 'status'])
    options = parser.parse_args()
    args, c = inputs(options.operation)
    if options.operation != 'ci':
        # Deliberately cannot be changed by config, caller, secret or environment.
        d.require_activation()
        d.source_gate(args.source, historical=options.operation in ('rollback', 'health', 'status'))
    if options.phase == 'gate':
        return
    evidence = Path('evidence')
    d.need(not evidence.exists() and not evidence.is_symlink(), 'existing evidence: stop')
    evidence.mkdir(mode=0o700)
    if options.operation == 'ci':
        d.safe_file('app', 'apps/sevenbot-flow-probe/server.py')
        d.need(d.command(['git', 'rev-parse', 'HEAD'], cwd='app') == args.source, 'wrong application checkout')
        # Record the true exit; no shell command interpretation.
        result = d.subprocess.run(d.TEST, cwd='app', capture_output=True, text=True, timeout=590)
        (evidence / 'tests.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        d.write_receipt(evidence, 'ci.json', dict(source_sha=args.source, helper_sha=args.shared,
                        run_id=c['run_id'], run_attempt=c['attempt'], exit_code=result.returncode))
        d.need(result.returncode == 0, 'application tests failed')
    elif options.operation == 'publish':
        d.publish(args, c)
    else:
        d.operate(args, c)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('workflow stopped: ' + (str(exc) if type(exc) is ValueError else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
