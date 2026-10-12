"""Safe source-extracted function tests. Never source/execute bootstrap top-level.
Every external disk command is a shell stub; no block device is touched.
"""
import os
import pathlib
import re
import subprocess
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[2] / 'frzr-bootstrap'
FUNCTIONS = '\n'.join(re.findall(r'^function [^\n]+\{\n.*?^}', SOURCE.read_text(), re.M | re.S))

def row(path, kind='part', parent='/dev/FAKE', label='', uuid='', fs=''):
    return ' '.join(f'{key}="{value}"' for key, value in zip(
        ['PATH', 'TYPE', 'PKNAME', 'LABEL', 'PARTUUID', 'FSTYPE'],
        [path, kind, parent, label, uuid, fs]))

DISK = row('/dev/FAKE', 'disk', '')
EFI = row('/dev/FAKE1', label='frzr_efi', uuid='uuid-1', fs='vfat')
ROOT = row('/dev/FAKE2', label='frzr_root', uuid='uuid-2', fs='btrfs')
HOME = row('/dev/FAKE3', label='frzr_home', uuid='uuid-3', fs='btrfs')

STUBS = r'''
DISK=/dev/FAKE; IS_NONINTERACTIVE=true; MOUNT_PATH=/tmp/frzr_root
lsblk() { printf '%s\n' "$SNAPSHOT"; return "${READ_RC:-0}"; }
timeout() { shift; "$@"; }
parted() { echo "MUTATION:parted:$*"; return "${PARTED_RC:-0}"; }
partprobe() { echo "MUTATION:partprobe:$*"; SNAPSHOT="$EMPTY_SNAPSHOT"; }
umount() { echo "MUTATION:umount:$*"; return "${UMOUNT_RC:-0}"; }
mount() { echo 'UNEXPECTED:mount'; return 99; }
findmnt() { if [[ "$*" = *TARGET* ]]; then printf "%s\n" "${MOUNT_TARGETS:-/}"; return "${FINDMNT_RC:-0}"; fi; return "${MOUNT_RC:-1}"; }
mkdir() { echo 'UNEXPECTED:mkdir'; return 99; }
rm() { echo 'UNEXPECTED:rm'; return 99; }
bootctl() { echo 'UNEXPECTED:bootctl'; return 99; }
whiptail() { return 255; }
'''

def run(code, snapshot=DISK, **env):
    e = {'PATH': '/usr/bin:/bin', 'SNAPSHOT': snapshot, 'EMPTY_SNAPSHOT': DISK, **env}
    return subprocess.run(['/bin/bash', '-c', FUNCTIONS + STUBS + code], text=True,
                          capture_output=True, env=e, timeout=3)

