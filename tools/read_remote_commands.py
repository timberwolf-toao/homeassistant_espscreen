"""The commands a remote of each integration takes, read from Home Assistant's source (GitHub #117, app 0.4.38).

    python tools/read_remote_commands.py <home-assistant/core checkout>          writes catalogue/_remote_commands.json
    python tools/read_remote_commands.py <checkout> --check                      fails when that file differs
    python tools/read_remote_commands.py <checkout> --check --ignore-pins --release
                                                       the commands only, against a release (tools/ha_release.py)

Home Assistant lists no commands for a remote entity: `remote.send_command` takes whatever the integration accepts. For
the integrations below that set is fixed in code, either in Home Assistant itself or in the library its manifest.json
pins (`requirements`). This reads it from there with Python's own parser, never by hand and never by importing the
library: the exact pinned version is fetched from PyPI (a wheel, else the sdist) into .esphome/remote-libs/. When Home
Assistant moves to a new version of a library, running this again gives that version's keys.

The editor offers these in the command field of Perform action > Send command; a typed command still goes out as typed,
so a learned code (Broadlink), a hub's own names (Harmony) or a raw code keeps working. Integrations whose names come
from the device or the user's own configuration (Harmony, Broadlink, Bravia, Jellyfin, iTach, Kira, Xiaomi) or that pass
any text through (Samsung, Philips) have no list here.
"""
import ast
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'catalogue/_remote_commands.json'
CACHE = ROOT / '.esphome/remote-libs'


# ---- Reading Python source ----

def tree(path):
    return ast.parse(Path(path).read_text())


def assigned(module, name):
    """The value node of a module-level NAME = ... (or NAME: T = ...)."""
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    raise LookupError(name)


