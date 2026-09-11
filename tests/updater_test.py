"""Exercise atomic publication, failed collectors, flag forwarding, and overlap."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class Updater(unittest.TestCase):
    def test_success_failure_and_concurrent_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            local = home/'plugin/bin'
            stock = home/'stock/bin'
            local.mkdir(parents=True)
            stock.mkdir(parents=True)
            shutil.copy('bin/openusage-update', local/'openusage-update')
            paths = {}
            for provider in ('claude', 'codex', 'cursor', 'opencode', 'grok'):
                path = stock/f'omarchy-agent-usage-{provider}' if provider in ('claude', 'codex') else local/f'openusage-{provider}'
                path.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps('+repr(dict(schemaVersion=1,id=provider,limits=[dict(label='Weekly',percent=.4)]))+',))\nassert sys.argv[1] in ("--force", "--limits-only")\n')
                path.chmod(0o755)
                paths[provider] = path
            env = dict(os.environ, HOME=str(home), OMARCHY_PATH=str(home/'stock'))
            command = [str(local/'openusage-update'), '--force']
            subprocess.run(command, env=env, check=True)
            state = home/'.local/state/openusage'
            before = (state/'cursor.json').read_bytes()
            paths['cursor'].write_text('#!/bin/sh\nprintf "invalid json"\n')
            self.assertNotEqual(subprocess.run(command, env=env, capture_output=True).returncode, 0)
            self.assertEqual((state/'cursor.json').read_bytes(), before)
            jobs = [subprocess.Popen(command, env=env, stderr=subprocess.DEVNULL) for _ in range(2)]
            for job in jobs:
                self.assertNotEqual(job.wait(timeout=10), 0)
            for path in state.glob('*.json'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(path.read_text())['schemaVersion'], 1)
            self.assertEqual(len(list(state.glob('.*'))), 0)


if __name__ == '__main__':
    unittest.main()
