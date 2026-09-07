from backend.safesearch import filter_safe_pages, is_safe_page


def page(**kwargs):
    base = {"url": "https://example.com/article", "title": "A normal article", "description": "Useful information", "content": "Educational content."}
    base.update(kwargs)
    return base


def test_normal_page_is_safe():
    assert is_safe_page(page())


def test_blocked_domain_is_filtered():
    assert not is_safe_page(page(url="https://pornhub.example/article"))


def test_blocked_title_is_filtered():
    assert not is_safe_page(page(title="Explicit video collection"))


def test_blocked_description_is_filtered():
    assert not is_safe_page(page(description="Adult content and explicit video"))


def test_obfuscated_url_signal_is_filtered():
    assert not is_safe_page(page(url="https://p.o.r.n.example/path"))


def test_unicode_compatibility_normalization_is_scanned():
    # Full-width ASCII letters normalize to ordinary ASCII under NFKC.
    assert not is_safe_page(page(title="Ａｄｕｌｔ Ｖｉｄｅｏ"))


def test_safe_filter_can_be_disabled():
    unsafe = page(title="Porn video")
    pages = [unsafe, page()]
    assert filter_safe_pages(pages, enabled=False) == pages


def test_safe_filter_is_fail_closed_for_invalid_page():
    assert not is_safe_page(None)  # type: ignore[arg-type]
