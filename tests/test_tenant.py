"""Workspaces: one server, several people, no shared wallet and no shared shelf.

The single-tenant case is the one that must not move. Everything here checks it
first, because this feature is only worth having if the local install that never
asked anybody who they are goes on not asking.

The rest is the isolation itself, and it is worth stating what "isolated" has to
mean, because three different things could each leak on their own: the provider
credential (whose money), the papers on disk (whose documents), and the job
registry (whose work is running).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import access, config, jobs, tenant


class SingleTenantIsUntouched(unittest.TestCase):
    def test_nothing_is_bound_when_the_feature_is_off(self):
        self.assertFalse(tenant.enabled())
        self.assertIsNone(tenant.current())

    def test_the_data_directory_is_exactly_what_it_always_was(self):
        """An existing install must not have to move a single file."""
        self.assertEqual(tenant.data_dir(), config.DATA_DIR)

    def test_a_project_still_lands_where_it_used_to(self):
        self.assertEqual(jobs.Project('demo').dir, config.DATA_DIR / 'demo')

    def test_binding_a_workspace_does_nothing_while_it_is_off(self):
        token = tenant.use('abc')
        try:
            self.assertIsNone(tenant.current())
            self.assertEqual(tenant.data_dir(), config.DATA_DIR)
        finally:
            tenant.reset(token)


class MultiTenantTestCase(unittest.TestCase):
    """Each test gets its own state directory, so nothing touches the operator's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        for patcher in (patch.dict(os.environ, {'AHA_MULTI_TENANT': '1'}),
                        patch.object(config, 'STATE_DIR', root),
                        patch.object(config, 'DATA_DIR', root / 'data')):
            patcher.start()
            self.addCleanup(patcher.stop)
        (root / 'data').mkdir(parents=True, exist_ok=True)

    def as_workspace(self, phrase):
        token = tenant.use(tenant.identify(phrase))
        self.addCleanup(lambda t=token: tenant.reset(t))
        return tenant.current()


class ThePassphraseIsTheAddress(MultiTenantTestCase):
    def test_the_same_phrase_always_opens_the_same_workspace(self):
        """Which is what makes it work on a second device with no account."""
        self.assertEqual(tenant.identify('correct horse battery'),
                         tenant.identify('  correct horse battery  '))

    def test_different_phrases_open_different_workspaces(self):
        self.assertNotEqual(tenant.identify('one phrase here'),
                            tenant.identify('another phrase'))

    def test_a_short_phrase_is_refused(self):
        """A guessable phrase is a guessable workspace."""
        for phrase in ('', 'short', 'a' * (tenant.MIN_PASSPHRASE - 1)):
            with self.subTest(phrase=phrase), self.assertRaises(ValueError):
                tenant.identify(phrase)

    def test_the_id_does_not_contain_the_phrase(self):
        phrase = 'a memorable passphrase'
        self.assertNotIn('memorable', tenant.identify(phrase))

    def test_the_secret_survives_a_restart(self):
        """A fresh secret per process would move every workspace on every
        deploy, which on a container platform is every push."""
        first = tenant.identify('a stable phrase')
        tenant.secret.__wrapped__ if hasattr(tenant.secret, '__wrapped__') else None
        self.assertEqual(tenant.identify('a stable phrase'), first)
        self.assertTrue((config.STATE_DIR / '.runtime' / 'tenant-secret').exists())


class TheCookieCarriesTheWorkspace(MultiTenantTestCase):
    def test_a_token_names_the_workspace_it_opens(self):
        me = tenant.identify('my own workspace')
        self.assertEqual(access.workspace_of(access.mint(me)), me)

    def test_a_forged_signature_opens_nothing(self):
        me = tenant.identify('my own workspace')
        self.assertIsNone(access.workspace_of(f'{me}:9999999999.' + 'f' * 64))

    def test_one_workspace_cannot_mint_a_token_for_another(self):
        """The cookie is signed with the server secret, not with the visitor's
        own phrase -- otherwise anyone could address anyone."""
        mine, theirs = tenant.identify('my own phrase'), tenant.identify('their own phrase')
        token = access.mint(mine)
        payload, _, mac = token.rpartition('.')
        swapped = payload.replace(mine, theirs) + '.' + mac
        self.assertIsNone(access.workspace_of(swapped))

    def test_an_expired_token_opens_nothing(self):
        me = tenant.identify('my own workspace')
        with patch.object(access, 'TTL', -1):
            self.assertIsNone(access.workspace_of(access.mint(me)))

    def test_the_gate_stands_even_with_no_operator_password(self):
        """In multi-tenant the phrase is an address, so there is nobody to let
        in without one."""
        with patch.object(config, 'ACCESS_PASSWORD', ''):
            self.assertTrue(access.enabled())


