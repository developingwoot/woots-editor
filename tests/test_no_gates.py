"""There are no approval gates (ADR 0003): stages are drafts and done means the file exists. The words must not creep back into code, prompts or screens."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORDS = re.compile(r"\bapprov\w*|\bgates?\b|\bfrozen\b", re.I)
# (file, text on the line): the few places the word means something else or reads old files
ALLOWED = [("tools/sectionrender.py", "lavs gate to digital silence"),                    # an audio noise gate
           ("tools/shortsapp.py", "LEGACY_STATUS"),                                        # project files from older versions say "approved"
           ("tools/workflow.py", '"gates" key'),                                           # old state files still hold one; it is ignored
           ("tools/review_app/server.py", "nothing waits for a sign-off")]


def test_the_words_of_the_old_approval_system_are_gone():
    files = [*ROOT.glob("tools/*.py"), *ROOT.glob("tools/review_app/*.py"), *ROOT.glob("tools/review_app/static/**/*.js"),
             *ROOT.glob("tools/review_app/static/**/*.html"), *ROOT.glob("skills/**/*.md"), *ROOT.glob("skills/**/*.json")]
    found = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        for n, line in enumerate(f.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
            if WORDS.search(line) and not any(rel == r and s in line for r, s in ALLOWED):
                found.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not found, "\n".join(found)
