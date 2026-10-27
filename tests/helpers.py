import json
from pathlib import Path

from core.ingestion.acceptance import accept_batch
from core.ingestion.csv_import import import_facts_csv, import_posts_csv
from core.metrics.engine import compute
from core.rules.engine import run_rules
from core.schemas.project import load_project

FIXTURES = Path(__file__).parent / "fixtures" / "quantitative_samples"


def load_fixture(posts_file: str = "posts.csv", accept: bool = True):
    project = load_project(json.loads((FIXTURES / "project.json").read_text(encoding="utf-8")))
    facts = import_facts_csv((FIXTURES / "facts.csv").read_text(encoding="utf-8"), project, "batch-facts")
    posts = import_posts_csv((FIXTURES / posts_file).read_text(encoding="utf-8"), project, "batch-posts", posts_file)
    if accept:
        facts, posts = accept_batch(facts), accept_batch(posts)
    return project, facts, posts


def run_fixture(posts_file: str = "posts.csv"):
    project, facts, posts = load_fixture(posts_file)
    metrics = compute(project, facts.facts + posts.facts, posts.posts)
    findings = run_rules(project, metrics)
    return project, metrics, findings