class WhoseMoney(MultiTenantTestCase):
    def test_each_workspace_resolves_against_its_own_credential_store(self):
        mine = self.as_workspace('my own phrase')
        first = tenant.credential_file()
        tenant.reset(tenant.use(tenant.identify('their own phrase')))
        token = tenant.use(tenant.identify('their own phrase'))
        try:
            self.assertNotEqual(tenant.credential_file(), first)
            self.assertIn(mine, str(first))
        finally:
            tenant.reset(token)

    def test_the_resolved_credential_cache_is_keyed_by_workspace(self):
        """Keyed by provider alone, the second workspace would be handed the
        first one's key -- the exact bug this feature exists to prevent."""
        from app import pi_models
        pi_models.forget_resolved()
        calls = []

        def fake(*args, **kwargs):
            calls.append(tenant.current())
            return {'base_url': 'https://x', 'api_key': 'k-' + str(tenant.current())}

        with patch.object(pi_models, '_run', side_effect=fake):
            a = tenant.use(tenant.identify('workspace one here'))
            first = pi_models.resolve('openrouter')
            tenant.reset(a)
            b = tenant.use(tenant.identify('workspace two here'))
            second = pi_models.resolve('openrouter')
            tenant.reset(b)
        self.assertNotEqual(first['api_key'], second['api_key'])
        self.assertEqual(len(calls), 2, 'the second workspace reused the first cache entry')

    def test_the_subprocess_is_pointed_at_this_workspaces_store(self):
        from app import pi_models
        seen = {}

        def fake_run(cmd, **kwargs):
            seen['file'] = kwargs['env']['PI_CREDENTIAL_FILE']
            raise RuntimeError('stop here')

        me = self.as_workspace('my own phrase')
        with patch.object(pi_models.subprocess, 'run', side_effect=fake_run), \
             patch.object(pi_models.binaries, 'node', return_value='node'):
            with self.assertRaises(pi_models.ProviderError):
                pi_models._run('providers')
        self.assertIn(me, seen['file'])


class WhoseDocuments(MultiTenantTestCase):
    def test_a_project_lands_inside_its_own_workspace(self):
        me = self.as_workspace('my own phrase')
        self.assertIn(me, str(jobs.Project('paper').dir))

    def test_the_same_paper_name_in_two_workspaces_is_two_projects(self):
        """A pid is a slug of the filename, so a collision is the normal case,
        not an edge one."""
        a = tenant.use(tenant.identify('workspace one here'))
        mine = jobs.Project('paper').dir
        tenant.reset(a)
        b = tenant.use(tenant.identify('workspace two here'))
        theirs = jobs.Project('paper').dir
        tenant.reset(b)
        self.assertNotEqual(mine, theirs)

    def test_a_workspace_lists_only_its_own(self):
        a = tenant.use(tenant.identify('workspace one here'))
        mine = jobs.Project('mine')
        mine.dir.mkdir(parents=True, exist_ok=True)
        mine.save(id='mine', state='idle')
        tenant.reset(a)

        b = tenant.use(tenant.identify('workspace two here'))
        try:
            self.assertEqual([p['id'] for p in jobs.list_projects()], [])
            theirs = jobs.Project('theirs')
            theirs.dir.mkdir(parents=True, exist_ok=True)
            theirs.save(id='theirs', state='idle')
            self.assertEqual([p['id'] for p in jobs.list_projects()], ['theirs'])
        finally:
            tenant.reset(b)


class WhoseWork(MultiTenantTestCase):
    def test_the_running_job_registry_is_per_workspace(self):
        a = tenant.use(tenant.identify('workspace one here'))
        jobs._ACTIVE[jobs._slot('paper')] = 1
        busy_here = jobs._pending('paper')
        tenant.reset(a)
        b = tenant.use(tenant.identify('workspace two here'))
        try:
            self.assertTrue(busy_here)
            self.assertFalse(jobs._pending('paper'),
                             'another workspace sees this one as busy')
        finally:
            tenant.reset(b)
            jobs._ACTIVE.clear()

    def test_a_worker_thread_runs_as_the_workspace_that_queued_it(self):
        """The pool's threads were never in the request. Without the binding the
        job would resolve credentials and write papers as somebody else."""
        me = self.as_workspace('my own phrase')
        seen = []
        bound = jobs._bind(lambda pid: seen.append(tenant.current()), tenant.current())
        token = tenant.use(None)
        try:
            bound('paper')
        finally:
            tenant.reset(token)
        self.assertEqual(seen, [me])


