# Copyright (c) 2026, One FM and contributors
# For license information, please see license.txt

"""The production deploy workflow must recover the site when a deploy fails.

`bench setup requirements` upgrades Python packages in place. If a later step
fails, the web server (gunicorn --preload) would keep the old packages in memory
while new files are on disk, so the failure trap has to restart the web group as
well as start the workers, and it has to be set before that step runs.
"""

from __future__ import annotations

import os

from frappe.tests.utils import FrappeTestCase

WORKFLOW = os.path.join(
	os.path.dirname(__file__), "..", "..", ".github", "workflows", "deploy-production.yml"
)
SETUP_REQUIREMENTS = "bench setup requirements frappe_agile"
WEB_RESTART = "supervisorctl restart $NAME-web:"


class TestDeployProductionWorkflow(FrappeTestCase):
	def setUp(self):
		with open(WORKFLOW) as f:
			self.lines = f.read().splitlines()

	def _trap_lines(self):
		return [i for i, line in enumerate(self.lines) if line.strip().startswith("trap ")]

	def _setup_requirements_index(self):
		matches = [i for i, line in enumerate(self.lines) if line.strip() == SETUP_REQUIREMENTS]
		self.assertEqual(len(matches), 1, "expected exactly one bench setup requirements line")
		return matches[0]

	def test_single_trap_before_setup_requirements(self):
		traps = self._trap_lines()
		self.assertEqual(len(traps), 1, "expected exactly one trap line")
		self.assertLess(traps[0], self._setup_requirements_index())

	def test_trap_starts_workers_and_restarts_web(self):
		trap = self.lines[self._trap_lines()[0]]
		self.assertIn("supervisorctl start $WORKERS", trap)
		self.assertIn(WEB_RESTART, trap)
		self.assertTrue(trap.rstrip().endswith("EXIT"))
