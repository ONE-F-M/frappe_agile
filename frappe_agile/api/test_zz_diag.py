import traceback
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_agile.api import github_sync


class TestZzDiag(FrappeTestCase):
	def test_diag(self):
		out = []
		try:
			from processa.agents_sandbox.customization import github_sync as pg
			out.append("import ok " + str(hasattr(pg, "org_repos")))
		except Exception:
			out.append("import fail " + traceback.format_exc()[-400:])
		try:
			out.append("tok=" + repr(frappe.get_cached_doc("Processa Settings").get_password("github_token", raise_exception=False)))
		except Exception:
			out.append("settings fail " + traceback.format_exc()[-400:])
		try:
			with patch("processa.agents_sandbox.customization.github_sync.org_repos", return_value=[]):
				out.append(str(github_sync.sync_github_repositories()))
		except Exception:
			out.append("sync fail " + traceback.format_exc()[-600:])
		self.fail("DIAG " + " | ".join(out))
