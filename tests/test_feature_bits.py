"""No Home Assistant feature bit is counted by hand (docs/CATALOGUE.md).

A tile's feature bits (supported_features) come from Home Assistant's own source: tools/read_ha_source.py reads them into
catalogue/_ha.json, and tools/generate_catalogue.py writes them by name into what every layer reads: tile_catalogue.h
for the firmware (tile_catalogue::cover::SET_TILT_POSITION), catalogue.bits() for the add-on and bits() of
web/src/model/catalogue.ts for the editor. This test reads the shared code of the three layers (generated files aside)
and fails where it tests a supported_features value against a number or defines a feature constant as a number, and it
holds the values those names replaced, so the change to names changed no behaviour.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'screen_manager/app'))
import catalogue  # noqa: E402

# Generated from the catalogue, the editor's build output and the compiled preview: not written by hand.
GENERATED = {'components/smart_display/tile_catalogue.h'}
SKIPPED_DIRS = ('screen_manager/app/static/', 'web/src/wasm/')
SUFFIXES = {'.h', '.hpp', '.cpp', '.py', '.ts', '.vue'}

NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)\b'
# Names that hold an entity's supported_features wherever they occur.
ALWAYS = {'supported_features', 'supported'}
# A name given a supported_features value in its file: `f = Number(a.supported_features || 0)`, `const uint32_t f=t.supported`,
# `features = attrs.get('supported_features')`.
ASSIGNED = re.compile(r'\b([A-Za-z_]\w*)\s*=(?!=)(?:[^;\n=,]|=>)*?(?:supported_features\b|(?:\.|->)supported\b)')
# A feature constant spelled as a number: EFFECT_FEATURE = 4, FEATURE_OPEN = 1, constexpr uint32_t COVER_FEATURES = 15.
CONSTANT = re.compile(r'\b[A-Z][A-Z0-9_]*FEATURES?[A-Z0-9_]*\s*=\s*' + NUMBER)
# A C++ `namespace feature { constexpr uint32_t ARM_HOME = 1, ... }` with numbers in it.
NAMESPACE = re.compile(r'namespace\s+features?\s*\{([^{}]*)\}')
# Bits paired with words and tested in one go: `for kind, bit in (('daily', 1), ('hourly', 2)) if features & bit`.
PAIRS = re.compile(r'for\s+\w+\s*,\s*(\w+)\s+in\s+[(\[]\s*[(\[]\s*[\'"]\w+[\'"]\s*,\s*' + NUMBER)

HELP = ('Home Assistant feature bits are named, never counted by hand: use tile_catalogue::<type>::<NAME> (firmware), '
        "catalogue.bits('<type>', 'NAME') (add-on) or bits('<type>', 'NAME') from model/catalogue.ts (editor). "
        'A bit the catalogue lacks is added from Home Assistant\'s source, see docs/CATALOGUE.md.')


def is_comment(line, suffix):
    text = line.strip()
    return text.startswith(('//', '/*', '*')) or (suffix == '.py' and text.startswith('#'))


def problems(text, suffix='.ts'):
    """Every place in one file's text that counts a feature bit by hand: (line number, line)."""
    names = ALWAYS | set(ASSIGNED.findall(text))
    held = '|'.join(sorted(map(re.escape, names), key=len, reverse=True))
    # `<name> & 4`, `t.supported & 4`, `features.value & 4` and `4 & <name>`; `&&` is not a bit test.
    tested = re.compile(rf'(?<![\w&])(?:{held})(?:\.value)?\s*\)?\s*&(?!&)\s*\(?\s*{NUMBER}'
                        rf'|(?<![\w&]){NUMBER}\s*&(?!&)\s*\(?\s*(?:[\w.\[\]\'"-]+?[.>])?(?:{held})\b')
    found = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if is_comment(line, suffix):
            continue
        code = line.split('//')[0] if suffix != '.py' else line.split(' #')[0]
        pair = PAIRS.search(code)
        if tested.search(code) or CONSTANT.search(code) or (pair and re.search(rf'&\s*{re.escape(pair.group(1))}\b', code)):
            found.append((number, line.strip()))
    if suffix in ('.h', '.hpp', '.cpp'):
        for block in NAMESPACE.finditer(text):
            if re.search(r'=\s*' + NUMBER, block.group(1)):
                number = text.count('\n', 0, block.start()) + 1
                found.append((number, lines[number - 1].strip()))
    return sorted(set(found))


def shared_files():
    for top in ('components', 'screen_manager/app', 'web/src'):
        for path in sorted((ROOT / top).rglob('*')):
            name = path.relative_to(ROOT).as_posix()
            if path.suffix in SUFFIXES and name not in GENERATED and not name.startswith(SKIPPED_DIRS) and 'node_modules' not in name:
                yield name, path


