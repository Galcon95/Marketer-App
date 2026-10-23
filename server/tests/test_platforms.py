"""Unit tests of check_platform_fit (app/core/platforms.py), the chat tool that checks a post against a
platform's rules. Pure calculation, no model calls."""

from app.core.platforms import PLATFORM_RULES, check_platform_fit


def test_short_post_fits_x_without_issues():
    fit = check_platform_fit("Buy below intrinsic value, sell when the crowd is euphoric. #Investing #Stocks", "x")
    assert fit.fits
    assert fit.hashtags == 2
    assert fit.issues == []


def test_too_long_post_does_not_fit_and_names_the_limit():
    fit = check_platform_fit("word " * 100, "x")
    assert not fit.fits
    assert fit.max_characters == 280
    assert any("Too long" in issue for issue in fit.issues)


def test_citation_markers_are_not_counted():
    with_markers = check_platform_fit("Sell when prices are too high [1]. Buy when cheap [2]. #Stocks", "x")
    without = check_platform_fit("Sell when prices are too high. Buy when cheap. #Stocks", "x")
    assert with_markers.characters == without.characters


def test_linkedin_recommends_words_and_hashtags():
    fit = check_platform_fit("A short LinkedIn post. #a", "linkedin")
    assert fit.fits  # within the hard limit ...
    assert any("words" in issue for issue in fit.issues)  # ... but far below 80-200 words
    assert any("hashtags" in issue for issue in fit.issues)  # and 1 instead of 3-5 hashtags


def test_ai_cliches_are_reported():
    fit = check_platform_fit("Dive into this game-changer of a book! #Books", "x")
    assert any("AI-written" in issue for issue in fit.issues)


def test_every_platform_has_rules():
    assert set(PLATFORM_RULES) == {"x", "linkedin", "instagram", "facebook", "tiktok", "youtube"}
