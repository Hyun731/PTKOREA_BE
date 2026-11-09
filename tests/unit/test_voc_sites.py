"""피드백 #5(수집 채널 확장): 아카라이브·뽐뿌가 커뮤니티 채널로 분류되는지."""
from app.services.research import VOC_SITE_CHANNEL, _host


def test_arcalive_and_ppomppu_are_classified_as_community():
    assert VOC_SITE_CHANNEL.get("arca.live") == "community"
    assert VOC_SITE_CHANNEL.get("ppomppu.co.kr") == "community"


def test_host_matches_a_subpath_url_on_the_new_sites():
    assert _host("https://arca.live/b/breaking/123456") == "arca.live"
    assert _host("https://www.ppomppu.co.kr/zboard/view.php?id=freeboard&no=1") == "ppomppu.co.kr"
