"""Dev helper: build + render the quantitative fixture deck and a contact sheet."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.composition.build import BuildInputs, build_deck  # noqa: E402
from core.rendering.pptx_renderer import render_deck  # noqa: E402
from core.rendering.preview import render_pages  # noqa: E402
from tests.helpers import load_fixture  # noqa: E402
from tools.contact_sheet import sheet  # noqa: E402

posts = sys.argv[1] if len(sys.argv) > 1 else "posts.csv"
out = Path("var/dev") / posts.replace(".csv", "")
p, f, po = load_fixture(posts)
r = build_deck(BuildInputs(project=p, facts=f.facts + po.facts, posts=po.posts, generated_on=date(2026, 10, 12)))
pptx = render_deck(r.deck, out / "report.pptx")
pages = render_pages(pptx, out / "preview")
sheet(pages, out / "sheet.png", 3)
print(out, len(pages))
