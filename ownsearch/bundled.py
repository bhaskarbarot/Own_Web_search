"""Launch the source copy in searxxxing; search logic stays in the upstream code."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'searxxxing'
RUNTIME = ROOT / '.runtime' / 'searxxxing'


def _write_json(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.name+'.', delete=False) as handle:
        temp = Path(handle.name)
        try:
            os.chmod(temp, mode)
            json.dump(value, handle, indent=2)
            handle.write('\n')
            handle.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def setup(data_dir, port=8888, install=True):
    if not 1024 <= port <= 65535:
        raise ValueError('Choose a localhost port between 1024 and 65535.')
    if not (SOURCE / 'LICENSE').is_file() or not (SOURCE / 'searx/webapp.py').is_file():
        raise ValueError('Bundled source is missing. This command requires the repository checkout with searxxxing/.')
    # Read existing user configuration before making changes; never erase malformed config.
    config_file = Path(data_dir) / 'ownsearch.json'
    config = json.loads(config_file.read_text()) if config_file.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('ownsearch.json must be a JSON object; existing file was preserved.')
    settings_file = RUNTIME / 'settings.yml'
    old = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    secret = old.get('server', {}).get('secret_key') or secrets.token_hex(32)
    engines = ['google', 'bing', 'brave', 'duckduckgo', 'google news', 'bing news',
               'brave.news', 'duckduckgo news', 'bing images', 'brave.images']
    # JSON is valid YAML. Only this small instance configuration is customized.
    settings = {
        'use_default_settings': {'engines': {'keep_only': engines}},
        'general': {'instance_name': 'OwnSearch discovery (SearXNG)', 'debug': False},
        'search': {'formats': ['html', 'json'], 'autocomplete': '', 'favicon_resolver': ''},
        'server': {'bind_address': '127.0.0.1', 'port': port, 'secret_key': secret,
                   'limiter': False, 'public_instance': False, 'image_proxy': False},
        'valkey': {'url': False},
        'outgoing': {'request_timeout': 2.0, 'max_request_timeout': 2.5},
        'engines': [{'name': name, 'disabled': False, 'timeout': 2.0} for name in engines],
    }
    python = RUNTIME / 'venv/bin/python'
    if install:
        if not python.exists():
            subprocess.run([sys.executable, '-m', 'venv', str(RUNTIME / 'venv')], check=True)
        try:
            subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(SOURCE / 'requirements.txt'),
                            '-r', str(SOURCE / 'requirements-server.txt')], check=True)
            subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
        except subprocess.CalledProcessError as exc:
            raise ValueError('Dependency installation failed; inspect the pip output and rerun setup.') from exc
    _write_json(settings_file, settings)
    (RUNTIME / 'cache').mkdir(exist_ok=True)
    config.update(searxng_url=f'http://127.0.0.1:{port}', searxng_allow_private=True,
                  searxng_timeout=3.5)
    _write_json(config_file, config)
    return {'source': str(SOURCE), 'settings': str(settings_file),
            'ownsearch_config': str(config_file), 'url': config['searxng_url'],
            'started': False, 'next': 'python3 main.py discovery serve'}


def launch_spec():
    settings_file = RUNTIME / 'settings.yml'
    python = RUNTIME / 'venv/bin/python'
    if not settings_file.is_file() or not python.is_file():
        raise ValueError('Run python3 main.py discovery setup first.')
    settings = json.loads(settings_file.read_text())
    # This launcher is intentionally localhost-only; public hosting needs its own configuration.
    port = int(settings['server']['port'])
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid bundled discovery port.')
    env = os.environ.copy()
    env.update(PYTHONPATH=str(SOURCE), SEARXNG_SETTINGS_PATH=str(settings_file),
               TMPDIR=str(RUNTIME / 'cache'), SEARXNG_DEBUG='false')
    args = [str(python), '-m', 'granian', '--interface', 'wsgi', '--host', '127.0.0.1',
            '--port', str(port), '--workers', '1', '--blocking-threads', '4',
            '--runtime-threads', '1', 'searx.webapp:app']
    return args, env


def serve():
    args, env = launch_spec()
    os.chdir(SOURCE)
    os.execve(args[0], args, env)


def status():
    settings_file = RUNTIME / 'settings.yml'
    if not settings_file.is_file():
        return {'running': False, 'note': 'Run python3 main.py discovery setup first.'}
    port = int(json.loads(settings_file.read_text())['server']['port'])
    url = f'http://127.0.0.1:{port}'
    # Never send the local instance probe via an environment HTTP proxy.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url+'/config', timeout=2) as response:
            config = json.loads(response.read(2_000_000))
        if not isinstance(config, dict):
            raise ValueError('Invalid instance configuration response.')
        valid = config.get('instance_name') == 'OwnSearch discovery (SearXNG)'
        return {'running': valid, 'url': url, 'source': str(SOURCE),
                'engines': [row['name'] for row in config.get('engines', [])],
                'note': 'Local instance checked; upstream search availability is not certified.'}
    except (OSError, ValueError, TypeError) as exc:
        return {'running': False, 'url': url, 'error': type(exc).__name__}
