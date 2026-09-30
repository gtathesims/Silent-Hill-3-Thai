import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent / 'baseline/original'
sys.path.insert(0, str(ROOT))
from mod_patcher import patch_game
from core.backup import sha256_file
from games.silent_hill_3.adapter import load_profile, prepare_patch_transaction
from games.silent_hill_3 import pictures  # Load resource paths before mocking the fallback bundle.


class ExeFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = Path(self.tmp.name) / 'game'
        (self.game / 'data').mkdir(parents=True)
        for name in ('sh3.exe', 'data/msg.arc', 'data/pic.arc'):
            shutil.copy2(BASE / name, self.game / name)
        # A different executable build with an intact PE header.
        with (self.game / 'sh3.exe').open('ab') as stream:
            stream.write(b'test alternate executable')
        self.before = {name: sha256_file(self.game / name) for name in
                       ('sh3.exe', 'data/msg.arc', 'data/pic.arc')}

    def engine(self, *args, expected=0):
        command = ([str(ROOT / 'build/windows_bundle/SilentHill3ThaiModInstaller/ModPatcher.exe')]
                   if os.environ.get('TEST_FROZEN_ENGINE') == '1'
                   else [sys.executable, str(ROOT / 'mod_patcher.py')])
        result = subprocess.run([*command,
                                 '--game-dir', str(self.game), *args],
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_originals(self):
        for name, digest in self.before.items():
            self.assertEqual(sha256_file(self.game / name), digest)

    def test_fallback_install_repeat_restore_and_reinstall(self):
        self.engine('--patch', expected=10)
        self.assert_originals()
        dry = self.engine('--dry-run', '--allow-exe-fallback')
        self.assertEqual(dry['overall_status'], 'supported-with-exe-fallback')
        self.assert_originals()
        self.assertFalse((self.game / '.thai_mod_installer/backups').exists())
        result = self.engine('--patch', '--allow-exe-fallback')
        self.assertTrue(result['exe_fallback_used'])
        for config in load_profile()['targets'].values():
            self.assertEqual(sha256_file(self.game / config['path']), config['known_patched_sha256'])
        self.assertEqual(self.engine('--patch', '--allow-exe-fallback')['overall_status'],
                         'already-installed-verified')
        self.engine('--restore')
        self.assert_originals()
        self.assertFalse((self.game / '.thai_mod_installer').exists())
        self.engine('--patch', '--allow-exe-fallback')
        self.engine('--restore')
        self.assert_originals()
        self.assertFalse((self.game / '.thai_mod_installer').exists())

    def test_unknown_archive_still_refused(self):
        with (self.game / 'data/msg.arc').open('ab') as stream:
            stream.write(b'unsupported')
        self.before['data/msg.arc'] = sha256_file(self.game / 'data/msg.arc')
        self.engine('--patch', '--allow-exe-fallback', expected=10)
        self.assert_originals()

    def test_corrupt_bundled_exe_refused(self):
        with patch('games.silent_hill_3.adapter.INSTALLER_ROOT', Path(self.tmp.name)):
            result, code = patch_game(self.game, allow_exe_fallback=True)
        self.assertEqual(code, 18, result)
        self.assert_originals()

    def test_mid_commit_failure_restores_unknown_exe(self):
        import os
        replace = os.replace
        transaction = prepare_patch_transaction(self.game, Path(self.tmp.name) / 'candidates',
                                                allow_exe_fallback=True)
        def fail_message_commit(source, destination):
            if str(source).endswith('msg.arc.mod-install-tmp'):
                raise OSError('simulated message commit failure')
            return replace(source, destination)
        with patch('core.transaction.os.replace', side_effect=fail_message_commit):
            with self.assertRaisesRegex(Exception, 'rolled back'):
                transaction.commit()
        self.assert_originals()


if __name__ == '__main__':
    unittest.main()
