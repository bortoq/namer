"""Restoration scripts must recover actual renames without overwriting files."""

import json
import os
import subprocess

import pytest

from namer import core
from namer.cli import build_parser, main
from namer.restore import RestoreScript


@pytest.fixture
def names(monkeypatch):
    targets = {}

    def generate(path, **kwargs):
        basename = os.path.basename(path)
        return targets.get(basename, basename), {'title': 'Movie', 'is_series': False}

    monkeypatch.setattr(core, 'generate_new_name', generate)
    return targets


def entries(script):
    return [json.loads(line[len('# namer-restore: '):])
            for line in script.read_text().splitlines()
            if line.startswith('# namer-restore: ')]


def run(script, cwd):
    return subprocess.run([str(script)], cwd=cwd, capture_output=True, text=True)


def test_cli_backup_default_and_named():
    parser = build_parser()
    assert parser.parse_args([]).backup is False
    assert parser.parse_args(['-b']).backup is True
    assert parser.parse_args(['-b', 'undo']).backup == 'undo'
    assert parser.parse_args(['--backup', 'undo']).backup == 'undo'
    with pytest.raises(SystemExit):
        parser.parse_args(['-b', '-n'])


@pytest.mark.parametrize('explicit', [False, True])
def test_cli_renames_and_creates_executable_restore(tmp_path, monkeypatch, names, explicit):
    media = tmp_path / 'media'
    media.mkdir()
    source = media / 'original.mkv'
    source.write_bytes(b'video bytes')
    names[source.name] = 'New.mkv'
    monkeypatch.chdir(tmp_path)
    args = ['-d', str(media), '-b'] + (['custom undo'] if explicit else [])
    assert main(args) == 0
    script = tmp_path / 'custom undo' if explicit else media / 'namer-restore.py'
    assert os.access(script, os.X_OK)
    assert not source.exists()
    assert (media / 'New.mkv').read_bytes() == b'video bytes'
    # The script works independently of namer and from another directory.
    result = run(script, tmp_path)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == b'video bytes'
    assert not (media / 'New.mkv').exists()
    assert run(script, tmp_path).returncode == 0


def test_nested_paths_shell_characters_and_actual_collision_name(tmp_path, names):
    directory = tmp_path / "media ' $(touch hacked)"
    nested = directory / 'subfolder'
    nested.mkdir(parents=True)
    source = nested / "old ' `touch hacked` $HOME\nимя.mkv"
    source.write_bytes(b'original')
    occupied = nested / 'New？.mkv'
    occupied.write_bytes(b'other')
    names[source.name] = 'New?.mkv'
    assert core.process_directory(str(directory), backup=True) == (1, 2, 0)
    script = directory / 'namer-restore.py'
    assert entries(script)[0][:2] == [str(nested / 'New？_1.mkv'), str(source)]
    result = run(script, tmp_path)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == b'original'
    assert occupied.read_bytes() == b'other'
    assert not (tmp_path / 'hacked').exists()


def test_restore_reverses_dependent_renames(tmp_path, names):
    (tmp_path / 'A.mkv').write_bytes(b'first')
    (tmp_path / 'C.mkv').write_bytes(b'second')
    names.update({'A.mkv': 'B.mkv', 'C.mkv': 'A.mkv'})
    assert core.process_directory(str(tmp_path), backup=True) == (2, 2, 0)
    result = run(tmp_path / 'namer-restore.py', tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'A.mkv').read_bytes() == b'first'
    assert (tmp_path / 'C.mkv').read_bytes() == b'second'
    assert not (tmp_path / 'B.mkv').exists()


@pytest.mark.parametrize('conflict', ['file', 'symlink', 'replacement', 'missing'])
def test_restore_refuses_overwrite_or_wrong_file(tmp_path, names, conflict):
    source = tmp_path / 'old.mkv'
    source.write_bytes(b'original')
    names[source.name] = 'new.mkv'
    assert core.process_directory(str(tmp_path), backup=True) == (1, 1, 0)
    destination = tmp_path / 'new.mkv'
    if conflict == 'file':
        source.write_bytes(b'foreign')
    elif conflict == 'symlink':
        source.symlink_to(tmp_path / 'missing')
    elif conflict == 'replacement':
        # Hold the original inode to prevent immediate inode reuse.
        destination.rename(tmp_path / 'moved-away')
        destination.write_bytes(b'foreign')
    else:
        destination.unlink()
    result = run(tmp_path / 'namer-restore.py', tmp_path)
    assert result.returncode == 1
    if conflict == 'file':
        assert source.read_bytes() == b'foreign'
        assert destination.read_bytes() == b'original'
    elif conflict == 'symlink':
        assert source.is_symlink()
        assert destination.read_bytes() == b'original'
    elif conflict == 'replacement':
        assert destination.read_bytes() == b'foreign'


