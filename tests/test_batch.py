import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import main
from browser import FatalPageError


class BatchTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return {'backup':{'models':[
            {'workspace_name':workspace,'workspace_id':workspace,'model_name':f'empty-{model}',
             'model_id':model,'enabled':True,
             'tags':['daily'] if model in ('a','b') else ['weekly']}
            for workspace,model in [('one','a'),('one','b'),('two','c')]
        ]}}

    async def test_batch_continues_after_failure_and_closes(self):
        browser=AsyncMock()
        browser.copy_and_archive.side_effect=[{'status':'SUCCESS'},RuntimeError('failed'),{'status':'SUCCESS'}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(main,'LOG_DIR',Path(tmp)), patch.object(main,'AnaplanBrowser',return_value=browser):
            results=await main.run_backup(self.config(),live=True)
            self.assertEqual([r['status'] for r in results],['SUCCESS','FAILED','SUCCESS'])
            self.assertEqual([c.args[0].workspace for c in browser.copy_and_archive.await_args_list],['one','one','two'])
            browser.start.assert_awaited_once()
            browser.stop.assert_awaited_once()
            self.assertEqual(len(list(Path(tmp).glob('backup_results_*.json'))),1)

    async def test_fatal_page_stops_batch_and_closes_browser(self):
        browser=AsyncMock()
        browser.copy_and_archive.side_effect=FatalPageError('Verify you are human')
        with tempfile.TemporaryDirectory() as tmp, patch.object(main,'LOG_DIR',Path(tmp)), patch.object(main,'AnaplanBrowser',return_value=browser):
            with self.assertRaises(FatalPageError):
                await main.run_backup(self.config(),live=True)
            self.assertEqual(browser.copy_and_archive.await_count,1)
            browser.stop.assert_awaited_once()

    async def test_dry_run_does_not_start_browser(self):
        browser=AsyncMock()
        browser.copy_and_archive.return_value={'status':'DRY_RUN'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(main,'LOG_DIR',Path(tmp)), patch.object(main,'AnaplanBrowser',return_value=browser):
            await main.run_backup(self.config(),force_dry_run=True)
            browser.start.assert_not_awaited()
            for call in browser.copy_and_archive.await_args_list:
                self.assertTrue(call.kwargs['dry_run'])

    async def test_duplicates_and_missing_ids(self):
        cfg=self.config()
        cfg['backup']['models'].append(cfg['backup']['models'][0].copy())
        cfg['backup']['models'][1]['model_id']=''
        browser=AsyncMock()
        browser.copy_and_archive.return_value={'status':'SUCCESS'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(main,'LOG_DIR',Path(tmp)), patch.object(main,'AnaplanBrowser',return_value=browser), patch.object(main.AnaplanAPI,'resolve',side_effect=lambda t:t):
            results=await main.run_backup(cfg,live=True)
            self.assertEqual(browser.copy_and_archive.await_count,2)
            self.assertEqual(sum(r['status']=='FAILED' for r in results),1)

    async def test_test_copy_still_requires_one_target(self):
        with self.assertRaisesRegex(RuntimeError,'ONE'):
            await main.run_backup(self.config(),test_copy=True)

    async def test_tag_selects_only_matching_models(self):
        browser=AsyncMock()
        browser.copy_and_archive.return_value={'status':'DRY_RUN'}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(main,'LOG_DIR',Path(tmp)), \
                patch.object(main,'AnaplanBrowser',return_value=browser):
            await main.run_backup(self.config(),force_dry_run=True,tags=['weekly'])
            browser.copy_and_archive.assert_awaited_once()
            self.assertEqual(browser.copy_and_archive.await_args.args[0].model,'empty-c')

    async def test_multiple_tags_match_any_selected_tag(self):
        browser=AsyncMock()
        browser.copy_and_archive.return_value={'status':'DRY_RUN'}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(main,'LOG_DIR',Path(tmp)), \
                patch.object(main,'AnaplanBrowser',return_value=browser):
            await main.run_backup(
                self.config(),force_dry_run=True,tags=['daily','weekly'])
            self.assertEqual(browser.copy_and_archive.await_count,3)

    async def test_each_live_target_restarts_navigation_at_home(self):
        from browser import AnaplanBrowser
        from backup import ModelTarget
        with tempfile.TemporaryDirectory() as tmp:
            browser=AnaplanBrowser(Path(tmp))
            browser.page=AsyncMock()
            for method in ('_open_target_model','_open_model_management','_select_exact_model',
                           '_archive_exists','_invoke_copy_archive','_submit_archive_name',
                           '_verify_archive'):
                setattr(browser,method,AsyncMock())
            browser._archive_exists.return_value=False
            browser._verify_archive.return_value=True
            for workspace in ('one','two'):
                result=await browser.copy_and_archive(ModelTarget(workspace,'empty',workspace,'model'),'archive')
                self.assertEqual(result['status'],'SUCCESS')
            self.assertEqual(browser.page.goto.await_count,2)
            self.assertEqual([c.args[0].workspace_id for c in browser._open_target_model.await_args_list],['one','two'])

    async def test_existing_archive_stops_before_copy_submission(self):
        from browser import AnaplanBrowser
        from backup import ModelTarget
        with tempfile.TemporaryDirectory() as tmp:
            browser=AnaplanBrowser(Path(tmp))
            browser.page=AsyncMock()
            for method in ('_raise_if_fatal_page','_open_target_model','_open_model_management',
                           '_select_exact_model','_archive_exists','_invoke_copy_archive',
                           '_submit_archive_name','_verify_archive','_diagnostics'):
                setattr(browser,method,AsyncMock())
            browser._archive_exists.return_value=True
            with self.assertRaisesRegex(RuntimeError,'already exists'):
                await browser.copy_and_archive(
                    ModelTarget('one','empty','workspace','model'),
                    'empty_[BACKUP]_20261027_120000')
            browser._open_target_model.assert_awaited_once()
            browser._invoke_copy_archive.assert_not_awaited()
            browser._submit_archive_name.assert_not_awaited()

    async def test_transient_failure_retries_only_before_submission(self):
        from browser import AnaplanBrowser
        from backup import ModelTarget
        with tempfile.TemporaryDirectory() as tmp:
            browser=AnaplanBrowser(Path(tmp))
            browser.safe_retry_attempts=2
            browser.safe_retry_delay=0
            browser._prepare_copy_archive=AsyncMock(
                side_effect=[RuntimeError('Timed out waiting for Model Management'),None])
            browser._submit_archive_name=AsyncMock()
            browser._verify_archive=AsyncMock(return_value=True)
            browser._diagnostics=AsyncMock()
            result=await browser.copy_and_archive(
                ModelTarget('one','empty','workspace','model'),'archive')
            self.assertEqual(result['submission_state'],'confirmed')
            self.assertEqual(browser._prepare_copy_archive.await_count,2)
            browser._submit_archive_name.assert_awaited_once()

    async def test_unverified_submission_is_never_automatically_retried(self):
        from browser import AnaplanBrowser, ArchiveOperationError
        from backup import ModelTarget
        with tempfile.TemporaryDirectory() as tmp:
            browser=AnaplanBrowser(Path(tmp))
            browser.safe_retry_attempts=3
            browser.safe_retry_delay=0
            browser._prepare_copy_archive=AsyncMock()
            browser._submit_archive_name=AsyncMock()
            browser._verify_archive=AsyncMock(return_value=False)
            browser._diagnostics=AsyncMock()
            with self.assertRaises(ArchiveOperationError) as raised:
                await browser.copy_and_archive(
                    ModelTarget('one','empty','workspace','model'),'archive')
            self.assertEqual(raised.exception.submission_state,'submitted_unverified')
            browser._prepare_copy_archive.assert_awaited_once()
            browser._submit_archive_name.assert_awaited_once()
