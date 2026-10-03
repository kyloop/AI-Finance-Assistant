"""Seed glossary + KB article metadata. Run: python -m scripts.seed_db
KB articles are Markdown files with front-matter under src/data/knowledge_base/<category>/ (spec FR-K7)."""
import re

import yaml

from src.core.config import DATA_DIR
from src.db.models import GlossaryTerm, KBDocument
from src.db.session import SessionLocal, init_db

GLOSSARY = {
    "ETF": ("A fund that holds many investments and trades on an exchange like a single stock.", "ETFs & mutual funds"),
    "Mutual fund": ("A pooled fund priced once per day, managed by a fund company.", "ETFs & mutual funds"),
    "Diversification": ("Spreading money across different investments so one bad performer hurts less.", "diversification & risk"),
    "Expense ratio": ("The yearly fee a fund charges, as a percentage of what you have invested.", "ETFs & mutual funds"),
    "Bond": ("A loan you make to a company or government in return for interest payments.", "bonds"),
    "Compound growth": ("Earning returns on your earlier returns, so growth accelerates over time.", "basics"),
    "Roth IRA": ("A retirement account funded with after-tax money; qualified withdrawals are tax-free.", "taxes & accounts"),
    "Dividend": ("A share of a company's profit paid out to its stockholders.", "stocks"),
}
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def seed() -> dict:
    init_db()
    with SessionLocal() as db:
        for term, (d, c) in GLOSSARY.items():
            db.merge(GlossaryTerm(term=term, definition=d, category=c))
        n = 0
        for path in (DATA_DIR / "knowledge_base").rglob("*.md"):
            m = FRONT.match(path.read_text())
            if not m:
                continue
            meta = yaml.safe_load(m.group(1))
            db.merge(KBDocument(id=path.stem, title=meta["title"], category=meta["category"], source_name=meta["source_name"],
                                source_url=meta["source_url"], last_reviewed=str(meta["last_reviewed"]),
                                path=str(path.relative_to(DATA_DIR))))
            n += 1
        db.commit()
    return {"glossary": len(GLOSSARY), "articles": n}


if __name__ == "__main__":
    print(seed())
