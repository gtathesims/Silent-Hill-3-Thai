import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent/'baseline/original'
ENGINE=ROOT/'build/windows_bundle/SilentHill3ThaiModInstaller/ModPatcher.exe'
sys.path.insert(0,str(ROOT))
from core.backup import BackupStore, BackupTarget, sha256_file
from games.silent_hill_3.adapter import load_profile

class PictureInstallTests(unittest.TestCase):
    def run_engine(self, game, mode, expected=0):
        result=subprocess.run([str(ENGINE),'--game-dir',str(game),mode],capture_output=True,text=True,encoding='utf-8',timeout=120)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return json.loads(result.stdout)

    def fixture(self, root):
        game=root/'game'
        (game/'data').mkdir(parents=True)
        for name in ('sh3.exe','data/msg.arc','data/pic.arc'):
            shutil.copy2(BASE/name,game/name)
        return game

    def test_clean_install_repeat_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=self.fixture(Path(tmp))
            self.assertEqual(self.run_engine(game,'--dry-run')['overall_status'],'known-supported')
            self.assertEqual(self.run_engine(game,'--patch')['overall_status'],'installed')
            for item in load_profile()['targets'].values():
                self.assertEqual(sha256_file(game/item['path']),item['known_patched_sha256'])
            self.assertEqual(self.run_engine(game,'--patch')['overall_status'],'already-installed-verified')
            self.assertEqual(self.run_engine(game,'--restore')['overall_status'],'restored')
            for item in load_profile()['targets'].values():
                self.assertEqual(sha256_file(game/item['path']),item['known_original_sha256'])

    def test_upgrade_legacy_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=self.fixture(Path(tmp))
            config=load_profile()['targets']
            store=BackupStore(game,game/'.thai_mod_installer/backups/silent-hill-3-thai',game_id='silent_hill_3_pc',mod_id='silent-hill-3-thai',mod_version='old')
            store.ensure_originals([BackupTarget(config[k]['path'],config[k]['known_original_sha256']) for k in ('executable','messages')])
            old_hashes={p.name:sha256_file(p) for p in store.files_dir.iterdir()}
            from games.silent_hill_3.operations import build_executable_candidate,build_msg_arc_candidate
            for key,builder in [('executable',build_executable_candidate),('messages',build_msg_arc_candidate)]:
                target=game/config[key]['path']
                output=Path(tmp)/target.name
                builder(target,output)
                shutil.copy2(output,target)
            installed=self.run_engine(game,'--patch')
            self.assertEqual(installed['committed_targets'],['data/pic.arc'])
            for name,digest in old_hashes.items():
                self.assertEqual(sha256_file(store.files_dir/name),digest)
            self.run_engine(game,'--restore')
            for item in config.values():
                self.assertEqual(sha256_file(game/item['path']),item['known_original_sha256'])

    def test_unknown_picture_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as tmp:
            game=self.fixture(Path(tmp))
            with (game/'data/pic.arc').open('r+b') as f:
                f.seek(-1,2)
                value=f.read(1)
                f.seek(-1,2)
                f.write(bytes([value[0]^1]))
            before={str(p):sha256_file(p) for p in [game/'sh3.exe',game/'data/msg.arc',game/'data/pic.arc']}
            self.run_engine(game,'--patch',10)
            for name,digest in before.items():
                self.assertEqual(sha256_file(Path(name)),digest)

if __name__=='__main__':
    unittest.main()
