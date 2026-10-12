"""Extracted functions with curl/aria stubs only; no real network or deployment."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / '__frzr-deploy'
TEXT = SOURCE.read_text()
FUNCTIONS = '\n'.join(re.search(r'^' + name + r'\(\) \{\n.*?^}', TEXT, re.M | re.S).group()
                      for name in ['download_file', 'get_fallback_url_justlist'])

class DeployNetwork(unittest.TestCase):
    def run_shell(self, code, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            # Existing partial file reproduces old false success when curl fails.
            Path(tmp, 'image').write_text('partial fixture')
            return subprocess.run(['/bin/bash', '-c', 'set -o pipefail; exec 3>&1\n' + FUNCTIONS + '\n' + code],
                text=True, capture_output=True, timeout=3,
                env={'PATH': '/usr/bin:/bin', 'OUT': tmp, **extra})

    def test_curl_stall_propagates_before_deploy(self):
        code = r'''
command() { [[ "$*" != '-v aria2c' ]]; }
curl() { printf 'CURL %s\n' "$*" >&2; return 28; }
if download_file https://fixture.invalid/image "$OUT" image; then echo UNSAFE_DEPLOY; else exit 9; fi
'''
        p = self.run_shell(code)
        self.assertEqual(p.returncode, 9)
        self.assertNotIn('UNSAFE_DEPLOY', p.stdout)
        self.assertIn('--speed-limit 1 --speed-time 120 --retry 2', p.stderr)
        self.assertNotIn('--max-time', p.stderr)
        self.assertIn('transfer status 28', p.stderr)

    def test_download_policy_has_no_total_duration_cap(self):
        p = self.run_shell(r'''
command() { [[ "$*" != '-v aria2c' ]]; }
curl() { printf 'CURL %s\n' "$*" >&2; return 0; }
download_file https://fixture.invalid/image "$OUT" image
''')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('--max-time', p.stderr)
        self.assertIn('--speed-limit 1 --speed-time 120', p.stderr)

    def test_aria_stall_is_bounded_and_propagated(self):
        p = self.run_shell(r'''
command() { return 0; }
aria2c() { printf 'ARIA %s\n' "$*" >&2; return 2; }
if download_file https://fixture.invalid/image "$OUT" image; then echo UNSAFE_DEPLOY; else exit 9; fi
''')
        self.assertEqual(p.returncode, 9)
        self.assertNotIn('UNSAFE_DEPLOY', p.stdout)
        self.assertIn('--timeout=120 --lowest-speed-limit=1 --max-tries=3 --retry-wait=2', p.stderr)

    def test_metadata_failure_bounded_and_not_returned_as_url(self):
        p = self.run_shell(r'''
curl() { printf 'CURL %s\n' "$*" >&2; printf 'partial response'; return 28; }
get_fallback_url_justlist https://fixture.invalid image
''')
        self.assertEqual(p.returncode, 1)
        self.assertNotIn('partial response', p.stdout)
        self.assertEqual(p.stderr.count('--connect-timeout 10 --max-time 30 --retry 1 --retry-delay 2'), 2)


    def test_progress_filters_do_not_mask_downloader_status(self):
        for downloader in ('curl', 'aria2c'):
            for progress in ('steam', 'whiptail'):
                for rc in (0, 28):
                    setup = ('command() { return 0; }; ' if downloader == 'aria2c' else
                             "command() { [[ \"$*\" != '-v aria2c' ]]; }; ")
                    setup += f'{downloader}() {{ return {rc}; }}; '
                    setup += 'clean_progress_loop() { cat >/dev/null; }; whiptail() { cat >/dev/null; }; '
                    setup += 'FRZR_STEAM_PROGRESS=1; ' if progress == 'steam' else 'SHOW_UI=1; '
                    p = self.run_shell(setup + 'if download_file https://fixture.invalid/image "$OUT" image; then echo CONTINUE; else exit 9; fi')
                    self.assertEqual(p.returncode, 0 if rc == 0 else 9, (downloader, progress, p.stderr))
                    self.assertEqual('CONTINUE' in p.stdout, rc == 0)

    def test_all_download_ui_branches_carry_policy(self):
        function = re.search(r'^download_file\(\) \{\n.*?^}', TEXT, re.M | re.S).group()
        self.assertEqual(function.count('curl --connect-timeout 15 --speed-limit 1 --speed-time 120 --retry 2 --retry-delay 2 --fail'), 4)
        self.assertEqual(function.count('aria2c --connect-timeout=15 --timeout=120 --lowest-speed-limit=1 --max-tries=3 --retry-wait=2'), 4)

if __name__ == '__main__': unittest.main(verbosity=2)