class BootstrapSafety(unittest.TestCase):
    def test_detection_matrix(self):
        cases = [
            ('none', DISK, 1, 'none'),
            ('complete', '\n'.join([DISK, EFI, ROOT]), 0, 'complete'),
            ('home', '\n'.join([DISK, EFI, ROOT, HOME]), 0, 'complete'),
            ('partial', '\n'.join([DISK, ROOT]), 2, 'incomplete'),
            ('home_only', '\n'.join([DISK, HOME]), 2, 'incomplete'),
            ('duplicates', '\n'.join([DISK, EFI, EFI, ROOT]), 3, 'ambiguous'),
            ('same_uuid', '\n'.join([DISK, EFI, ROOT.replace('uuid-2', 'uuid-1')]), 3, 'ambiguous'),
            ('substring', '\n'.join([DISK, EFI.replace('frzr_efi', 'not_frzr_efi_old'), ROOT]), 3, 'ambiguous'),
            ('cross_disk', '\n'.join([DISK, EFI, ROOT.replace('/dev/FAKE', '/dev/OTHER')]), 3, 'ambiguous'),
            ('wrong_fs', '\n'.join([DISK, EFI, ROOT.replace('btrfs', 'ext4')]), 3, 'ambiguous'),
            ('empty', '', 4, 'unknown'), ('malformed', 'LABEL="frzr_root"', 4, 'unknown'),
            ('missing_disk', ROOT, 4, 'unknown'),
        ]
        for name, snapshot, rc, state in cases:
            with self.subTest(name=name):
                p = run('inspect_frzr_installation; rc=$?; echo "$FRZR_DETECTION_STATE"; exit "$rc"', snapshot)
                self.assertEqual(p.returncode, rc, p.stderr)
                self.assertEqual(p.stdout.strip(), state)
                self.assertNotIn('integer expression expected', p.stderr)

    def test_read_failure_and_timeout_fail_closed(self):
        for rc in ['1', '124']:
            p = run('check_existing_installation', '\n'.join([DISK, EFI, ROOT]), READ_RC=rc)
            self.assertEqual(p.returncode, 4)
            self.assertNotIn('MUTATION', p.stdout)

    def test_cleanup_authorization(self):
        snapshot = '\n'.join([DISK, ROOT, HOME])
        good = {'FRZR_CLEANUP_DISK': '/dev/FAKE', 'FRZR_CLEANUP_PARTITIONS': '/dev/FAKE2|uuid-2\n/dev/FAKE3|uuid-3'}
        for changes in [{}, {'FRZR_CLEANUP_DISK': '/dev/OTHER'}, {'FRZR_CLEANUP_PARTITIONS': '/dev/FAKE2|uuid-2'}, {'FRZR_CLEANUP_PARTITIONS': '/dev/FAKE2|stale\n/dev/FAKE3|uuid-3'}]:
            env = {} if not changes else {**good, **changes}
            p = run('check_existing_installation', snapshot, **env)
            self.assertNotEqual(p.returncode, 1)
            self.assertNotIn('MUTATION', p.stdout)
        p = run('check_existing_installation', snapshot, **good)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('MUTATION:parted:-s /dev/FAKE rm 2', p.stdout)
        self.assertIn('MUTATION:parted:-s /dev/FAKE rm 3', p.stdout)
        p = run('check_existing_installation', snapshot, **good, PARTED_RC='1')
        self.assertEqual(p.returncode, 4)
        self.assertNotIn('partprobe', p.stdout)

    def test_main_never_installs_unknown_or_partial(self):
        code = 'handle_installation_choice() { echo MUTATION:install; }; main gamer /dev/FAKE dual'
        for snapshot in ['', ROOT, '\n'.join([DISK, ROOT]), '\n'.join([DISK, EFI, EFI, ROOT])]:
            p = run(code, snapshot)
            self.assertNotEqual(p.returncode, 0)
            self.assertNotIn('MUTATION', p.stdout)

    def test_menu_cancel_propagates(self):
        setup = 'IS_NONINTERACTIVE=false; detect_existing_systems() { :; }; show_system_info() { :; }; '
        for call in ['choose_install_type ""', 'choose_repair_or_reinstall ""', 'select_disk ""']:
            p = run(setup + call)
            self.assertEqual(p.returncode, 130, p.stdout + p.stderr)
        p = run(setup + 'filter_usable_free_spaces() { printf "1 100 99 60\\n200 400 200 70\\n"; }; SELECTED_FREE_SPACE_START_SECTORS=stale; select_free_space; rc=$?; echo "selected:$SELECTED_FREE_SPACE_START_SECTORS"; exit "$rc"')
        self.assertEqual(p.returncode, 130)
        self.assertIn('selected:\n', p.stdout)


    def test_cleanup_mount_failures_and_stale_snapshot(self):
        good = {'FRZR_CLEANUP_DISK': '/dev/FAKE', 'FRZR_CLEANUP_PARTITIONS': '/dev/FAKE2|uuid-2'}
        snapshot = '\n'.join([DISK, ROOT])
        for env in [{'MOUNT_RC': '2'}, {'MOUNT_RC': '127'}, {'MOUNT_RC': '0', 'UMOUNT_RC': '1'}]:
            p = run('cleanup_incomplete_installation', snapshot, **good, **env)
            self.assertEqual(p.returncode, 4)
            self.assertNotIn('MUTATION:parted', p.stdout)
        p = run('cleanup_incomplete_installation', snapshot.replace('uuid-2', 'changed'), **good)
        self.assertEqual(p.returncode, 4)
        self.assertNotIn('MUTATION', p.stdout)
        p = run('cleanup_incomplete_installation', snapshot, **good, FRZR_CANCEL_FILE=str(SOURCE))
        self.assertEqual(p.returncode, 130)
        self.assertNotIn('MUTATION', p.stdout)

    def test_mount_occupancy_fail_closed(self):
        for env in [{'MOUNT_TARGETS': '/\n/tmp/frzr_root'}, {'MOUNT_TARGETS': '/\n/tmp/frzr_root/boot'}, {'FINDMNT_RC': '2'}]:
            p = run('frzr_protected_stage fresh; echo MUTATION:write', **env)
            self.assertEqual(p.returncode, 4, p.stderr)
            self.assertNotIn('MUTATION', p.stdout)
        p = run('frzr_protected_stage fresh; echo READY')
        self.assertEqual(p.returncode, 0)
        self.assertIn('READY', p.stdout)


    def test_supported_dispatch_preserved(self):
        stubs = 'fresh_install() { echo DISPATCH:fresh; }; dual_boot_install() { echo DISPATCH:dual; }; repair_install() { echo DISPATCH:repair; }; '
        for snapshot, mode in [(DISK, 'fresh'), (DISK, 'dual'), ('\n'.join([DISK, EFI, ROOT]), 'repair'), ('\n'.join([DISK, EFI, ROOT]), 'fresh')]:
            p = run(stubs + f'main gamer /dev/FAKE {mode}', snapshot)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(f'DISPATCH:{mode}', p.stdout)

    def test_cleanup_postcheck_must_be_none(self):
        p = run('partprobe() { :; }; cleanup_incomplete_installation', '\n'.join([DISK, ROOT]),
                FRZR_CLEANUP_DISK='/dev/FAKE', FRZR_CLEANUP_PARTITIONS='/dev/FAKE2|uuid-2')
        self.assertEqual(p.returncode, 4)
        self.assertNotIn('cleanup_complete', p.stderr)

    def test_cancellation_checkpoint(self):
        p = run('frzr_protected_stage write; echo MUTATION:write', FRZR_CANCEL_FILE=str(SOURCE))
        self.assertEqual(p.returncode, 130)
        self.assertNotIn('MUTATION', p.stdout)
        self.assertNotIn('protected', p.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
