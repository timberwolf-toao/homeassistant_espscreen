"""Comparing the Home Assistant facts we keep with those of a Home Assistant release (.github/workflows/ha-source.yml).

catalogue/_ha.json and catalogue/_remote_commands.json are read from a home-assistant/core checkout, often a dev build
ahead of the newest release. Held against that release, a snapshot that is newer may know more than it does: an action,
a flag or a command the release has not shipped yet is no fault. What is one is the release having something the
snapshot lacks, or saying something else about what both have (another bit for a flag, other flags for an action).

    tools/read_ha_source.py <checkout> --check --release
    tools/read_remote_commands.py <checkout> --check --release --ignore-pins

Without --release the comparison stays exact (tools/check.sh with HA_CORE). Standard library only.
"""
import re

STAGES = {'dev': 0, 'a': 1, 'b': 2, 'rc': 3}


def version(source):
    """The version in a `source` line ("home-assistant/core 2026.10.0.dev0 (dd2a9edc 2026-09-30)") as a tuple that
    sorts as Home Assistant's versions do: a dev build, a beta and a release candidate before the release itself."""
    found = re.search(r'(\d+)\.(\d+)\.(\d+)(?:\.?(dev|a|b|rc)(\d*))?', source or '')
    if not found:
        return None
    year, month, patch, stage, number = found.groups()
    return (int(year), int(month), int(patch), STAGES[stage] if stage else len(STAGES), int(number or 0))


def newer(snapshot_source, release_source):
    """Whether the snapshot was read from a later Home Assistant than the release."""
    ours, theirs = version(snapshot_source), version(release_source)
    return bool(ours and theirs and ours > theirs)


def differences(snapshot, release, path=''):
    """(faults, extras): what the release has that the snapshot lacks or contradicts, and what only the snapshot has.
    Dicts are compared key by key; a list of texts (commands, a type's actions) as a set, the release's items having to
    be in the snapshot; anything else (a flag's bit, the flags an action asks) must be equal."""
    faults, extras = [], []
    if isinstance(snapshot, dict) and isinstance(release, dict):
        for key in sorted(set(snapshot) | set(release)):
            where = f'{path}/{key}' if path else str(key)
            if key not in snapshot:
                faults.append(f'{where}: in the release, not in the snapshot')
            elif key not in release:
                extras.append(f'{where}: only in the snapshot')
            else:
                more_faults, more_extras = differences(snapshot[key], release[key], where)
                faults += more_faults
                extras += more_extras
    elif isinstance(snapshot, list) and isinstance(release, list) and all(isinstance(item, str) for item in snapshot + release):
        lacking = [item for item in release if item not in snapshot]
        added = [item for item in snapshot if item not in release]
        if lacking:
            faults.append(f'{path}: the release has {", ".join(lacking)}, the snapshot not')
        if added:
            extras.append(f'{path}: only the snapshot has {", ".join(added)}')
    elif snapshot != release:
        faults.append(f'{path}: the snapshot says {snapshot!r}, the release {release!r}')
    return faults, extras


def check(snapshot, release, snapshot_source, release_source, release_mode):
    """(ok, lines) for a --check: exact, or with `release_mode` and a newer snapshot, only the release's faults count."""
    if not release_mode or not newer(snapshot_source, release_source):
        if snapshot == release:
            return True, []
        faults, extras = differences(snapshot, release)
        return False, faults + extras
    faults, extras = differences(snapshot, release)
    lines = [f'The snapshot ({snapshot_source}) is newer than {release_source}: only what the release has counts.']
    lines += [f'fault: {line}' for line in faults] + [f'newer: {line}' for line in extras]
    return not faults, lines
