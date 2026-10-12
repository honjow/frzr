"""Cross-repo protocol tests; read real candidate, execute only extracted checkpoint.
Set INSTALL_MEDIA_ROOT to a paired frontend checkout when it is not a sibling.
No bootstrap top-level code or device commands are executed.
"""
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_bootstrap import SOURCE, DISK, EFI, ROOT, HOME, run

FRONTEND = Path(os.environ.get('INSTALL_MEDIA_ROOT', str(SOURCE.parents[1] / 'install-media')))
LIB = FRONTEND / 'skorionos/airootfs/usr/local/lib'
sys.path.insert(0, str(LIB))

@unittest.skipUnless((LIB / 'installer/engine/bootstrap.py').exists(), 'Paired frontend checkout required')
class PairedProtocolTests(unittest.TestCase):
    def test_actual_candidate_marker_read_only(self):
        from installer.engine.bootstrap import require_safe_backend
        require_safe_backend(str(SOURCE))  # opens the file; never executes it
        header = SOURCE.read_bytes()[:8192].splitlines()
        self.assertEqual(header.count(b'# FRZR_INSTALLER_PROTOCOL=1'), 1)

    def test_classification_decision_parity(self):
        from installer.engine.detection import classify_inventory
        cases = [DISK, '\n'.join([DISK, EFI, ROOT]), '\n'.join([DISK, ROOT]),
                 '\n'.join([DISK, HOME]), '\n'.join([DISK, EFI, ROOT, HOME]),
                 '\n'.join([DISK, EFI, ROOT.replace('uuid-2', 'uuid-1')]),
                 '\n'.join([DISK, EFI, ROOT.replace('/dev/FAKE', '/dev/OTHER')]),
                 '\n'.join([DISK, EFI, ROOT.replace('btrfs', 'ext4')]),
                 '\n'.join([DISK, EFI.replace('frzr_efi', 'old_frzr_efi'), ROOT])]
        for snapshot in cases:
            inventory = {'blockdevices': [{key.lower(): val for key, val in
                         (field.split('=', 1) for field in shlex.split(line))}
                         for line in snapshot.splitlines()]}
            python_state = classify_inventory('/dev/FAKE', inventory).status
            shell = run('inspect_frzr_installation; echo "$FRZR_DETECTION_STATE"', snapshot)
            self.assertEqual(shell.stdout.strip(), python_state)

    def test_real_runner_with_extracted_shell_checkpoint(self):
        from installer.engine.runner import CommandRunner
        from installer.engine.events import EventKind
        checkpoint = re.search(r'^function frzr_checkpoint\(\) \{\n.*?^}',
                               SOURCE.read_text(), re.M | re.S).group()
        events = []
        entered = threading.Event()
        results = []
        errors = []
        def callback(event):
            events.append(event)
            if 'PROTECTED_READY' in event.message:
                entered.set()
        runner = CommandRunner(callback)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'INSTALLER_DRY_RUN': '0'}):
            script = Path(tmp) / 'checkpoint-only.sh'
            script.write_text('#!/bin/bash\n' + checkpoint + '\n'
                              'echo "@@FRZR_STAGE fixture protected"\n'
                              'echo PROTECTED_READY\n'
                              'for ((i=0;i<300;i++)); do [[ -e "$FRZR_CANCEL_FILE" ]] && break; sleep .01; done\n'
                              'frzr_checkpoint fixture_complete\n'
                              'echo SHOULD_NOT_RUN\n')
            def work():
                try: results.append(runner.run(['/bin/bash', str(script)], stage='bootstrap'))
                except Exception as exc: errors.append(exc)
            thread = threading.Thread(target=work)
            thread.start()
            self.assertTrue(entered.wait(4), errors)
            self.assertEqual(runner.cancel(), 'deferred')
            thread.join(6)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(results[0].returncode, 130)
            self.assertTrue(results[0].cancelled)
            self.assertNotIn('SHOULD_NOT_RUN', results[0].output)
            self.assertTrue(any(e.kind == EventKind.STAGE and e.stage == 'fixture_complete' for e in events))

if __name__ == '__main__': unittest.main(verbosity=2)