def strings(node):
    """The text keys of a dict, or the text items of a list, tuple, set or frozenset(...)."""
    if isinstance(node, ast.Call) and node.args:
        return strings(node.args[0])
    items = node.keys if isinstance(node, ast.Dict) else node.elts if isinstance(node, (ast.List, ast.Tuple, ast.Set)) else []
    return [item.value for item in items if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def class_body(module, name):
    for node in ast.walk(module):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node.body
    raise LookupError(name)


def members(module, name, value=False, kind=None):
    """An enum's or a constant class's members: their names, or with `value` their text values; `kind` keeps only
    members whose value is of that type."""
    found = []
    for node in class_body(module, name):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and not node.targets[0].id.startswith('_'):
            constant = node.value.value if isinstance(node.value, ast.Constant) else None
            if kind is not None and not isinstance(constant, kind):
                continue
            found.append(constant if value else node.targets[0].id)
    return [item for item in found if isinstance(item, str)]


def named_values(module, name):
    """{member: text} of a class whose members are text constants."""
    return {node.targets[0].id: node.value.value for node in class_body(module, name)
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}


def methods(module, name, decorator):
    """The async methods of a class that carry `@decorator(...)` and need no argument besides self."""
    found = []
    for node in class_body(module, name):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        marked = any(isinstance(d, ast.Call) and getattr(d.func, 'id', None) == decorator for d in node.decorator_list)
        required = len(node.args.args) - 1 - len(node.args.defaults)
        if marked and required == 0 and not node.args.kwonlyargs:
            found.append(node.name)
    return found


def unique(items):
    return list(dict.fromkeys(items))


# ---- Home Assistant and its pinned libraries ----

class Source:
    def __init__(self, core):
        self.core = core
        self.used = {}

    def component(self, domain, name='remote.py'):
        self.used.setdefault(domain, []).append(f'homeassistant/components/{domain}/{name}')
        return tree(self.core / 'homeassistant/components' / domain / name)

    def pin(self, domain, package):
        """`package==version` as the integration's manifest.json requires it."""
        manifest = json.loads((self.core / 'homeassistant/components' / domain / 'manifest.json').read_text())
        wanted = re.sub(r'[-_.]+', '-', package).lower()
        for requirement in manifest.get('requirements', []):
            name, _, version = requirement.partition('==')
            name = name.split('[', 1)[0]   # androidtv[async]: the extras are no part of the name
            if re.sub(r'[-_.]+', '-', name).lower() == wanted and version:
                return name, version
        raise LookupError(f'{domain} pins no {package}')

    def library(self, domain, package, path):
        """A file of the library the integration pins, fetched once per version."""
        name, version = self.pin(domain, package)
        folder = CACHE / f'{re.sub(r"[-_.]+", "-", name).lower()}-{version}'
        if not folder.exists():
            fetch(name, version, folder)
        found = sorted(folder.rglob(path))
        if not found:
            raise LookupError(f'{name}=={version} has no {path}')
        self.used.setdefault(domain, []).append(f'{name}=={version} {path}')
        return found[0]


def fetch(name, version, folder):
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as answer:
        files = json.load(answer)['urls']
    wheel = next((f for f in files if f['filename'].endswith('-none-any.whl')), None)
    chosen = wheel or next(f for f in files if f['packagetype'] == 'sdist')
    with urllib.request.urlopen(chosen['url'], timeout=120) as answer:
        data = answer.read()
    folder.mkdir(parents=True)
    if chosen['filename'].endswith('.whl') or chosen['filename'].endswith('.zip'):
        zipfile.ZipFile(io.BytesIO(data)).extractall(folder)
    else:
        tarfile.open(fileobj=io.BytesIO(data)).extractall(folder, filter='data')


# ---- One rule per integration: where its commands are, as its remote.py reads them ----

# Android's whole key table also holds a keyboard, a phone and game pads; a TV remote has none of those keys.
NOT_ON_A_REMOTE = re.compile(r'^(UNKNOWN|[A-Z]|F\d+|NUMPAD_\w+|BUTTON_\w+|(META|CTRL|ALT|SHIFT)_\w+|CALL|ENDCALL|HEADSETHOOK|'
                             r'DEMO_APP_\d|SOFT_\w+|SYSRQ|BREAK|SCROLL_LOCK|CAPS_LOCK|NUM_LOCK|FUNCTION|SYM|EXPLORER|ENVELOPE|'
                             r'CONTACTS|CALENDAR|CALCULATOR|CAMERA|FOCUS|POUND|STAR|AT|PLUS|MINUS|EQUALS|COMMA|PERIOD|SLASH|'
                             r'BACKSLASH|SEMICOLON|APOSTROPHE|GRAVE|LEFT_BRACKET|RIGHT_BRACKET|TAB|SPACE|FORWARD_DEL|DEL|'
                             r'MOVE_HOME|MOVE_END|INSERT|NUM|PICTSYMBOLS|SWITCH_CHARSET|MUHENKAN|HENKAN|KATAKANA_HIRAGANA|'
                             r'YEN|RO|KANA|EISU|ZENKAKU_HANKAKU|LANGUAGE_SWITCH|COPY|CUT|PASTE|STEM_\w+|NAVIGATE_\w+|'
                             r'SYSTEM_NAVIGATION_\w+|DPAD_(UP|DOWN)_(LEFT|RIGHT))$')


def androidtv_remote(source):
    # remote.py strips SHORT:/START_LONG:/END_LONG:; androidtvremote2 upper-cases a key and adds KEYCODE_.
    stub = source.library('androidtv_remote', 'androidtvremote2', 'remotemessage_pb2.pyi').read_text()
    keys = unique(re.findall(r'^\s*KEYCODE_(\w+): RemoteKeyCode\.ValueType', stub, re.M))
    return [key for key in keys if not NOT_ON_A_REMOTE.match(key)]


def androidtv(source):
    # remote.py: a name in KEYS becomes `input keyevent <code>`; anything else runs as an adb shell command.
    return strings(assigned(tree(source.library('androidtv', 'androidtv', 'androidtv/constants.py')), 'KEYS'))


def apple_tv(source):
    # remote.py: COMMAND_TO_ATTRIBUTE first, then a method of pyatv's RemoteControl by that name.
    own = strings(assigned(source.component('apple_tv'), 'COMMAND_TO_ATTRIBUTE'))
    control = methods(tree(source.library('apple_tv', 'pyatv', 'pyatv/interface.py')), 'RemoteControl', 'feature')
    return unique(control + own)


def roku(source):
    # rokuecp lower-cases a key and checks it against VALID_REMOTE_KEYS.
    return strings(assigned(tree(source.library('roku', 'rokuecp', 'rokuecp/const.py')), 'VALID_REMOTE_KEYS'))


def sky_remote(source):
    return strings(assigned(tree(source.library('sky_remote', 'skyboxremote', 'skyboxremote/skyboxremote.py')), '_KEY_MAP'))


def directv(source):
    return strings(assigned(tree(source.library('directv', 'directv', 'directv/const.py')), 'VALID_REMOTE_KEYS'))


def lg_netcast(source):
    # remote.py: VALID_COMMANDS is every int attribute of LG_COMMAND not starting with _.
    return members(tree(source.library('lg_netcast', 'pylgnetcast', 'pylgnetcast/pylgnetcast.py')), 'LG_COMMAND', kind=int)


def panasonic_viera(source):
    # __init__.py: getattr(Keys, key.upper()), so a member's name.
    return [n.targets[0].id for n in class_body(tree(source.library('panasonic_viera', 'panasonic_viera', 'panasonic_viera/keys.py')), 'Keys')
            if isinstance(n, ast.Assign)]


def vizio(source):
    # remote.py lower-cases a command and looks it up in the device's keys and REMOTE_KEY_ALIASES.
    keys = [value.lower() for value in members(tree(source.library('vizio', 'vizaio', 'vizaio/_keys.py')), 'RemoteKey', value=True)]
    # REMOTE_KEY_ALIASES: {native key: [its friendly names]}; HA drops an alias whose key the library lacks.
    table = assigned(source.component('vizio'), 'REMOTE_KEY_ALIASES')
    aliases = [alias for key, names in zip(table.keys, table.values) if key.value.lower() in keys for alias in strings(names)]
    return unique(keys + aliases)


def xbox(source):
    # remote.py: a member of InputKeyType is a button press, a key of MAP_COMMAND a command of its own.
    buttons = members(tree(source.library('xbox', 'python-xbox', 'pythonxbox/api/provider/smartglass/models.py')), 'InputKeyType', value=True)
    return unique(buttons + strings(assigned(source.component('xbox'), 'MAP_COMMAND')))


def kaleidescape(source):
    return strings(assigned(source.component('kaleidescape'), 'VALID_COMMANDS'))


def jvc_projector(source):
    # remote.py: COMMANDS lists cmd.Remote.<NAME>; the text each stands for is in pyjvcprojector's class Remote.
    names = [node.attr for node in assigned(source.component('jvc_projector'), 'COMMANDS').elts if isinstance(node, ast.Attribute)]
    values = named_values(tree(source.library('jvc_projector', 'pyjvcprojector', 'jvcprojector/command/command.py')), 'Remote')
    missing = [name for name in names if name not in values]
    if missing:
        raise SystemExit(f'jvc_projector: {missing} are not in pyjvcprojector\'s class Remote')
    return [values[name] for name in names]


def lyngdorf(source):
    return members(tree(source.library('lyngdorf', 'lyngdorf', 'lyngdorf/remote.py')), 'RemoteKey', value=True)


RULES = {rule.__name__: rule for rule in (androidtv_remote, androidtv, apple_tv, roku, sky_remote, directv, lg_netcast,
                                           panasonic_viera, vizio, xbox, kaleidescape, jvc_projector, lyngdorf)}


def output(core):
    source = Source(core)
    platforms = {}
    for domain, rule in RULES.items():
        if not (core / 'homeassistant/components' / domain / 'remote.py').exists():
            continue
        commands = rule(source)
        if not commands:
            raise SystemExit(f'{domain}: no commands found where its rule looks; read its remote.py again')
        platforms[domain] = {'from': unique(source.used.get(domain, [])), 'commands': commands}
    commit = subprocess.run(['git', '-C', str(core), 'log', '-1', '--format=%h %cs'], capture_output=True, text=True).stdout.strip()
    version = next((line.split('=')[1].strip().strip('"') for line in (core / 'pyproject.toml').read_text().splitlines()
                    if line.startswith('version')), '?')
    return json.dumps({'source': f'home-assistant/core {version} ({commit})', 'platforms': platforms}, indent=1) + '\n'


def compared(platforms):
    """What a --check holds: everything, or with --ignore-pins each integration's commands alone."""
    if platforms is None or '--ignore-pins' not in sys.argv:
        return platforms
    return {name: {'commands': item['commands']} for name, item in platforms.items()}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    text = output(Path(sys.argv[1]).resolve())
    if '--check' in sys.argv:
        # --ignore-pins: the commands per integration only, not the library versions they were read from (a screen sends
        # the command, never the version). --release: see tools/ha_release.py.
        import ha_release
        kept = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'source': '', 'platforms': None}
        found = json.loads(text)
        ok, lines = ha_release.check(*(compared(data['platforms']) for data in (kept, found)), kept['source'], found['source'],
                                     '--release' in sys.argv)
        print('\n'.join(lines))
        if not ok:
            sys.exit('catalogue/_remote_commands.json differs from this Home Assistant: run tools/read_remote_commands.py without --check.')
    else:
        OUTPUT.write_text(text)
        print(f'wrote {OUTPUT.relative_to(ROOT)}: ' + ', '.join(f'{d} {len(p["commands"])}' for d, p in json.loads(text)['platforms'].items()))