class FeatureBitsByName(unittest.TestCase):
    def test_no_shared_code_counts_a_feature_bit_by_hand(self):
        found = [f'{name}:{number}: {line}' for name, path in shared_files() for number, line in problems(path.read_text(errors='replace'), path.suffix)]
        self.assertEqual(found, [], HELP + '\n' + '\n'.join(found))

    def test_the_check_finds_what_was_counted_by_hand(self):
        # The lines this test replaced (app 0.4.40), each of which it must catch.
        caught = [
            ('constexpr uint32_t ARM_HOME = 1, ARM_AWAY = 2, ARM_NIGHT = 4;', '.h', 'namespace feature {\n%s\n}\n'),
            ('constexpr uint32_t OPEN = 1;', '.h', 'namespace feature {\n%s\n}\n'),
            ('constexpr uint32_t EFFECT_FEATURE = 4;', '.h', '%s\n'),
            ('EFFECT_FEATURE = 4', '.py', '%s\n'),
            ("    return frozenset(kind for kind, bit in (('daily', 1), ('hourly', 2)) if features & bit)", '.py',
             "    features = (attributes or {}).get('supported_features')\n%s\n"),
            ("  return f & 128 ? 'position' : f & 112 ? 'buttons' : '';", '.ts', '  const f = Number(a.supported_features || 0);\n%s\n'),
            ("    ...(f & 16 ? [{ icon: 'blinds-open' }] : []),", '.ts', '  const f = Number(a.supported_features || 0), value = 1;\n%s\n'),
            ('  if ((f & 1 && a.temperature != null) || !(f & 2)) return null;', '.vue',
             '  const a = current.value?.a || {}, f = Number(a.supported_features || 0);\n%s\n'),
            ('<span v-if="features & 4" class="range"></span>', '.vue',
             'const features = computed(() => Number(current.value?.a?.supported_features || 0));\n%s\n'),
            ('  if (t.supported & 512) locate();', '.h', '%s\n'),
            ('  bool ok = 4 & t->supported;', '.h', '%s\n'),
        ]
        for line, suffix, around in caught:
            with self.subTest(line=line):
                self.assertTrue(problems(around % line, suffix), f'not caught: {line}')

    def test_the_check_leaves_other_bit_fields_alone(self):
        fine = [
            ("  return f & bits('cover', 'SET_TILT_POSITION') ? 'position' : '';", '.ts', '  const f = Number(a.supported_features || 0);\n%s\n'),
            ('  if (t.supported & tile_catalogue::light::EFFECT) open();', '.h', '%s\n'),
            ('  lamp.color = caps & 1; lamp.temperature = caps & 2;', '.cpp', '%s\n'),
            ('  return (cp >> 12 & 0x3F) | (mask & 1);', '.h', '%s\n'),
            ('  if (t.supported && ready & 1) go();', '.h', '%s\n'),
            ('// supported_features 512 is LOCATE', '.h', '%s\n'),
            ("EFFECT = catalogue.bits('light', 'EFFECT')", '.py', '%s\n'),
            ("namespace feature = tile_catalogue::lock;", '.h', '%s\n'),
        ]
        for line, suffix, around in fine:
            with self.subTest(line=line):
                self.assertEqual(problems(around % line, suffix), [])

    def test_the_names_keep_the_numbers_they_replaced(self):
        # The numbers Home Assistant gives these bits, which the hand-counted code had: naming them changed nothing.
        self.assertEqual([catalogue.bits('alarm_control_panel', name) for name in
                          ('ARM_HOME', 'ARM_AWAY', 'ARM_NIGHT', 'TRIGGER', 'ARM_CUSTOM_BYPASS', 'ARM_VACATION')], [1, 2, 4, 8, 16, 32])
        self.assertEqual(catalogue.bits('lock', 'OPEN'), 1)
        self.assertEqual(catalogue.bits('light', 'EFFECT'), 4)
        self.assertEqual((catalogue.bits('weather', 'FORECAST_DAILY'), catalogue.bits('weather', 'FORECAST_HOURLY')), (1, 2))
        self.assertEqual([catalogue.bits('cover', name) for name in ('SET_TILT_POSITION', 'OPEN_TILT', 'CLOSE_TILT', 'STOP_TILT')], [128, 16, 32, 64])
        self.assertEqual(catalogue.bits('cover', 'OPEN_TILT', 'CLOSE_TILT', 'STOP_TILT'), 112)
        self.assertEqual((catalogue.bits('climate', 'TARGET_TEMPERATURE'), catalogue.bits('climate', 'TARGET_TEMPERATURE_RANGE')), (1, 2))
        self.assertEqual((catalogue.bits('media_player', 'VOLUME_SET'), catalogue.bits('media_player', 'VOLUME_MUTE')), (4, 8))
        with self.assertRaises(KeyError):
            catalogue.bits('lock', 'NOT_A_FEATURE')
        import core
        import light_effects
        self.assertEqual(light_effects.EFFECT, 4)
        self.assertEqual(core.FORECAST_BITS, (('daily', 1), ('hourly', 2)))
        header = (ROOT / 'components/smart_display/tile_catalogue.h').read_text()
        for line in ('inline constexpr uint32_t ARM_HOME = 1;', 'inline constexpr uint32_t ARM_VACATION = 32;',
                     'inline constexpr uint32_t EFFECT = 4;', 'inline constexpr uint32_t SET_TILT_POSITION = 128;'):
            self.assertIn(line, header)
        self.assertIn('namespace feature = tile_catalogue::alarm_control_panel;', (ROOT / 'components/smart_display/alarm_panel.h').read_text())
        self.assertIn('namespace feature = tile_catalogue::lock;', (ROOT / 'components/smart_display/lock_panel.h').read_text())

    def test_the_firmware_header_names_what_it_closes_and_tools_that_exist(self):
        header = (ROOT / 'components/smart_display/tile_catalogue.h').read_text()
        opened = re.findall(r'^namespace (\w+) \{$', header, re.M)
        closed = re.findall(r'^\}  // namespace (\w+)$', header, re.M)
        self.assertEqual(closed, opened[1:] + opened[:1], 'every namespace closes under its own name, tile_catalogue last')
        for tool in re.findall(r'tools/\w+\.py', header):
            self.assertTrue((ROOT / tool).exists(), f'tile_catalogue.h names {tool}, which does not exist')


if __name__ == '__main__':
    unittest.main()
