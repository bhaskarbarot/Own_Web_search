#!/usr/bin/env bash
# Local UI launcher. Usage: ./run.sh [port]
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -n "${OWNSEARCH_PYTHON:-}" ]]; then
  search_python="$OWNSEARCH_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  search_python=.venv/bin/python
else
  search_python=python3
fi
export OWNSEARCH_SEARCH_MODE=live
exec "$search_python" - "$@" <<'PYTHON'
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser

from ownsearch import bundled
from ownsearch.config import Settings

root = Path.cwd()
children = []
logs = []
opener = build_opener(ProxyHandler({}))

def interrupt(*_):
    raise KeyboardInterrupt

signal.signal(signal.SIGINT, interrupt)
signal.signal(signal.SIGTERM, interrupt)

def request(path, url):
    with opener.open(url + path, timeout=2) as response:
        return response.read(2_000_000)

def api_running(url):
    try:
        return json.loads(request('/', url)).get('name') == 'OwnSearch'
    except (OSError, ValueError, AttributeError):
        return False

def start(args, name):
    path = root / '.runtime' / 'ui' / (name + '.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    log = path.open('a')
    logs.append(log)
    process = subprocess.Popen(args, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    children.append((process, path))
    return process, path

def wait_ready(check, process, log, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Startup failed; see ' + str(log))
        if check():
            return
        time.sleep(.2)
    raise RuntimeError('Startup timed out; see ' + str(log))

try:
    if len(sys.argv) > 2:
        raise ValueError('Usage: ./run.sh [port]')
    port = int(sys.argv[1] if len(sys.argv) == 2 else os.environ.get('OWNSEARCH_UI_PORT', '8765'))
    if not 1024 <= port <= 65535:
        raise ValueError('Choose a UI port between 1024 and 65535.')
    url = 'http://127.0.0.1:' + str(port)
    existing_api = api_running(url)
    if existing_api:
        try:
            if b'id="search-form"' not in request('/ui', url):
                raise ValueError('The running server does not include this UI.')
        except (OSError, ValueError) as exc:
            raise RuntimeError('An older OwnSearch server occupies port ' + str(port) + '. Stop it or use ./run.sh ' + str(port + 1)) from exc
    else:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.5):
                raise RuntimeError('Port ' + str(port) + ' is occupied. Choose another: ./run.sh ' + str(port + 1))
        except OSError:
            pass

    settings = Settings.load()
    if not settings.searxng_url and not settings.brave_api_key:
        installed = (bundled.RUNTIME / 'venv/bin/python').is_file()
        print('Preparing bundled discovery' + ('…' if installed else ' and installing its isolated requirements…'), flush=True)
        bundled.setup(settings.data_dir, install=not installed)
        settings = Settings.load()
    runtime_settings = bundled.RUNTIME / 'settings.yml'
    if runtime_settings.is_file():
        discovery_port = int(json.loads(runtime_settings.read_text())['server']['port'])
        discovery_url = 'http://127.0.0.1:' + str(discovery_port)
        if settings.searxng_url.rstrip('/') == discovery_url:
            if bundled.status().get('running'):
                print('Reusing discovery at ' + discovery_url, flush=True)
            else:
                print('Starting discovery at ' + discovery_url, flush=True)
                process, log = start([sys.executable, 'main.py', 'discovery', 'serve'], 'discovery')
                wait_ready(lambda: bundled.status().get('running'), process, log, 20)
        else:
            print('Using your configured discovery provider.', flush=True)
    elif settings.searxng_url or settings.brave_api_key:
        print('Using your configured discovery provider.', flush=True)

    if existing_api:
        print('Reusing OwnSearch at ' + url, flush=True)
    else:
        print('Starting local OwnSearch UI…', flush=True)
        process, log = start([sys.executable, 'main.py', 'serve', '--host', '127.0.0.1', '--port', str(port), '--no-auth'], 'api-' + str(port))
        wait_ready(lambda: api_running(url), process, log, 10)
    print('\nOpen ' + url + '/ui\nPress Ctrl+C to stop processes started by this launcher.\n', flush=True)
    if os.environ.get('OWNSEARCH_OPEN_BROWSER', '1') != '0' and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        threading.Thread(target=webbrowser.open, args=(url + '/ui',), daemon=True).start()
    while True:
        for process, log in children:
            if process.poll() is not None:
                raise RuntimeError('A service exited; see ' + str(log))
        time.sleep(.5)
except KeyboardInterrupt:
    print('\nStopping local launcher…', flush=True)
except (ValueError, OSError, RuntimeError) as exc:
    print('OwnSearch: ' + str(exc), file=sys.stderr)
    sys.exit(1)
finally:
    for process, _ in reversed(children):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    for log in logs:
        log.close()
PYTHON
