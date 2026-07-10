import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_research_generates_100_unique_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "findings.json"
            self.run_script("scripts/research.py", "--input", "data/apps.yml", "--output", str(output))
            payload = json.loads(output.read_text(encoding="utf-8"))
            findings = payload["findings"]
            self.assertEqual(len(findings), 100)
            self.assertEqual(len({row["app"] for row in findings}), 100)
            for row in findings:
                if row["credential_access"] != "unclear":
                    self.assertGreaterEqual(len(row["evidence_urls"]), 1, row["app"])

    def test_verify_and_report_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = Path(tmp) / "findings.json"
            verification = Path(tmp) / "verification.json"
            report = Path(tmp) / "index.html"
            self.run_script("scripts/research.py", "--input", "data/apps.yml", "--output", str(findings))
            self.run_script("scripts/verify.py", "--findings", str(findings), "--output", str(verification))
            self.run_script(
                "scripts/build_report.py",
                "--findings",
                str(findings),
                "--verification",
                str(verification),
                "--out",
                str(report),
            )
            verify_payload = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(verify_payload["summary"]["sample_count"], 30)
            self.assertGreaterEqual(verify_payload["summary"]["post_correction_accuracy"], 0.9)
            html = report.read_text(encoding="utf-8")
            self.assertIn("100 requested apps", html)
            self.assertIn("Full dataset", html)
            self.assertIn("Verification", html)


if __name__ == "__main__":
    unittest.main()
