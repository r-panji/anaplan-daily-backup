import os, logging, json, re, asyncio
from time import monotonic
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError
from credentials import load_credentials

log=logging.getLogger(__name__)

class FatalPageError(RuntimeError):
    """An Anaplan error page that requires a fresh browser run."""


class ArchiveOperationError(RuntimeError):
    def __init__(self,message,submission_state='not_submitted',retryable=False):
        super().__init__(message)
        self.submission_state=submission_state
        self.retryable=retryable


class AnaplanBrowser:
    def __init__(self,root:Path):
        self.root=root
        self.profile=Path(os.getenv('BROWSER_PROFILE',str(root/'.browser-profile'))).expanduser()
        self.headless=os.getenv('HEADLESS','false').lower()=='true'
        self.login_url=os.getenv('ANAPLAN_HOME_URL',os.getenv('ANAPLAN_LOGIN_URL','https://us1a.app.anaplan.com/home'))
        self.timeout=int(os.getenv('UI_TIMEOUT_MS','20000'))
        self.login_timeout=int(os.getenv('LOGIN_TIMEOUT_MS','180000'))
        self.archive_verify_timeout=int(os.getenv('ARCHIVE_VERIFY_TIMEOUT_MS','600000'))
        self.safe_retry_attempts=max(1,int(os.getenv('ANAPLAN_SAFE_RETRY_ATTEMPTS','2')))
        self.safe_retry_delay=max(0,float(os.getenv('ANAPLAN_SAFE_RETRY_DELAY_SECONDS','2')))
        self.diag=root/'logs'/'diagnostics'; self.diag.mkdir(parents=True,exist_ok=True)
        self._pw=self.context=self.page=None
        self.ui=None
        self.email,self.password=load_credentials()
        self.auto_login=os.getenv('ANAPLAN_BROWSER_AUTO_LOGIN','true').lower()=='true'
        self._login_submitted=False
        self._email_submitted=False
        self._anaplan_login_selected=False
        self._login_stage="waiting for form"

    async def start(self):
        self.profile.mkdir(parents=True,exist_ok=True)
        self._pw=await async_playwright().start()
        self.context=await self._pw.chromium.launch_persistent_context(str(self.profile),headless=self.headless)
        self.page=self.context.pages[0] if self.context.pages else await self.context.new_page()
        self.page.set_default_timeout(self.timeout)
        await self.page.goto(self.login_url,wait_until='domcontentloaded')

    async def stop(self):
        try:
            if self.context:
                await self.context.close()
                log.info('Backup browser closed.')
        finally:
            if self._pw: await self._pw.stop()

    async def ensure_authenticated(self):
        log.info('Browser opened: %s',self.page.url)
        log.info('Filling Anaplan login from .env when available; complete any SSO/MFA prompt in the browser.')
        deadline=monotonic()+self.login_timeout/1000
        while monotonic() < deadline:
            if self.page.is_closed():
                raise RuntimeError('Browser closed while waiting for login')
            try:
                await self._raise_if_fatal_page()
                if self.auto_login and self.email:
                    await self._try_password_login()
                title=(await self.page.title()).strip()
                login_fields=self.page.locator('input[type="email"]:visible, input[type="password"]:visible')
                ready_title=title.endswith(' | Anaplan') and not re.search(r'log\s*in|sign\s*in',title,re.I)
                if ready_title and await login_fields.count()==0:
                    for locator in self._management_locators()+self._navigation_locators():
                        if await locator.count() and await locator.first.is_visible():
                            log.info('Authenticated Anaplan page ready.')
                            return
            except PlaywrightError as exc:
                if not self._navigation_changed(exc):
                    category='timeout' if isinstance(exc,PlaywrightTimeoutError) else 'browser interaction error'
                    self.auto_login=False
                    log.warning('Automatic login stopped at %s (%s). Complete login in the browser.',
                                self._login_stage,category)
                    (self.diag/'login_status.json').write_text(json.dumps({
                        'stage':self._login_stage,'category':category,
                        'email_submitted':self._email_submitted,
                        'password_submitted':self._login_submitted,
                    }),encoding='utf-8')
            await asyncio.sleep(0.1)
        raise RuntimeError(
            f'Anaplan navigation did not appear within {self.login_timeout / 1000:g}s. '
            'Complete SSO/MFA or check credentials; increase LOGIN_TIMEOUT_MS if needed.'
        )

    async def _raise_if_fatal_page(self):
        patterns=(
            (re.compile(r'something\s+went\s+wrong\s*,?\s*try\s+again',re.I),
             'Anaplan displayed "Something went wrong, try again".'),
            (re.compile(r'verify\s+(?:that\s+)?you\s+are\s+human',re.I),
             'Anaplan requested human verification.'),
        )
        for frame in self.page.frames:
            try:
                body=frame.locator('body')
                if not await body.count():
                    continue
                text=await body.inner_text(timeout=1000)
            except PlaywrightError:
                continue
            for pattern,message in patterns:
                if pattern.search(text):
                    log.error('%s Closing the browser; rerun the command to try again.',message)
                    raise FatalPageError(
                        f'{message} The program was stopped and the browser was closed. '
                        'Rerun the command to try again.'
                    )

    async def _try_password_login(self):
        if self._login_submitted:
            return
        url=urlparse(self.page.url)
        host=url.hostname or ''
        if url.scheme!='https' or not (host=='anaplan.com' or host.endswith('.anaplan.com')):
            return
        if not self._anaplan_login_selected:
            name=re.compile(r'^Anaplan\s+log\s*in(?:\s*\(with email and password\))?$',re.I)
            choices=[self.page.get_by_role('button',name=name),
                     self.page.get_by_role('link',name=name),
                     self.page.get_by_text(name,exact=True)]
            for choice in choices:
                for i in range(await choice.count()):
                    item=choice.nth(i)
                    if await item.is_visible():
                        self._login_stage='choosing Anaplan login'
                        await item.click(timeout=3000)
                        self._anaplan_login_selected=True
                        log.info('Selected Anaplan login (email and password).')
                        return
        password=self.page.locator('input[type="password"]:visible')
        email=self.page.locator(
            'input[type="email"]:visible, input[name="email"]:visible, '
            'input[name="username"]:visible, input[autocomplete="username"]:visible, '
            'input[id="email"]:visible, input[id="username"]:visible'
        )
        submit=self.page.get_by_role('button',name=re.compile(r'^(log\s*in|sign\s*in)$',re.I))
        if await email.count()==1 and await email.is_editable():
            self._login_stage='entering email'
            if await email.input_value()!=self.email:
                await email.fill(self.email,timeout=3000)
                log.info('Filled login email from ANAPLAN_EMAIL in .env.')
        if await email.count()==1 and await email.is_editable():
            advance=self.page.locator('#submit-prelogin:visible')
            if await advance.count()==0:
                form=email.locator('xpath=ancestor::form[1]')
                scope=form if await form.count()==1 else self.page
                advance=scope.get_by_role('button',name=re.compile(r'^continue$',re.I)).and_(
                    self.page.locator(':visible'))
            if await advance.count()==1 and not await advance.evaluate(
                'element => element.__backupContinueClicked === true'
            ):
                await email.blur()
                self._login_stage='submitting email'
                self._email_submitted=True
                await advance.evaluate('element => { element.__backupContinueClicked = true; }')
                await advance.click(timeout=self.timeout)
                log.info('Clicked Continue after filling email; waiting for password or SSO/MFA.')
                return
        if await password.count()==0:
            return
        if await password.count()!=1 or await submit.count()!=1:
            return
        if not await submit.is_visible() or not await password.is_editable():
            return
        if await email.count()==1:
            if await email.is_editable():
                self._login_stage='entering email'
                await email.fill(self.email,timeout=3000)
            elif (await email.input_value()).strip().lower()!=self.email.lower():
                return
        elif await email.count()>1:
            return
        if not self.password: return
        self._login_stage='entering password'
        await password.fill(self.password,timeout=3000)
        if not await submit.is_enabled():
            return
        self._login_stage='submitting password'
        self._login_submitted=True
        await submit.click(timeout=3000)
        log.info('Submitted Anaplan password login using .env credentials; waiting for authentication.')

    async def _diagnostics(self,label):
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
        safe=re.sub(r'[^A-Za-z0-9_.-]+','_',label)
        png=self.diag/f'{stamp}_{safe}.png'; html=self.diag/f'{stamp}_{safe}.html'; meta=self.diag/f'{stamp}_{safe}.json'
        try: await self.page.screenshot(path=str(png),full_page=True)
        except Exception: pass
        try: html.write_text(await self.page.content(),encoding='utf-8')
        except Exception: pass
        try: meta.write_text(json.dumps({'url':self.page.url,'title':await self.page.title()},indent=2),encoding='utf-8')
        except Exception: pass
        for index, frame in enumerate(self.page.frames):
            if frame == self.page.main_frame: continue
            try:
                (self.diag/f'{stamp}_{safe}_frame_{index}.html').write_text(
                    await frame.content(),encoding='utf-8')
            except Exception: pass
        log.error('UI diagnostics saved under %s',self.diag)

    async def _wait_for_visible(self, locators, description, timeout=None):
        deadline=monotonic()+(self.timeout if timeout is None else timeout)/1000
        while True:
            if self.page.is_closed():
                raise RuntimeError(f'Browser closed while waiting for {description}')
            await self._raise_if_fatal_page()
            for locator in locators:
                for i in range(await locator.count()):
                    candidate=locator.nth(i)
                    if await candidate.is_visible():
                        return candidate
            if monotonic() >= deadline:
                raise RuntimeError(f'Timed out waiting for {description}')
            await asyncio.sleep(0.1)

    async def _click_first(self, locators, description):
        locator=await self._wait_for_visible(locators, description)
        await locator.click()
        log.info('UI: %s',description)

    async def _fill_first(self, locators, value, description):
        last=None
        for locator in locators:
            try:
                if await locator.count():
                    await locator.first.fill(value)
                    log.info('UI: filled %s',description)
                    return
            except Exception as e: last=e
        raise RuntimeError(f'Could not locate {description}') from last

    def _management_locators(self, scope=None):
        scope=scope or self.page
        name=re.compile(r'^(model management|manage models)$',re.I)
        return [
            scope.get_by_role('link',name=name),
            scope.get_by_role('button',name=name),
            scope.get_by_role('menuitem',name=name),
            scope.get_by_text(name,exact=True),
        ]

    def _navigation_locators(self):
        return [
            self.page.locator('[data-test-id="gnav-product-menu-trigger"]'),
            self.page.get_by_role('menuitem',name=re.compile(r'^home$',re.I)),
            self.page.get_by_role('button',name=re.compile(r'^(home|navigation|menu|manage)$',re.I)),
        ]

    @staticmethod
    def _navigation_changed(exc):
        message=str(exc).lower()
        return any(text in message for text in (
            'frame was detached', 'execution context was destroyed',
            'cannot find context with specified id',
        ))

    async def _open_target_model(self,target):
        path=f'/workspaces/{target.workspace_id}/models/{target.model_id}'
        deadline=monotonic()+self.login_timeout/1000
        opened=False
        all_models_opened=False
        while monotonic() < deadline:
            await self._raise_if_fatal_page()
            if path.lower() in self.page.url.lower():
                return
            try:
                for frame in self.page.frames:
                    links=frame.locator('a[href]')
                    for i in range(await links.count()):
                        link=links.nth(i)
                        href=await link.get_attribute('href') or ''
                        if re.search(re.escape(path)+r'(?:[/?#]|$)',href,re.I) and await link.is_visible():
                            await link.click()
                            opened=True
                            log.info('UI: opened target model by workspace/model IDs')
                            break
                    if opened: break
                if not opened and not all_models_opened:
                    for frame in self.page.frames:
                        link=frame.locator('a[data-test-id="view-all-models"]')
                        if await link.count() and await link.first.is_visible():
                            await link.first.click()
                            all_models_opened=True
                            break
            except PlaywrightError as exc:
                if not self._navigation_changed(exc): raise
            await asyncio.sleep(0.1)
        raise RuntimeError('Could not open the configured workspace/model IDs from Home. '
                           'Check that the model is accessible in this browser account.')

    async def _open_model_management(self):
        deadline=monotonic()+self.login_timeout/1000
        clicked_scope=None
        while monotonic() < deadline:
            await self._raise_if_fatal_page()
            try:
                for scope in self.page.frames:
                    heading=scope.get_by_text(re.compile(r'^Model Management(?:\s*:.*)?$',re.I))
                    copy=scope.get_by_text(re.compile(r'^Copy\s*(?:&|and)\s*Archive$',re.I))
                    if await heading.count() and await copy.count():
                        if await heading.first.is_visible() and await copy.first.is_visible():
                            self.ui=scope
                            log.info('UI: Model Management ready')
                            return
                    if scope != clicked_scope:
                        clicked=False
                        for locator in self._management_locators(scope):
                            for i in range(await locator.count()):
                                if await locator.nth(i).is_visible():
                                    await locator.nth(i).click()
                                    clicked_scope=scope
                                    clicked=True
                                    log.info('UI: opened Manage models')
                                    break
                            if clicked: break
            except PlaywrightError as exc:
                if not self._navigation_changed(exc): raise
                clicked_scope=None
            await asyncio.sleep(0.1)
        raise RuntimeError('Timed out waiting for Model Management in the target model. '
                           'Check Workspace Administrator access and the saved diagnostics.')

    async def _select_exact_model(self,target):
        # Match the visible model name exactly; IDs were already validated through the documented API.
        exact=re.compile(r'^'+re.escape(target.model)+r'$')
        rows=self.ui.get_by_role('row').filter(has_text=target.model)
        if await rows.count():
            matching=[]
            for i in range(await rows.count()):
                row=rows.nth(i)
                txt=(await row.inner_text()).strip()
                if target.model in txt: matching.append(row)
            if len(matching)!=1:
                raise RuntimeError(f'Expected exactly one row containing model {target.model!r}; found {len(matching)}')
            row=matching[0]
            # Select via checkbox if available, otherwise click exact model text.
            cb=row.get_by_role('checkbox')
            if await cb.count(): await cb.first.check()
            else: await row.get_by_text(exact).first.click()
            log.info('UI: selected exact model %r',target.model)
            return row
        exact_text=self.ui.get_by_text(exact,exact=True)
        if await exact_text.count()!=1:
            raise RuntimeError(f'Expected exactly one visible exact model named {target.model!r}; found {await exact_text.count()}')
        await exact_text.first.click(); log.info('UI: selected exact model %r',target.model)
        return None

    async def _invoke_copy_archive(self,row=None):
        # Action may be in the selected row's overflow menu or in a toolbar.
        if row is not None:
            for rx in [r'(more|actions|options)',r'⋮']:
                btn=row.get_by_role('button',name=re.compile(rx,re.I))
                if await btn.count():
                    await btn.first.click(); break
        await self._click_first([
            self.ui.get_by_role('menuitem',name=re.compile(r'^copy\s*(?:&|and)\s*archive$',re.I)),
            self.ui.get_by_role('button',name=re.compile(r'^copy\s*(?:&|and)\s*archive$',re.I)),
            self.ui.get_by_text(re.compile(r'^copy\s*(?:&|and)\s*archive$',re.I),exact=True),
        ],'Copy & Archive')

    async def _submit_archive_name(self,archive_name):
        dialogs=self.ui.locator('[role="dialog"]:visible, .dijitDialog:visible')
        scope=await self._wait_for_visible([
            dialogs.filter(has=self.ui.locator('input:not([readonly]):not([disabled])[type="text"]')),
        ],'archive name dialog')
        await self._fill_first([
            scope.get_by_role('textbox',name=re.compile(r'(model name|name|copy)',re.I)),
            scope.locator('input[type="text"]:not([readonly]):not([disabled]):visible'),
        ],archive_name,'archive model name')
        await self._click_first([
            scope.get_by_role('button',name=re.compile(r'^ok$',re.I)),
            scope.get_by_role('button',name=re.compile(r'^(copy\s*(?:&|and)\s*archive|copy|confirm|save)$',re.I)),
        ],'Copy & Archive confirmation')

    async def _confirm_archive_ok(self):
        dialogs=self.ui.locator('[role="dialog"]:visible, .dijitDialog:visible').filter(
            has_text=re.compile(r'copy.*archive',re.I))
        for i in range(await dialogs.count()):
            ok=dialogs.nth(i).get_by_role('button',name=re.compile(r'^ok$',re.I))
            if await ok.count()==1 and await ok.is_visible() and await ok.is_enabled():
                await ok.click()
                log.info('UI: clicked OK in Copy & Archive confirmation')
                return True
        return False

    async def _show_archived_models(self):
        controls=[
            self.ui.get_by_role('checkbox',name=re.compile(r'show archived models',re.I)),
            self.ui.get_by_role('button',name=re.compile(r'show archived models',re.I)),
            self.ui.get_by_text(re.compile(r'^show archived models$',re.I),exact=True),
        ]
        for control in controls:
            if not await control.count() or not await control.first.is_visible():
                continue
            item=control.first
            if await item.get_attribute('type')=='checkbox':
                if not await item.is_checked():
                    await item.check()
            else:
                await item.click()
            return True
        return False

    async def _archive_exists(self,archive_name,reveal_archived=True):
        exact_name=re.compile(r'^'+re.escape(archive_name)+r'$')
        result=self.ui.get_by_text(exact_name,exact=True)
        if await result.count():
            return True
        if reveal_archived and await self._show_archived_models():
            await asyncio.sleep(0.2)
            result=self.ui.get_by_text(exact_name,exact=True)
            return bool(await result.count())
        return False

    async def _verify_archive(self,archive_name):
        # Wait for the modal/action to settle, then look for the generated name. If archived models are hidden,
        # try the documented "Show Archived Models" control before declaring verification failure.
        deadline=monotonic()+self.archive_verify_timeout/1000
        confirmed=False
        exact_name=re.compile(r'^'+re.escape(archive_name)+r'$')
        while monotonic()<deadline:
            await self._raise_if_fatal_page()
            try:
                if not confirmed:
                    confirmed=await self._confirm_archive_ok()
                result=self.ui.get_by_text(exact_name,exact=True)
                if await result.count() and await result.first.is_visible():
                    return True
                await self._show_archived_models()
            except PlaywrightError as exc:
                if not self._navigation_changed(exc): raise
            await asyncio.sleep(1)
        return False

    async def preflight_target(self,target):
        self.ui=None
        await self.page.goto(self.login_url,wait_until='domcontentloaded')
        await self._raise_if_fatal_page()
        await self._open_target_model(target)
        await self._open_model_management()
        await self._select_exact_model(target)
        return {'status':'PREFLIGHT_OK','workspace':target.workspace,
                'workspace_id':target.workspace_id,'model':target.model,
                'model_id':target.model_id}

    @staticmethod
    def _safe_to_retry_before_submission(exc):
        if isinstance(exc,FatalPageError):
            return False
        if isinstance(exc,ArchiveOperationError):
            return exc.submission_state=='not_submitted' and exc.retryable
        if isinstance(exc,(PlaywrightError,RuntimeError)):
            message=str(exc).lower()
            blocked=('already exists','workspace administrator','requires workspace_id')
            if any(text in message for text in blocked):
                return False
            transient=('timeout','timed out','frame was detached','execution context',
                       'could not open','could not locate','browser interaction')
            return any(text in message for text in transient)
        return False

    async def _prepare_copy_archive(self,target,archive_name):
        self.ui=None
        await self.page.goto(self.login_url,wait_until='domcontentloaded')
        await self._raise_if_fatal_page()
        await self._open_target_model(target)
        await self._open_model_management()
        row=await self._select_exact_model(target)
        if await self._archive_exists(archive_name):
            raise ArchiveOperationError(
                f'Archive {archive_name!r} already exists in workspace '
                f'{target.workspace!r}; Copy & Archive was not submitted.'
            )
        await self._invoke_copy_archive(row)

    async def copy_and_archive(self,target,archive_name,dry_run=False,test_copy=False):
        log.info("Target workspace=%r workspace_id=%r model=%r model_id=%r archive=%r dry_run=%s test_copy=%s",target.workspace,target.workspace_id or None,target.model,target.model_id or None,archive_name,dry_run,test_copy)
        if dry_run:
            return {'status':'DRY_RUN','workspace':target.workspace,'workspace_id':target.workspace_id or None,'model':target.model,'model_id':target.model_id or None,'archive':archive_name,'submission_state':'not_submitted'}
        if not (target.workspace_id and target.model_id):
            raise RuntimeError('Live backup requires workspace_id and model_id.')
        try:
            for attempt in range(1,self.safe_retry_attempts+1):
                try:
                    await self._prepare_copy_archive(target,archive_name)
                    break
                except Exception as exc:
                    if attempt>=self.safe_retry_attempts or not self._safe_to_retry_before_submission(exc):
                        raise
                    log.warning(
                        'Safe pre-submission attempt %d/%d failed for %s / %s: %s. Retrying.',
                        attempt,self.safe_retry_attempts,target.workspace,target.model,exc)
                    await asyncio.sleep(self.safe_retry_delay)
            try:
                await self._submit_archive_name(archive_name)
                verified=await self._verify_archive(archive_name)
            except FatalPageError:
                raise
            except Exception as exc:
                raise ArchiveOperationError(
                    f'Copy & Archive may have been submitted for {archive_name!r}, but the '
                    f'operation did not complete cleanly: {exc}. Inspect Anaplan before retrying.',
                    submission_state='submitted_unverified') from exc
            if not verified:
                raise ArchiveOperationError(
                    f'Copy & Archive was submitted but archive {archive_name!r} could not be '
                    'verified in the current UI. Inspect Anaplan before retrying.',
                    submission_state='submitted_unverified')
            return {'status':'SUCCESS','workspace':target.workspace,'workspace_id':target.workspace_id,'model':target.model,'model_id':target.model_id,'archive':archive_name,'verified':True,'submission_state':'confirmed'}
        except Exception:
            await self._diagnostics('backup_failure')
            raise
