from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "update-proxies.yml"


class UpdateProxiesWorkflowTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ruby"), "Ruby is required for the optional YAML syntax check")
    def test_workflow_is_valid_yaml(self) -> None:
        result = subprocess.run(
            ["ruby", "-e", "require 'yaml'; YAML.safe_load(File.read(ARGV[0]), aliases: true)", str(WORKFLOW)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_workflow_has_scheduled_and_manual_triggers(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, re.compile(r"^\s*schedule:\s*$", re.MULTILINE))
        self.assertIn('cron: "17 */2 * * *"', workflow)
        self.assertRegex(workflow, re.compile(r"^\s*workflow_dispatch:\s*$", re.MULTILINE))

    def test_workflow_restores_validates_and_publishes_only_public_list(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertRegex(workflow, re.compile(r"permissions:\s+contents: write", re.MULTILINE))
        self.assertIn("TELETHON_SESSION_BASE64: ${{ secrets.TELETHON_SESSION_BASE64 }}", workflow)
        self.assertIn('TELETHON_SESSION_FILE=${session_file}', workflow)
        self.assertIn("uv run python -m tg_proxy_search.update_public_proxies", workflow)
        self.assertIn("validate_proxy_urls", workflow)
        self.assertIn("git diff --quiet -- proxies.txt", workflow)
        self.assertIn("git add proxies.txt", workflow)


if __name__ == "__main__":
    unittest.main()
