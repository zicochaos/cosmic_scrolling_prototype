"""Test staged uninstall and ownership checks without sudo or live desktop edits."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class SuiteScripts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cosmic-suite-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'suite with spaces'
        self.root.mkdir()
        self.stage = Path(self.temp.name) / 'staged root'
        self.comp = self.root / 'cosmic-comp-scrolling-prototype'
        self.comp.mkdir()
        for name in ('install.sh', 'uninstall.sh'):
            shutil.copy2(SOURCE / name, self.root / name)
        for name in ('install-scrolling-session.sh', 'start-scrolling-session.sh',
                     'cosmic-scrolling-test.desktop'):
            shutil.copy2(SOURCE / self.comp.name / name, self.comp / name)
        binary = self.comp / 'target/debug/cosmic-comp'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        self.config = self.comp / 'target/scrolling-test-config'
        self.config.mkdir()
        (self.config / 'keep').write_text('settings')
        self.state = self.root / '.cosmic-scrolling'
        self.prefix = self.state / 'prefix'
        (self.prefix / 'bin').mkdir(parents=True)
        (self.prefix / 'bin/cosmic-applet-tiling').write_text('private binary')
        (self.prefix / 'bin/cosmic-comp').symlink_to(binary)
        (self.state / 'manifest').write_text('owner=cosmic-scrolling-prototype-v1\n')
        (self.state / 'session-config').mkdir()
        (self.state / 'session-config/keep').write_text('session settings')
        (self.state / 'cache').write_text('retained build')
        self.suite_config = self.state / 'session-config'
        self.env = dict(os.environ)
        self.env.pop('DESTDIR', None)
        self.env.pop('XDG_CONFIG_HOME', None)
        mock = self.root / 'mock-bin'
        mock.mkdir()
        sudo = mock / 'sudo'
        sudo.write_text('#!/bin/sh\necho UNEXPECTED_SUDO >&2\nexit 99\n')
        sudo.chmod(0o755)
        self.env['PATH'] = str(mock) + ':' + os.defpath
        self.run_script(self.comp / 'install-scrolling-session.sh', '--destdir', self.stage)
        self.desktop = self.stage / 'usr/share/wayland-sessions/cosmic-scrolling-test.desktop'
        self.launcher = self.stage / 'usr/local/bin/cosmic-scrolling-test-session'
        self.normal = self.desktop.parent / 'cosmic.desktop'
        self.normal.write_text('distribution session')

    def run_script(self, script, *args, code=0, env=None):
        p = subprocess.run([str(script), *map(str, args)], env=env or self.env,
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p

    def uninstall(self, *args, **kwargs):
        return self.run_script(self.root / 'uninstall.sh', '--destdir', self.stage,
                               *args, **kwargs)

    def assert_untouched(self):
        self.assertTrue(self.desktop.exists())
        self.assertTrue(self.suite_config.exists())
        self.assertTrue((self.state / 'manifest').exists())
        self.assertTrue(self.config.exists())

    def test_uninstall_is_idempotent_and_preserves_normal_session_cache_and_config(self):
        self.uninstall()
        self.uninstall()
        self.assertFalse(self.launcher.is_symlink())
        self.assertFalse(self.desktop.exists())
        self.assertFalse((self.state / 'manifest').exists())
        self.assertEqual(self.normal.read_text(), 'distribution session')
        self.assertEqual((self.state / 'cache').read_text(), 'retained build')
        self.assertEqual((self.config / 'keep').read_text(), 'settings')

    def test_purge_removes_new_and_legacy_isolated_config(self):
        self.uninstall('--purge-config')
        self.assertFalse(self.config.exists())
        self.assertFalse(self.suite_config.exists())
        self.assertTrue((self.comp / 'target/debug/cosmic-comp').exists())
        self.assertTrue((self.state / 'cache').exists())
        self.assertTrue(self.normal.exists())

    def test_foreign_launcher_prevents_all_removals(self):
        self.launcher.unlink()
        self.launcher.symlink_to('/another/clone/start-scrolling-session.sh')
        self.uninstall(code=1)
        self.assert_untouched()

    def test_foreign_desktop_prevents_all_removals(self):
        self.desktop.write_text('foreign')
        self.uninstall(code=1)
        self.assert_untouched()
        self.assertEqual(self.desktop.read_text(), 'foreign')

    def test_desktop_symlink_is_refused(self):
        target = self.root / 'owned-looking.desktop'
        self.desktop.rename(target)
        self.desktop.symlink_to(target)
        self.uninstall(code=1)
        self.assert_untouched()
        self.assertTrue(target.exists())

    def test_redirected_private_prefix_is_refused(self):
        elsewhere = self.root / 'unrelated'
        self.prefix.rename(elsewhere)
        self.prefix.symlink_to(elsewhere)
        self.uninstall(code=1)
        self.assert_untouched()
        self.assertTrue((elsewhere / 'bin/cosmic-applet-tiling').exists())

    def test_active_session_is_refused_before_removal(self):
        self.uninstall('--purge-config', code=1,
                       env=dict(self.env, XDG_CONFIG_HOME=str(self.config)))
        self.assert_untouched()

    def test_active_session_is_refused_for_suite_config_location(self):
        self.uninstall('--purge-config', code=1,
                       env=dict(self.env, XDG_CONFIG_HOME=str(self.suite_config)))
        self.assert_untouched()

    def test_invalid_profile_is_rejected_before_any_work(self):
        for value in ('release', 'Debug', 'fastdebug ', 'debug,fastdebug', 'fast'):
            result = self.run_script(self.root / 'install.sh', '--build-only', code=1,
                                     env=dict(self.env, SCROLLING_PROFILE=value))
            self.assertIn('SCROLLING_PROFILE', result.stderr)
        self.assert_untouched()

    def test_destdir_environment(self):
        self.run_script(self.root / 'uninstall.sh', env=dict(self.env, DESTDIR=str(self.stage)))
        self.assertFalse(self.desktop.exists())

    def test_invalid_arguments_do_not_change_installation(self):
        for script in ('install.sh', 'uninstall.sh'):
            for args in (('--unknown',), ('--destdir',), ('--destdir', 'relative')):
                self.run_script(self.root / script, *args, code=1)
                self.assert_untouched()


class InstallerBuild(unittest.TestCase):
    """Run install.sh --build-only against mock cargo/git tooling.

    Covers the compositor test/build ordering, the SCROLLING_PROFILE knob, the
    ownership manifest contents, the prefix symlink, and the workspace
    manifest rewrite without network access, real builds, or sudo.
    """

    REV = '0123456789abcdef0123456789abcdef01234567'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cosmic-install-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'suite with spaces'
        self.root.mkdir()
        self.comp = self.root / 'cosmic-comp-scrolling-prototype'
        self.comp.mkdir()
        shutil.copy2(SOURCE / 'install.sh', self.root / 'install.sh')
        for name in ('install-scrolling-session.sh', 'start-scrolling-session.sh',
                     'cosmic-scrolling-test.desktop'):
            shutil.copy2(SOURCE / self.comp.name / name, self.comp / name)
        (self.comp / 'Cargo.toml').write_text('[package]\nname = "cosmic-comp"\n')
        (self.comp / 'cosmic-comp-config').mkdir()
        (self.comp / 'cosmic-comp-config/Cargo.toml').write_text(
            '[package]\nname = "cosmic-comp-config"\n')
        applet = self.root / 'cosmic-ext-applet-scrolling-tiling'
        (applet / 'data/icons/scalable/apps').mkdir(parents=True)
        (applet / 'Cargo.toml').write_text('[package]\nname = "cosmic-applet-tiling"\n')
        (applet / 'data/com.system76.CosmicAppletTiling.desktop').write_text(
            '[Desktop Entry]\n')
        (applet / 'data/icons/scalable/apps/com.system76.CosmicAppletTiling-symbolic.svg').write_text(
            '<svg/>\n')
        self.log = self.root / 'tool-calls.jsonl'
        self.bin = self.root / 'mock-bin'
        self.bin.mkdir()
        self.executable(self.bin / 'sudo', '#!/bin/sh\necho UNEXPECTED_SUDO >&2\nexit 99\n')
        self.executable(self.bin / 'cargo', '''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['INSTALL_TEST_LOG'], 'a') as f:
    f.write(json.dumps({'cargo': args, 'cwd': os.getcwd()}) + '\\n')
if args[:1] == ['build']:
    if '--manifest-path' in args:
        target = os.environ.get('CARGO_TARGET_DIR', os.path.join(os.getcwd(), 'target'))
        binary = os.path.join(target, 'debug', 'cosmic-applet-tiling')
    else:
        profile = args[args.index('--profile') + 1] if '--profile' in args else 'debug'
        binary = os.path.join(os.getcwd(), 'target', profile, 'cosmic-comp')
    os.makedirs(os.path.dirname(binary), exist_ok=True)
    with open(binary, 'w') as f:
        f.write('#!/bin/sh\\n')
    os.chmod(binary, 0o755)
sys.exit(0)
''')
        self.executable(self.bin / 'git', '''#!/usr/bin/python3
import io, json, os, sys, tarfile
args = sys.argv[1:]
with open(os.environ['INSTALL_TEST_LOG'], 'a') as f:
    f.write(json.dumps({'git': args}) + '\\n')
if args[:1] == ['clone']:
    os.makedirs(os.path.join(args[-1], '.git'), exist_ok=True)
elif 'rev-parse' in args:
    print(os.environ['INSTALL_TEST_REV'])
elif 'get-url' in args:
    print('https://github.com/pop-os/cosmic-applets')
elif 'archive' in args:
    out = None
    for arg in args:
        if arg.startswith('--output='):
            out = arg[len('--output='):]
    styles = {
        'canonical': ['[workspace]',
                      'default-members = ["cosmic-applet-tiling"]',
                      'members = [',
                      '    "cosmic-applet-tiling",',
                      '    "cosmic-applet-status",',
                      ']'],
        'tight': ['[workspace]',
                  'default-members = ["cosmic-applet-tiling"]',
                  'members=[',
                  '    "cosmic-applet-tiling",',
                  '    "cosmic-applet-status",',
                  ']'],
        'indented': ['[workspace]',
                     'default-members = ["cosmic-applet-tiling"]',
                     '\\tmembers = [',
                     '    "cosmic-applet-tiling",',
                     '    "cosmic-applet-status",',
                     ']'],
        'spaced': ['[workspace]',
                   'default-members = ["cosmic-applet-tiling"]',
                   '  members  =  [',
                   '    "cosmic-applet-tiling",',
                   '    "cosmic-applet-status",',
                   ']'],
        'inline-close': ['[workspace]',
                         'default-members = ["cosmic-applet-tiling"]',
                         'members = [',
                         '    "cosmic-applet-tiling",',
                         '    "cosmic-applet-status" ]',
                         'resolver = "3"'],
        'multiline-default': ['[workspace]',
                              'default-members = [',
                              '    "cosmic-applet-tiling",',
                              ']',
                              'members = [',
                              '    "cosmic-applet-tiling",',
                              '    "cosmic-applet-status",',
                              ']'],
        'unclosed': ['[workspace]',
                     'default-members = ["cosmic-applet-tiling"]',
                     'members = [',
                     '    "cosmic-applet-tiling",'],
    }
    parts = styles.get(os.environ.get('INSTALL_TEST_WORKSPACE_STYLE', 'canonical'))
    if parts is None:
        parts = ['[workspace]', 'default-members = ["cosmic-applet-tiling"]']
    manifest = '\\n'.join(parts) + '\\n'
    lock = ('[[package]]\\n'
            'name = "cosmic-comp-config"\\n'
            'version = "0.1.0"\\n'
            'source = "git+https://github.com/pop-os/cosmic-comp.git?rev=abc#def"\\n'
            '\\n'
            '[[package]]\\n'
            'name = "unrelated"\\n'
            'version = "1.0"\\n')
    with tarfile.open(out, 'w') as tar:
        for name, text in (('Cargo.toml', manifest), ('Cargo.lock', lock)):
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        directory = tarfile.TarInfo('cosmic-applet-tiling')
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)
sys.exit(0)
''')
        self.env = dict(os.environ)
        for name in ('DESTDIR', 'XDG_CONFIG_HOME', 'SCROLLING_PROFILE',
                     'COSMIC_APPLETS_REV'):
            self.env.pop(name, None)
        self.env['PATH'] = str(self.bin) + os.pathsep + os.defpath
        self.env['INSTALL_TEST_LOG'] = str(self.log)
        self.env['INSTALL_TEST_REV'] = self.REV
        self.env['COSMIC_APPLETS_REV'] = self.REV
        self.state = self.root / '.cosmic-scrolling'

    def executable(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)

    def install(self, code=0, env=None):
        merged = dict(self.env)
        if env:
            merged.update(env)
        result = subprocess.run([str(self.root / 'install.sh'), '--build-only'],
                                env=merged, cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def entries(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def cargo_in(self, directory):
        return [entry['cargo'] for entry in self.entries()
                if 'cargo' in entry and entry['cwd'] == str(directory)]

    def test_compositor_tests_run_before_default_profile_build(self):
        self.install()
        self.assertEqual(self.cargo_in(self.comp)[0], ['test', '--locked'])
        self.assertEqual(self.cargo_in(self.comp)[1],
                         ['build', '--locked'])
        applet_calls = [entry['cargo'] for entry in self.entries()
                        if 'cargo' in entry and '--manifest-path' in entry['cargo']]
        self.assertEqual([call[0] for call in applet_calls], ['update', 'test', 'build'])
        manifest = (self.state / 'manifest').read_text()
        self.assertIn('owner=cosmic-scrolling-prototype-v1\n', manifest)
        self.assertIn('profile=debug\n', manifest)
        link = self.state / 'prefix/bin/cosmic-comp'
        self.assertEqual(str(link.readlink()),
                         '../../../cosmic-comp-scrolling-prototype/target/debug/cosmic-comp')
        self.assertTrue((self.comp / 'target/debug/cosmic-comp').exists())

    def test_fastdebug_profile_builds_optimized_compositor_and_records_it(self):
        self.install(env={'SCROLLING_PROFILE': 'fastdebug'})
        self.assertEqual(self.cargo_in(self.comp)[0], ['test', '--locked'])
        self.assertEqual(self.cargo_in(self.comp)[1],
                         ['build', '--locked', '--profile', 'fastdebug'])
        manifest = (self.state / 'manifest').read_text()
        self.assertIn('profile=fastdebug\n', manifest)
        self.assertIn('compositor=cosmic-comp-scrolling-prototype/target/fastdebug/cosmic-comp\n',
                      manifest)
        link = self.state / 'prefix/bin/cosmic-comp'
        self.assertEqual(str(link.readlink()),
                         '../../../cosmic-comp-scrolling-prototype/target/fastdebug/cosmic-comp')
        self.assertTrue(link.resolve() == self.comp / 'target/fastdebug/cosmic-comp')

    def test_workspace_rewrite_tolerates_whitespace_variants(self):
        for style in ('canonical', 'tight', 'indented', 'spaced'):
            with self.subTest(style=style):
                if self.state.exists():
                    shutil.rmtree(self.state)
                self.install(env={'INSTALL_TEST_WORKSPACE_STYLE': style})
                rewritten = (self.state / 'build-workspace/Cargo.toml').read_text()
                self.assertIn('default-members = ["cosmic-applet-tiling"]\n', rewritten)
                self.assertIn('members = ["cosmic-applet-tiling"]\n', rewritten)
                self.assertNotIn('cosmic-applet-status', rewritten)

    def test_workspace_without_members_list_fails(self):
        result = self.install(code=1, env={'INSTALL_TEST_WORKSPACE_STYLE': 'none'})
        self.assertIn('failed to limit the assembled applet workspace', result.stderr)
        self.assertFalse((self.state / 'build-workspace').exists())
        self.assertFalse((self.state / 'prefix/bin/cosmic-applet-tiling').exists())

    def test_workspace_rewrite_handles_inline_close_and_multiline_default(self):
        for style in ('inline-close', 'multiline-default'):
            with self.subTest(style=style):
                if self.state.exists():
                    shutil.rmtree(self.state)
                self.install(env={'INSTALL_TEST_WORKSPACE_STYLE': style})
                rewritten = (self.state / 'build-workspace/Cargo.toml').read_text()
                self.assertIn('default-members = ["cosmic-applet-tiling"]\n', rewritten)
                self.assertIn('members = ["cosmic-applet-tiling"]\n', rewritten)
                self.assertNotIn('cosmic-applet-status', rewritten)
                self.assertEqual(rewritten.count('cosmic-applet-tiling'), 2)
                if style == 'inline-close':
                    # The remainder after an inline-closing member list
                    # survives instead of being truncated away.
                    self.assertIn('resolver = "3"', rewritten)

    def test_workspace_with_unterminated_members_list_fails(self):
        result = self.install(code=1, env={'INSTALL_TEST_WORKSPACE_STYLE': 'unclosed'})
        self.assertIn('unterminated member list', result.stderr)
        self.assertFalse((self.state / 'build-workspace').exists())


if __name__ == '__main__':
    unittest.main()
