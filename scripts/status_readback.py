"""Validate an exact-run Actions-downloaded snapshot, not continuous monitoring."""
import argparse
import sys
import delivery as d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    workflow = f'{d.CD_REPO}/.github/workflows/status.yml@refs/heads/main'
    receipt = d.load_json(args.receipt)
    age = d.validate_status(receipt, source=args.source, image=args.image,
                           run=args.run, attempt=args.attempt, workflow=workflow)
    run = d.github_get(f'/repos/{d.CD_REPO}/actions/runs/{args.run}')
    d.need(str(run.get('id')) == args.run and
           run.get('repository', {}).get('full_name') == d.CD_REPO and
           run.get('path') == '.github/workflows/status.yml' and run.get('head_branch') == 'main' and
           run.get('event') == 'workflow_dispatch' and str(run.get('run_attempt')) == args.attempt and
           run.get('status') == 'completed' and run.get('conclusion') == 'success', 'status API mismatch')
    print(f'validated exact-run snapshot age_seconds={age:.3f}; not continuous health')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('status UNKNOWN: ' + (str(exc) if type(exc) is ValueError else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
