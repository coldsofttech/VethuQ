"""End to end: the GitHub tier against a real test repository (github-e2e.yml, on release tags).

Needs `vethuq` with the `vethuq-addon-github` add-on, a throwaway repository you own (`E2E_REPO`,
`owner/name`, public, so the minutes are free) and a fine-grained token for it
(`VETHUQ_GITHUB_TOKEN`). It sets the runner up, sends one scanned English page through
`index.run(tier="github")`, waits for the result, checks the text and that nothing is left behind.
Everything is encrypted; the page is a fixture of the repository. Exit code 0 only if all held.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "invoice.png"
WAIT_MINUTES = 25


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"end to end failed: {message}")


def main() -> int:
    from vethuq.addons.github import GitHub

    from vethuq import VethuQ

    owner, _, repo = os.environ["E2E_REPO"].partition("/")
    with tempfile.TemporaryDirectory(prefix="vethuq-e2e-") as folder:
        docs = Path(folder) / "docs"
        docs.mkdir()
        shutil.copy(FIXTURE, docs / FIXTURE.name)
        with VethuQ(db_path=Path(folder) / "db" / "vethuq.db") as client:
            github = GitHub(client)
            github.setup(repo, owner=owner, private=False, create=False, adopt=True)
            report = github.doctor()
            _require(not report.problems, f"doctor found: {report.problems}")
            client.sources.create(docs)
            run = client.index.run(tier="github", wait=True, timeout=WAIT_MINUTES * 60)
            _require(run.status.value == "completed", f"the run ended {run.status}")
            found = client.search.run("the", engine="like")
            _require(found.total > 0, "the page was read but nothing was found in it")
            left = github.cleanup(older_than_minutes=0)
            _require((left.releases, left.artifacts) == (0, 0), f"left behind: {left}")
    print("end to end: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
