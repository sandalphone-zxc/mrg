"""Explicit one-run command; no background scheduling or automatic extra budget."""
import argparse
import json
import os
import sys
from pathlib import Path
from . import KDiscovery, initialize_workspace
from .api import GithubConfiguration, exclusive_run
from .github_client import GithubClient
from .providers import OpenAICompatibleProvider
from .kd_s2_format import digest
from .kd_s2_report import verify
from .kd_s3 import folder_for
from .kd_s3_calls import ServicePause
from .kd_s2_sources import atomic

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='KD-S-3 requirements-led discovery')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('strategies')
    sub.add_parser('doctor')
    init = sub.add_parser('init'); init.add_argument('workspace')
    check = sub.add_parser('verify'); check.add_argument('folder')
    mine = sub.add_parser('mine')
    mine.add_argument('--workspace', required=True)
    mine.add_argument('--repo', required=True, help='owner/repository')
    mine.add_argument('--commit', required=True, help='Fixed 40-character Git SHA')
    mine.add_argument('--run-id', required=True, help='Reuse only to continue the same run and remaining budget')
    mine.add_argument('--model', default='deepseek-v4-pro')
    args = parser.parse_args(argv)
    try:
        if args.command == 'strategies':
            print(json.dumps(KDiscovery.describe(), ensure_ascii=False, indent=2)); return 0
        if args.command == 'doctor':
            from .runtime import identity
            print(json.dumps(identity(), indent=2)); return 0
        if args.command == 'init':
            print(initialize_workspace(args.workspace)); return 0
        if args.command == 'verify':
            print(json.dumps(verify(Path(args.folder)), ensure_ascii=False, indent=2)); return 0
        workspace = initialize_workspace(args.workspace)
        endpoint = os.environ.get('KDISCOVERY_MODEL_ENDPOINT', '')
        key = os.environ.get('KDISCOVERY_API_KEY', '')
        if not endpoint or not key:
            raise ValueError('Set KDISCOVERY_MODEL_ENDPOINT and KDISCOVERY_API_KEY')
        folder = folder_for(workspace, args.repo, args.commit, args.run_id)
        with exclusive_run(folder):
            config = {'repo': args.repo, 'commit': args.commit, 'model': args.model,
                      'model_url': endpoint, 'adapter': 'openai-compatible-v1', 'temperature': 0}
            lock = folder/'run-config.json'
            if lock.exists() and json.loads(lock.read_text(encoding='utf8')) != config:
                raise ValueError('Run configuration changed; refusing to mix checkpoints')
            atomic(lock, config)
            usage_path = folder/'provider-usage.json'
            if usage_path.exists():
                usage = json.loads(usage_path.read_text(encoding='utf8'))
                if any(r['status'] in ('requested', 'result_unknown') for r in usage):
                    raise ServicePause('Previous model outcome unknown; resolve it before continuing this run')
            provider = OpenAICompatibleProvider(endpoint, args.model, key, usage_path)
            api = GithubClient(GithubConfiguration(workspace))
            strategy = KDiscovery.create('github', 'KD-S-3', provider, workspace, api)
            result = strategy.extract({'repo': args.repo, 'commit': args.commit}, {},
                                      {'model': args.model, 'model_url': endpoint,
                                       'model_config_hash': digest(config)}, args.run_id,
                                      lambda message: print(message, file=sys.stderr))
            print(json.dumps({'folder': result['folder'], 'status': result.get('manifest', {}).get('status'),
                              'provider_usage': str(usage_path)}, ensure_ascii=False, default=str))
            return 0
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr); return 2

if __name__ == '__main__':
    raise SystemExit(main())
