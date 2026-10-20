"""Bundled setup/launch regressions; no package installs or public services needed."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ownsearch import bundled
from ownsearch.cli import main
from ownsearch.config import Settings
from ownsearch.webproviders import configured


class BundledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ownsearch-bundled-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'searxxxing'
        (self.source / 'searx').mkdir(parents=True)
        (self.source / 'LICENSE').write_text('License fixture')
        (self.source / 'searx/webapp.py').write_text('# Fixture')
        self.runtime = self.root / '.runtime/searxxxing'
        self.data = self.root / 'settings'
        for name, value in [('SOURCE', self.source), ('RUNTIME', self.runtime)]:
            context = patch.object(bundled, name, value)
            context.start()
            self.addCleanup(context.stop)

    def test_setup_connects_existing_provider_without_creating_corpus(self):
        self.data.mkdir()
        (self.data / 'ownsearch.json').write_text(json.dumps({'live_cache_ttl': 17, 'market_chart_url': ''}))
        result = bundled.setup(self.data, 8890, install=False)
        cfg = Settings.load(self.data)
        self.assertEqual(cfg.live_cache_ttl, 17)
        self.assertEqual(cfg.market_chart_url, '')
        source = configured(cfg)[0]
        self.assertEqual(source.name, 'searxng')
        self.assertEqual(source.settings.searxng_url, 'http://127.0.0.1:8890')
        self.assertTrue(source.settings.searxng_allow_private)
        self.assertFalse(source.settings.allow_private_hosts)
        self.assertEqual([p.name for p in self.data.iterdir()], ['ownsearch.json'])
        self.assertFalse(result['started'])
        settings_file = self.runtime / 'settings.yml'
        settings = json.loads(settings_file.read_text())
        secret = settings['server']['secret_key']
        self.assertGreaterEqual(len(secret), 64)
        self.assertEqual(settings_file.stat().st_mode & 0o777, 0o600)
        self.assertIn('json', settings['search']['formats'])
        self.assertLess(settings['outgoing']['max_request_timeout'], cfg.searxng_timeout)
        bundled.setup(self.data, 8890, install=False)
        self.assertEqual(json.loads(settings_file.read_text())['server']['secret_key'], secret)

    def test_invalid_user_config_is_preserved_before_any_install(self):
        self.data.mkdir()
        target = self.data / 'ownsearch.json'
        target.write_text('{invalid')
        with patch.object(bundled.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                bundled.setup(self.data)
            run.assert_not_called()
        self.assertEqual(target.read_text(), '{invalid')
        self.assertFalse(self.runtime.exists())

    def test_launcher_uses_bundled_source_and_localhost(self):
        bundled.setup(self.data, 8890, install=False)
        python = self.runtime / 'venv/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.dict(os.environ, {'PYTHONPATH': '/wrong-clone'}):
            args, env = bundled.launch_spec()
        self.assertEqual(args[0], str(python))
        self.assertIn('granian', args)
        self.assertEqual(args[args.index('--host')+1], '127.0.0.1')
        self.assertEqual(args[args.index('--port')+1], '8890')
        self.assertEqual(env['PYTHONPATH'], str(self.source))
        self.assertEqual(env['TMPDIR'], str(self.runtime / 'cache'))
        self.assertNotIn('repo/searxng', ' '.join(args)+env['PYTHONPATH'])

    def test_cli_routes_setup_without_opening_document_database(self):
        with patch.object(bundled, 'setup', return_value={'started': False}) as setup:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                result = main(['--data-dir', str(self.data), 'discovery', 'setup', '--port', '8890'])
        setup.assert_called_once_with(self.data, 8890)
        self.assertFalse(json.loads(output.getvalue())['started'])
        self.assertEqual(result, 0)
        self.assertFalse(self.data.exists())

    def test_missing_setup_and_invalid_port_have_clear_errors(self):
        self.assertFalse(bundled.status()['running'])
        with self.assertRaisesRegex(ValueError, 'setup first'):
            bundled.launch_spec()
        for port in (80, 65536):
            with self.assertRaises(ValueError):
                bundled.setup(self.data, port, install=False)
        self.assertFalse(self.runtime.exists())


class UpstreamCopyTests(unittest.TestCase):
    def test_all_regular_upstream_files_preserved_byte_for_byte(self):
        source = Path(__file__).resolve().parents[1] / 'searxxxing'
        manifest = json.loads((source / 'OWNSEARCH_UPSTREAM.json').read_text())
        self.assertEqual(manifest['revision'], '22c64b8d394b680c7ea96be25f36dad14126420a')
        self.assertEqual(manifest['license'], 'AGPL-3.0-or-later')
        for relative, expected in manifest['sha256'].items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((source / relative).read_bytes()).hexdigest(), expected)
        self.assertTrue((source / 'LICENSE').is_file())
        self.assertTrue((source / 'utils/templates/etc/apache2').is_symlink())


if __name__ == '__main__':
    unittest.main()
