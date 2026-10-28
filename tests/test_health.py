import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import health


def health_config():
    return {'backup':{'models':[{
        'workspace_name':'Workspace',
        'workspace_id':'A'*32,
        'model_name':'Model',
        'model_id':'B'*32,
        'enabled':True,
        'tags':['daily'],
    }]}}


class HealthCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_check_preflights_without_copying(self):
        browser=AsyncMock()
        browser.preflight_target.return_value={'status':'PREFLIGHT_OK'}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(health,'AnaplanBrowser',return_value=browser), \
                patch.object(health,'load_credentials',return_value=('user@example.com','secret')), \
                patch.dict(os.environ,{'ANAPLAN_BROWSER_AUTO_LOGIN':'true'},clear=True):
            root=Path(tmp)
            results,report=await health.run_health_check(
                health_config(),root,root/'logs')
            self.assertFalse(any(item['status']=='FAILED' for item in results))
            self.assertTrue(report.exists())
            browser.start.assert_awaited_once()
            browser.ensure_authenticated.assert_awaited_once()
            browser.preflight_target.assert_awaited_once()
            self.assertFalse(hasattr(browser,'copy_and_archive') and
                             browser.copy_and_archive.await_count)
            browser.stop.assert_awaited_once()

    async def test_missing_auto_login_email_stops_before_browser(self):
        browser=AsyncMock()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(health,'AnaplanBrowser',return_value=browser), \
                patch.object(health,'load_credentials',return_value=('','')), \
                patch.dict(os.environ,{'ANAPLAN_BROWSER_AUTO_LOGIN':'true'},clear=True):
            root=Path(tmp)
            results,_=await health.run_health_check(health_config(),root,root/'logs')
            self.assertTrue(any(item['check']=='credentials' and item['status']=='FAILED'
                                for item in results))
            browser.start.assert_not_awaited()

    async def test_notification_test_reports_delivery(self):
        browser=AsyncMock()
        browser.preflight_target.return_value={'status':'PREFLIGHT_OK'}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(health,'AnaplanBrowser',return_value=browser), \
                patch.object(health,'load_credentials',return_value=('user@example.com','secret')), \
                patch.object(health,'notify',return_value=[{'channel':'webhook','delivered':True}]), \
                patch.dict(os.environ,{'ANAPLAN_BROWSER_AUTO_LOGIN':'true'},clear=True):
            root=Path(tmp)
            results,_=await health.run_health_check(
                health_config(),root,root/'logs',test_notification=True)
            self.assertTrue(any(item['check']=='notification_webhook' and item['status']=='PASS'
                                for item in results))

    async def test_health_check_tag_filter_with_no_match_fails_cleanly(self):
        browser=AsyncMock()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(health,'AnaplanBrowser',return_value=browser), \
                patch.object(health,'load_credentials',return_value=('user@example.com','secret')), \
                patch.dict(os.environ,{'ANAPLAN_BROWSER_AUTO_LOGIN':'true'},clear=True):
            root=Path(tmp)
            results,_=await health.run_health_check(
                health_config(),root,root/'logs',tags=['weekly'])
            self.assertTrue(any(item['check']=='targets' and item['status']=='FAILED'
                                for item in results))
            browser.start.assert_not_awaited()


if __name__=='__main__':
    unittest.main()