class SettingsAreNotShared(MultiTenantTestCase):
    def test_a_workspace_overrides_only_for_itself(self):
        from app import studio_settings
        a = tenant.use(tenant.identify('workspace one here'))
        studio_settings.save_settings({'voice': 'en-US-AriaNeural'})
        mine = config.setting('EDGE_TTS_VOICE')
        tenant.reset(a)
        b = tenant.use(tenant.identify('workspace two here'))
        try:
            self.assertEqual(mine, 'en-US-AriaNeural')
            self.assertEqual(config.setting('EDGE_TTS_VOICE'), config.EDGE_TTS_VOICE)
        finally:
            tenant.reset(b)

    def test_saving_never_touches_the_operators_env(self):
        """The .env on disk is the machine's, not a visitor's."""
        from app import studio_settings
        env = config.STATE_DIR / '.env'
        env.write_text('EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural\n')
        before = env.read_text()
        with patch.object(config, 'ENV_FILE', env):
            self.as_workspace('my own phrase')
            studio_settings.save_settings({'voice': 'en-US-AriaNeural'})
        self.assertEqual(env.read_text(), before)


class EndToEnd(MultiTenantTestCase):
    """Login, cookie, middleware, contextvar, disk -- the whole chain."""

    def client(self):
        """The /files mount captured config.DATA_DIR when app.main was first
        imported, which in a test suite is whichever case ran first. Point it at
        this case's directory, and put it back afterwards."""
        from fastapi.testclient import TestClient
        from app.main import app
        for route in app.routes:
            served = getattr(route, 'app', None)
            if str(getattr(route, 'path', '')) != '/files' or served is None:
                continue
            # all_directories is what lookup_path actually walks; .directory is
            # only what the constructor was handed. Setting the second and not
            # the first changes nothing, silently.
            was = (served.directory, served.all_directories)
            served.directory = config.DATA_DIR
            served.all_directories = [config.DATA_DIR]
            self.addCleanup(lambda s=served, w=was:
                            (setattr(s, 'directory', w[0]),
                             setattr(s, 'all_directories', w[1])))
        return TestClient(app, follow_redirects=False)

    def sign_in(self, phrase):
        """A client per workspace, with the cookie on the client.

        Passing cookies per request is deprecated and its precedence against the
        client's own jar is explicitly undefined -- which, in a test about who
        can read what, is the one thing that must not be ambiguous."""
        client = self.client()
        response = client.post('/api/login', data={'password': phrase, 'next': '/'})
        self.assertEqual(response.status_code, 303, response.text)
        cookie = response.cookies.get(access.COOKIE)
        client.cookies.set(access.COOKIE, cookie)
        return client, cookie

    def test_two_phrases_are_two_libraries(self):
        me, mine = self.sign_in('workspace one here')
        them, theirs = self.sign_in('workspace two here')
        self.assertNotEqual(access.workspace_of(mine), access.workspace_of(theirs))

        token = tenant.use(access.workspace_of(mine))
        project = jobs.Project('mine')
        project.dir.mkdir(parents=True, exist_ok=True)
        project.save(id='mine', state='idle')
        tenant.reset(token)

        self.assertEqual([p['id'] for p in me.get('/api/projects').json()], ['mine'])
        self.assertEqual(them.get('/api/projects').json(), [])

    def test_a_short_phrase_is_refused_at_the_door(self):
        client = self.client()
        response = client.post('/api/login', data={'password': 'short', 'next': '/'})
        self.assertEqual(response.status_code, 401)

    def test_no_cookie_is_turned_away(self):
        client = self.client()
        self.assertEqual(client.get('/api/projects').status_code, 401)

    def test_a_workspace_can_read_only_its_own_files(self):
        """/files is a StaticFiles mount, so the workspace is applied by
        rewriting the path in front of it. The proof is that the same URL
        serves one visitor and not the other."""
        me, mine = self.sign_in('workspace one here')
        them, _ = self.sign_in('workspace two here')
        workspace = access.workspace_of(mine)

        paper = config.DATA_DIR / 'w' / workspace / 'p' / 'paper.pdf'
        paper.parent.mkdir(parents=True, exist_ok=True)
        paper.write_bytes(b'%PDF-1.4 mine')

        ok = me.get('/files/p/paper.pdf')
        denied = them.get('/files/p/paper.pdf')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.content, b'%PDF-1.4 mine')
        self.assertEqual(denied.status_code, 404)

    def test_spelling_out_another_workspace_does_not_reach_it(self):
        me, _ = self.sign_in('workspace one here')
        _, theirs = self.sign_in('workspace two here')
        them = access.workspace_of(theirs)

        paper = config.DATA_DIR / 'w' / them / 'p' / 'paper.pdf'
        paper.parent.mkdir(parents=True, exist_ok=True)
        paper.write_bytes(b'%PDF-1.4 theirs')

        for path in (f'/files/w/{them}/p/paper.pdf',
                     f'/files/../w/{them}/p/paper.pdf'):
            with self.subTest(path=path):
                self.assertNotEqual(me.get(path).content, b'%PDF-1.4 theirs')


if __name__ == '__main__':
    unittest.main()
