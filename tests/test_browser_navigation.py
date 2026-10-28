import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from playwright.async_api import async_playwright
from app.browser import AnaplanBrowser, FatalPageError


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.browser = AnaplanBrowser(Path(self.tmp.name))
        self.browser.timeout = 1000
        self.browser.login_timeout = 1000
        self.pw = await async_playwright().start()
        self.chromium = await self.pw.chromium.launch()
        self.browser.page = await self.chromium.new_page()
        self.browser.page.set_default_timeout(1000)

    async def asyncTearDown(self):
        await self.chromium.close()
        await self.pw.stop()
        self.tmp.cleanup()

    async def test_delayed_management_entry(self):
        await self.browser.page.set_content("""
            <script>
            setTimeout(() => {
                document.body.innerHTML = '<button>Manage models</button>';
                document.querySelector('button').onclick = () => {
                    document.body.innerHTML = '<h2>Model Management: Test</h2><button>Copy &amp; Archive</button>';
                };
            }, 100);
            </script>
        """)
        await self.browser._open_model_management()
        self.assertIsNotNone(self.browser.ui)

    async def test_direct_management_skips_hidden_match(self):
        await self.browser.page.set_content('''
            <button hidden>Model Management</button>
            <button onclick="document.body.dataset.opened='yes'; document.body.innerHTML='<h2>Model Management: Test</h2><button>Copy &amp;amp; Archive</button>'">Model Management</button>
        ''')
        await self.browser._open_model_management()
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-opened'), 'yes')

    async def test_login_timeout_does_not_capture_credentials(self):
        self.browser.login_timeout = 100
        self.browser._diagnostics = AsyncMock()
        await self.browser.page.set_content('<input type="password">')
        with self.assertRaisesRegex(RuntimeError, 'LOGIN_TIMEOUT_MS'):
            await self.browser.ensure_authenticated()
        self.browser._diagnostics.assert_not_awaited()

    async def test_something_went_wrong_stops_login(self):
        await self.browser.page.set_content('<h1>Something went wrong, try again</h1>')
        with self.assertRaisesRegex(FatalPageError, 'program was stopped'):
            await self.browser.ensure_authenticated()

    async def test_human_verification_in_frame_is_fatal(self):
        await self.browser.page.set_content('<iframe></iframe>')
        await self.browser.page.frames[1].set_content('<p>Verify you are human</p>')
        with self.assertRaisesRegex(FatalPageError, 'human verification'):
            await self.browser._raise_if_fatal_page()

    async def test_already_open_management_in_frame(self):
        from types import SimpleNamespace
        await self.browser.page.set_content('<iframe title="Modeling content"></iframe>')
        frame = self.browser.page.frames[1]
        await frame.set_content("""
            <h2>Model Management: Test workspace</h2>
            <div onclick="this.dataset.selected='yes'">empty</div>
            <button onclick="document.body.dataset.copy='yes'">Copy &amp; Archive</button>
        """)
        await self.browser._open_model_management()
        self.assertEqual(self.browser.ui, frame)
        await self.browser._select_exact_model(SimpleNamespace(model='empty'))
        self.assertEqual(await frame.locator('div').get_attribute('data-selected'), 'yes')
        await self.browser._invoke_copy_archive()
        self.assertEqual(await frame.locator('body').get_attribute('data-copy'), 'yes')

    async def test_manage_models_in_frame(self):
        await self.browser.page.set_content('<iframe title="Modeling content"></iframe>')
        frame = self.browser.page.frames[1]
        await frame.set_content("""
            <div onclick="document.body.innerHTML='<h2>Model Management: Test</h2><button>Copy &amp;amp; Archive</button>'">Manage models</div>
        """)
        await self.browser._open_model_management()
        self.assertEqual(self.browser.ui, frame)

    async def test_target_ids_and_frame_replacement(self):
        from types import SimpleNamespace
        target = SimpleNamespace(workspace_id='dev', model_id='target')
        page = self.browser.page
        async def respond(route):
            if '/models/target' in route.request.url:
                await route.fulfill(body='<iframe title="Modeling content"></iframe>', content_type='text/html')
            else:
                await route.fulfill(body='<iframe></iframe>', content_type='text/html')
        await page.route('https://fixture.test/**', respond)
        await page.goto('https://fixture.test/home')
        await page.frames[1].set_content("""
            <a href="/workspaces/prod/models/wrong" target="_parent">empty</a>
            <a href="/workspaces/dev/models/target" target="_parent">empty</a>
        """)
        await self.browser._open_target_model(target)
        self.assertTrue(page.url.endswith('/workspaces/dev/models/target'))
        await page.frames[1].set_content('<h2>Model Management: Test</h2><button>Copy &amp; Archive</button>')
        await self.browser._open_model_management()
        self.assertEqual(self.browser.ui, page.frames[1])

    async def test_detached_frame_retry(self):
        from unittest.mock import patch
        from playwright.async_api import Error
        await self.browser.page.set_content('<h2>Model Management: Test</h2><button>Copy &amp; Archive</button>')
        locator_type = type(self.browser.page.locator('h2'))
        original = locator_type.count
        calls = 0
        async def interrupted_count(locator):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Error('Locator.count: Frame was detached')
            return await original(locator)
        with patch.object(locator_type, 'count', interrupted_count):
            await self.browser._open_model_management()
        self.assertGreater(calls, 1)
        self.assertIsNotNone(self.browser.ui)

    async def login_fixture(self, url):
        self.browser.email = 'test@example.invalid'
        self.browser.password = 'fixture-password'
        self.browser.auto_login = True
        await self.browser.page.route('**/*', lambda route: route.fulfill(
            content_type='text/html', body="""
            <input type="email"><input type="password">
            <button onclick="document.body.dataset.submissions = String(Number(document.body.dataset.submissions || 0) + 1)">Log In</button>
            """))
        await self.browser.page.goto(url)

    async def test_password_login_submits_only_once(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser._try_password_login()
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('input[type=email]').input_value(), self.browser.email)
        self.assertEqual(await self.browser.page.locator('input[type=password]').input_value(), self.browser.password)
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-submissions'), '1')

    async def test_external_sso_does_not_receive_credentials(self):
        await self.login_fixture('https://anaplan.com.example.invalid/login')
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('input[type=password]').input_value(), '')
        self.assertFalse(self.browser._login_submitted)

    async def test_manual_login_setting(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        self.browser.auto_login = False
        self.browser.login_timeout = 100
        with self.assertRaises(RuntimeError):
            await self.browser.ensure_authenticated()
        self.assertEqual(await self.browser.page.locator('input[type=password]').input_value(), '')

    async def test_existing_session_skips_login(self):
        await self.login_fixture('https://us1a.app.anaplan.com/home')
        await self.browser.page.set_content('<title>Home | Anaplan</title><a role="menuitem">Home</a>')
        await self.browser.ensure_authenticated()
        self.assertFalse(self.browser._login_submitted)

    async def test_email_continue_then_readonly_email(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.set_content('''
            <input type="email"><button onclick="document.querySelector('input').readOnly=true; this.remove(); document.body.insertAdjacentHTML('beforeend', '<input type=password><button>Log In</button>')">Continue</button>
        ''')
        await self.browser._try_password_login()
        self.assertTrue(self.browser._email_submitted)
        await self.browser._try_password_login()
        self.assertTrue(self.browser._login_submitted)
        self.assertEqual(await self.browser.page.locator('input[type=password]').input_value(), self.browser.password)

    async def test_readonly_different_account_is_not_submitted(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.locator('input[type=email]').evaluate("e=>{e.value='other@example.invalid';e.readOnly=true}")
        await self.browser._try_password_login()
        self.assertFalse(self.browser._login_submitted)

    async def test_interaction_failure_does_not_log_password(self):
        from playwright.async_api import TimeoutError
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        self.browser.login_timeout=100
        self.browser._login_stage='entering password'
        self.browser._try_password_login=AsyncMock(side_effect=TimeoutError(self.browser.password))
        with self.assertLogs('app.browser',level='WARNING') as captured:
            with self.assertRaises(RuntimeError):
                await self.browser.ensure_authenticated()
        self.assertNotIn(self.browser.password, ''.join(captured.output))
        self.assertFalse(self.browser.auto_login)
        diagnostic=(self.browser.diag/'login_status.json').read_text()
        self.assertNotIn(self.browser.password,diagnostic)
        self.assertIn('entering password',diagnostic)

    async def test_select_anaplan_login_before_password(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.set_content('''
            <button onclick="document.body.dataset.sso='selected'">Single Sign-On</button>
            <a href="#" onclick="this.remove();document.body.insertAdjacentHTML('beforeend','<input type=email><input type=password><button>Log In</button>');return false">Anaplan login</a>
        ''')
        await self.browser._try_password_login()
        self.assertTrue(self.browser._anaplan_login_selected)
        self.assertIsNone(await self.browser.page.locator('body').get_attribute('data-sso'))
        await self.browser._try_password_login()
        self.assertTrue(self.browser._login_submitted)

    async def test_email_filled_before_continue_appears(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        self.browser.password = ''
        await self.browser.page.set_content('<input type="email" value="old@example.invalid">')
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('input').input_value(), self.browser.email)
        self.assertFalse(self.browser._login_submitted)

    async def test_stop_closes_all_owned_pages(self):
        self.browser.context=await self.chromium.new_context()
        first=await self.browser.context.new_page()
        second=await self.browser.context.new_page()
        self.browser._pw=AsyncMock()
        await self.browser.stop()
        self.assertTrue(first.is_closed())
        self.assertTrue(second.is_closed())
        self.browser._pw.stop.assert_awaited_once()

    async def test_stop_driver_even_if_context_close_fails(self):
        self.browser.context=AsyncMock()
        self.browser.context.close.side_effect=RuntimeError('close failed')
        self.browser._pw=AsyncMock()
        with self.assertRaisesRegex(RuntimeError,'close failed'):
            await self.browser.stop()
        self.browser._pw.stop.assert_awaited_once()

    async def test_email_filled_before_login_button_exists(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.set_content('<input type=email><input type=password>')
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('input[type=email]').input_value(),self.browser.email)

    async def test_archive_name_then_explicit_ok(self):
        self.browser.ui=self.browser.page
        await self.browser.page.set_content('''
            <div role="dialog"><button>Copy &amp; Archive</button></div>
            <div role="dialog" id="copy"><h2>Copy &amp; Archive</h2>
            <input type="text" readonly><input type="text" id="name">
            <button onclick="document.querySelector('#copy').innerHTML='<h2>Copy &amp; Archive confirmation</h2><button onclick=&quot;document.body.dataset.confirmed=1;this.parentElement.remove()&quot;>Ok</button>'">Copy &amp; Archive</button></div>
        ''')
        await self.browser._submit_archive_name('empty_[BACKUP]_20260929_150000')
        self.assertTrue(await self.browser._confirm_archive_ok())
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-confirmed'),'1')
        self.assertFalse(await self.browser._confirm_archive_ok())

    async def test_archive_verification_waits_for_slow_result(self):
        self.browser.ui=self.browser.page
        self.browser.archive_verify_timeout=3000
        await self.browser.page.set_content('''
            <script>
            setTimeout(() => document.body.insertAdjacentHTML(
                'beforeend', '<div>slow_[BACKUP]_archive</div>'), 1200);
            </script>
        ''')
        self.assertTrue(await self.browser._verify_archive('slow_[BACKUP]_archive'))

    async def test_unrelated_ok_not_clicked(self):
        self.browser.ui=self.browser.page
        await self.browser.page.set_content('<div role="dialog">Delete model<button>OK</button></div>')
        self.assertFalse(await self.browser._confirm_archive_ok())

    async def test_continue_waits_for_validation_and_ignores_hidden_duplicate(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.set_content('''
            <input type=email onblur="setTimeout(()=>document.querySelector('#submit-prelogin').disabled=false,100)">
            <button hidden>Continue</button>
            <button id="submit-prelogin" disabled onclick="document.body.dataset.continued='yes'">Continue</button>
        ''')
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-continued'),'yes')
        self.assertTrue(self.browser._email_submitted)

    async def test_loading_home_shell_does_not_skip_delayed_login(self):
        await self.login_fixture('https://us1a.app.anaplan.com/home')
        self.browser.login_timeout=3000
        await self.browser.page.set_content("""
            <title>Anaplan - Login</title><a role="menuitem">Home</a>
            <script>
            setTimeout(()=>{
                document.body.insertAdjacentHTML('beforeend','<input type=email><button id="submit-prelogin">Continue</button>');
                document.querySelector('button').onclick=()=>{
                    document.body.dataset.email=document.querySelector('input').value;
                    document.querySelector('input').remove();
                    document.querySelector('button').remove();
                    document.title='Home | Anaplan';
                };
            },200);
            </script>
        """)
        await self.browser.ensure_authenticated()
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-email'),self.browser.email)
        self.assertTrue(self.browser._email_submitted)

    async def test_continue_clicked_even_when_password_field_is_visible(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        await self.browser.page.set_content('''
            <form onsubmit="return false"><input type=email><input type=password>
            <button onclick="document.body.dataset.continued='yes'">Continue</button></form>
        ''')
        await self.browser._try_password_login()
        self.assertEqual(await self.browser.page.locator('input[type=email]').input_value(),self.browser.email)
        self.assertEqual(await self.browser.page.locator('body').get_attribute('data-continued'),'yes')
        self.assertTrue(self.browser._email_submitted)
        self.assertFalse(self.browser._login_submitted)

    async def test_continue_on_second_email_form(self):
        await self.login_fixture('https://us1a.app.anaplan.com/login')
        for step in ('first','second'):
            await self.browser.page.set_content('''
                <input type=email>
                <button onclick="document.body.dataset.clicks=String(Number(document.body.dataset.clicks||0)+1)">Continue</button>
            ''')
            await self.browser._try_password_login()
            await self.browser._try_password_login()
            self.assertEqual(await self.browser.page.locator('input').input_value(),self.browser.email,step)
            self.assertEqual(await self.browser.page.locator('body').get_attribute('data-clicks'),'1',step)