def test_automatic_script_names_preserve_existing_scripts(tmp_path):
    first = RestoreScript(str(tmp_path))
    first.close()
    original = (tmp_path / 'namer-restore.py').read_bytes()
    second = RestoreScript(str(tmp_path))
    second.close()
    assert os.path.basename(second.path) == 'namer-restore_1.py'
    assert (tmp_path / 'namer-restore.py').read_bytes() == original


def test_existing_named_script_prevents_renames(tmp_path, names):
    source = tmp_path / 'old.mkv'
    source.write_bytes(b'original')
    names[source.name] = 'new.mkv'
    script = tmp_path / 'undo'
    script.write_bytes(b'previous script')
    assert core.process_directory(str(tmp_path), backup=str(script)) == (0, 1, 1)
    assert source.read_bytes() == b'original'
    assert script.read_bytes() == b'previous script'


def test_journal_write_failure_prevents_move(tmp_path, monkeypatch, names):
    source = tmp_path / 'old.mkv'
    source.write_bytes(b'original')
    names[source.name] = 'new.mkv'

    def fail(*args):
        raise OSError('disk full')

    monkeypatch.setattr(RestoreScript, 'prepare', fail)
    assert core.process_directory(str(tmp_path), backup=True) == (0, 1, 1)
    assert source.read_bytes() == b'original'
    assert entries(tmp_path / 'namer-restore.py') == []


def test_racing_destination_only_records_success(tmp_path, monkeypatch):
    source = tmp_path / 'old.mkv'
    source.write_bytes(b'original')
    real_move = core._rename_no_clobber

    def race(src, dest):
        if os.path.basename(dest) == 'new.mkv':
            (tmp_path / 'new.mkv').write_bytes(b'foreign')
        return real_move(src, dest)

    monkeypatch.setattr(core, '_rename_no_clobber', race)
    script = RestoreScript(str(tmp_path))
    try:
        assert core.rename_file(str(source), 'new.mkv', restore_script=script)
    finally:
        script.close()
    assert len(entries(tmp_path / 'namer-restore.py')) == 1
    assert run(tmp_path / 'namer-restore.py', tmp_path).returncode == 0
    assert source.read_bytes() == b'original'
    assert (tmp_path / 'new.mkv').read_bytes() == b'foreign'


def test_interruption_preserves_completed_rename_and_pending_intent(tmp_path, monkeypatch, names):
    for basename in ['A.mkv', 'B.mkv']:
        (tmp_path / basename).write_bytes(basename.encode())
        names[basename] = 'new-' + basename
    real_move = core._rename_no_clobber

    def interrupt(src, dest):
        if os.path.basename(src) == 'B.mkv':
            raise KeyboardInterrupt
        return real_move(src, dest)

    monkeypatch.setattr(core, '_rename_no_clobber', interrupt)
    assert core.process_directory(str(tmp_path), backup=True) == (1, 2, 0)
    assert run(tmp_path / 'namer-restore.py', tmp_path).returncode == 0
    assert (tmp_path / 'A.mkv').read_bytes() == b'A.mkv'
    assert (tmp_path / 'B.mkv').read_bytes() == b'B.mkv'


def test_library_rejects_backup_with_dry_run(tmp_path):
    with pytest.raises(ValueError, match='mutually exclusive'):
        core.process_directory(str(tmp_path), backup=True, dry_run=True)


def test_empty_batch_creates_noop_script(tmp_path):
    assert core.process_directory(str(tmp_path), backup=True) == (0, 0, 0)
    script = tmp_path / 'namer-restore.py'
    assert entries(script) == []
    assert run(script, tmp_path).returncode == 0


def test_standalone_restore_falls_back_when_hardlinks_unsupported(tmp_path, monkeypatch):
    import errno
    import runpy

    try:
        core._get_renameat2()
    except OSError:
        pytest.skip('renameat2 unavailable')
    source = tmp_path / 'old.mkv'
    source.write_bytes(b'original')
    script = RestoreScript(str(tmp_path))
    try:
        assert core.rename_file(str(source), 'new.mkv', restore_script=script)
    finally:
        script.close()
    namespace = runpy.run_path(script.path, run_name='restore_test')

    def no_link(*args):
        raise OSError(errno.EPERM, 'hardlinks unsupported')

    monkeypatch.setattr(os, 'link', no_link)
    assert namespace['main']() == 0
    assert source.read_bytes() == b'original'
    assert not (tmp_path / 'new.mkv').exists()
