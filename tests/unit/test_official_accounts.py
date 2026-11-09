"""피드백 #3·#4(SNS 채널 입력): 틱톡 채널, 1순위/2순위 구분, "기타"는 AI 후보 대상이 아님."""
from app.services import official_accounts


def test_tiktok_and_other_are_registerable_channels():
    assert "tiktok" in official_accounts.CHANNELS
    assert "other" in official_accounts.CHANNELS
    assert official_accounts.CHANNEL_LABEL["tiktok"] == "TikTok"
    assert official_accounts.CHANNEL_LABEL["other"] == "기타"


def test_primary_tier_is_blog_youtube_instagram_only():
    primary = {c for c in official_accounts.CHANNELS if official_accounts.CHANNEL_TIER.get(c, "secondary") == "primary"}
    assert primary == {"instagram", "youtube", "blog"}
    secondary = {c for c in official_accounts.CHANNELS if official_accounts.CHANNEL_TIER.get(c, "secondary") == "secondary"}
    assert secondary == {"facebook", "x", "threads", "tiktok", "other"}


def test_other_channel_is_excluded_from_ai_discovery():
    """"기타"는 사람이 직접 라벨을 붙이는 채널이라 고정 도메인이 없다 — AI 후보 스키마에서 뺀다."""
    assert "other" not in official_accounts.DISCOVERABLE_CHANNELS
    assert "other" not in official_accounts.SCHEMA["properties"]["profiles"]["items"]["properties"]["channel"]["enum"]
    assert "tiktok" in official_accounts.SCHEMA["properties"]["profiles"]["items"]["properties"]["channel"]["enum"]


def test_valid_rejects_a_tiktok_url_on_the_wrong_channel_and_accepts_a_matching_one():
    assert not official_accounts._valid("tiktok", "https://instagram.com/x")
    assert official_accounts._valid("tiktok", "https://www.tiktok.com/@brand")
