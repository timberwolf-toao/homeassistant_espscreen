"""Holding our Home Assistant snapshot against a Home Assistant release (tools/ha_release.py, .github/workflows/ha-source.yml).

A dev snapshot ahead of the release may know more; only what the release has and the snapshot lacks or contradicts
fails. A remote's commands are compared without the library pins they were read from (--ignore-pins)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ha_release  # noqa: E402

DEV = 'home-assistant/core 2026.10.0.dev0 (dd2a9edc 2026-09-30)'
RELEASE = 'home-assistant/core 2026.9.4 (9212531 2026-09-27)'
NEXT = 'home-assistant/core 2026.10.1 (1234567 2026-10-14)'


class Versions(unittest.TestCase):
    def test_versions_sort_as_home_assistants(self):
        order = ['2026.9.4', '2026.10.0.dev0', '2026.10.0b0', '2026.10.0b3', '2026.10.0rc1', '2026.10.0', '2026.10.1']
        self.assertEqual(sorted(order, key=lambda text: ha_release.version(text)), order)
        self.assertTrue(ha_release.newer(DEV, RELEASE))
        self.assertFalse(ha_release.newer(DEV, NEXT))
        self.assertFalse(ha_release.newer(RELEASE, RELEASE))
        self.assertIsNone(ha_release.version('home-assistant/core ? ()'))


class Comparison(unittest.TestCase):
    SNAPSHOT = {'light': {'features': {'EFFECT': 4, 'FLASH': 8}, 'actions': {'turn_on': [], 'toggle': [], 'new_one': []}},
                'roku': {'commands': ['home', 'back', 'play']}}

    def release(self, **change):
        data = json.loads(json.dumps(self.SNAPSHOT))
        for key, value in change.items():
            domain, *rest = key.split('__')
            target = data[domain]
            for part in rest[:-1]:
                target = target[part]
            if value is None:
                del target[rest[-1]]
            else:
                target[rest[-1]] = value
        return data

    def test_a_newer_snapshot_may_know_more(self):
        older = self.release(light__actions__new_one=None, roku__commands=['home', 'back'])
        ok, lines = ha_release.check(self.SNAPSHOT, older, DEV, RELEASE, release_mode=True)
        self.assertTrue(ok, lines)
        self.assertTrue(any('light/actions/new_one: only in the snapshot' in line for line in lines), lines)
        self.assertTrue(any('only the snapshot has play' in line for line in lines), lines)

    def test_what_the_release_adds_or_contradicts_fails(self):
        for name, release in {'a new action': self.release(light__actions__brand_new=[]),
                              'a new command': self.release(roku__commands=['home', 'back', 'play', 'mute']),
                              'another bit': self.release(light__features__FLASH=16),
                              'other flags for an action': self.release(light__actions__turn_on=[['EFFECT']]),
                              'a new type': {**self.SNAPSHOT, 'lock': {'features': {}}}}.items():
            with self.subTest(name):
                ok, lines = ha_release.check(self.SNAPSHOT, release, DEV, RELEASE, release_mode=True)
                self.assertFalse(ok)
                self.assertTrue(any(line.startswith('fault: ') for line in lines), lines)

    def test_without_release_mode_or_an_older_snapshot_it_is_exact(self):
        older = self.release(light__actions__new_one=None)
        self.assertFalse(ha_release.check(self.SNAPSHOT, older, DEV, RELEASE, release_mode=False)[0])
        self.assertFalse(ha_release.check(self.SNAPSHOT, older, DEV, NEXT, release_mode=True)[0])
        self.assertEqual(ha_release.check(self.SNAPSHOT, self.SNAPSHOT, DEV, RELEASE, release_mode=False), (True, []))


class Pins(unittest.TestCase):
    def compared(self, *flags):
        code = ('import sys, json; sys.argv = ["x", *json.loads(sys.argv[1])]; sys.path.insert(0, "tools"); '
                'import read_remote_commands as r; print(json.dumps(r.compared({"roku": {"from": ["rokuecp==0.19.0"], '
                '"commands": ["home"]}})))')
        run = subprocess.run([sys.executable, '-c', code, json.dumps(list(flags))], cwd=ROOT, capture_output=True, text=True, check=True)
        return json.loads(run.stdout)

    def test_ignore_pins_compares_the_commands_alone(self):
        self.assertEqual(self.compared('--check', '--ignore-pins'), {'roku': {'commands': ['home']}})
        self.assertEqual(self.compared('--check'), {'roku': {'from': ['rokuecp==0.19.0'], 'commands': ['home']}})

    def test_the_workflow_passes_the_flags_and_check_sh_does_not(self):
        workflow = (ROOT / '.github/workflows/ha-source.yml').read_text()
        self.assertIn('read_ha_source.py "$HA_CORE" --check --release', workflow)
        self.assertIn('read_remote_commands.py "$HA_CORE" --check --release --ignore-pins', workflow)
        check = (ROOT / 'tools/check.sh').read_text()
        self.assertNotIn('--release', check)
        self.assertNotIn('--ignore-pins', check)


if __name__ == '__main__':
    unittest.main()
