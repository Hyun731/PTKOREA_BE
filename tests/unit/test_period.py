"""Research period rule: activity date wins, publish date is a fallback with a small lead/tail window."""
from datetime import date

from app.services.period import classify, published_in_search_window

S, E = date(2026, 1, 1), date(2026, 9, 30)


def test_activity_date_decides():
    assert classify(S, E, date(2026, 3, 1), None, date(2025, 1, 1))[0] == "in"  # old article, in-period activity
    assert classify(S, E, date(2025, 12, 1), date(2026, 1, 15), None)[0] == "in"  # a run that overlaps the start
    st, why = classify(S, E, date(2026, 10, 7), None, date(2026, 10, 7))
    assert st == "out" and why.startswith("조사 기간 밖") and "2026.10.07" in why


def test_publish_date_fallback():
    assert classify(S, E, None, None, date(2026, 5, 1))[0] == "in"
    assert classify(S, E, None, None, date(2025, 12, 20))[0] == "check"  # announcement just before the start
    assert classify(S, E, None, None, date(2021, 1, 1))[0] == "out"
    assert classify(S, E, None, None, date(2026, 10, 30))[0] == "out"
    assert classify(S, E, None, None, None)[0] == "check"
    assert published_in_search_window(None, S, E) and not published_in_search_window(date(2025, 11, 1), S, E)


def test_cards_in_by_default_still_follow_the_period_rule():
    from datetime import date
    from types import SimpleNamespace as NS

    from app.services.period import AUTO_ADOPTER, apply
    item = NS(period_start=date(2026, 1, 1), period_end=date(2026, 9, 30))
    src = NS(published_at=None)
    late = NS(review_status="accepted", reviewed_by=AUTO_ADOPTER, input_path="auto", review_reason=None,
              activity_date=date(2025, 3, 1), activity_date_end=None)
    assert apply(late, item, src) == "out" and late.review_status == "excluded"
    unclear = NS(review_status="accepted", reviewed_by=AUTO_ADOPTER, input_path="auto", review_reason=None,
                 activity_date=None, activity_date_end=None)
    assert apply(unclear, item, src) == "check" and unclear.review_status == "candidate"
    person = NS(review_status="accepted", reviewed_by="kim", input_path="auto", review_reason=None,
                activity_date=date(2025, 3, 1), activity_date_end=None)
    assert apply(person, item, src) == "in" and person.review_status == "accepted"  # a person's call is kept
