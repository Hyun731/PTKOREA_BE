"""Run-level caps grow with the run size, so one click over a full plan does not starve later items."""
from app.services.research import (MAX_PAGES_PER_ITEM, MAX_PAGES_PER_RUN, MAX_POSTS_PER_RUN, MAX_QUERIES_PER_ITEM,
                                   MAX_QUERIES_PER_RUN, RunState)


def test_small_run_keeps_the_backstop():
    s = RunState(items=3, influencer_items=1)
    assert s.max_queries == MAX_QUERIES_PER_RUN
    assert s.max_pages == MAX_PAGES_PER_RUN
    assert s.max_posts == MAX_POSTS_PER_RUN


def test_full_plan_gets_room_for_every_item():
    s = RunState(items=66, influencer_items=3)
    assert s.max_queries == MAX_QUERIES_PER_ITEM * 66   # every item can use its own per-item share
    assert s.max_pages == MAX_PAGES_PER_ITEM * 66
    assert s.max_posts == MAX_POSTS_PER_RUN * 3


def test_default_state_matches_old_caps():
    s = RunState()
    assert (s.max_queries, s.max_pages, s.max_posts) == (MAX_QUERIES_PER_RUN, MAX_PAGES_PER_RUN, MAX_POSTS_PER_RUN)
