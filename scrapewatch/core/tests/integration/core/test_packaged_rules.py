"""Packaged rules ship inside the wheel and drive the engine end to end."""

from scrapewatch.core import Engine, Event, JobRef, Status, load_rules, packaged_rule_files


def test_packaged_directory_contains_the_phase1_seed():
    names = [path.name for path in packaged_rule_files()]
    assert "cloudflare-challenge.yaml" in names


def test_challenge_page_from_the_contract_example_is_blocked():
    event = Event(
        url="https://shop.example.com/checkout",
        job=JobRef(name="ebay-prices", run_id="run-1"),
        captured_at="2026-11-19T00:00:00+00:00",
        status_code=403,
        headers={"server": "cloudflare"},
        body_sample=(
            '<html><head><title>Attention Required! | Cloudflare</title></head>'
            '<body><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
            "</body></html>"
        ),
    )

    verdict = Engine(rules=load_rules()).observe(event)

    assert verdict.status is Status.BLOCKED
    assert verdict.detector_id == "cloudflare-challenge"
    assert verdict.confidence == 1.0  # both fired groups matched fully, hint agrees, capped
    assert any("title_re:" in s for s in verdict.evidence["matched_signatures"])
    assert any("script_src_re:" in s for s in verdict.evidence["matched_signatures"])


def test_a_real_page_with_a_turnstile_widget_stays_ok():
    # negative corpus in miniature (core-engine.md §6): a healthy page that
    # merely mentions turnstile in prose must not trip the detector
    event = Event(
        url="https://blog.example.com/turnstile-review",
        job=JobRef(name="blog-posts", run_id="run-1"),
        captured_at="2026-11-19T00:00:00+00:00",
        status_code=200,
        body_sample=(
            "<html><head><title>Why we removed our captcha</title></head>"
            "<body><p>We evaluated Cloudflare Turnstile and hCaptcha...</p></body></html>"
        ),
    )

    rules = {rule.id for rule in load_rules()}
    assert "cloudflare-challenge" in rules
    assert Engine(rules=load_rules()).observe(event).status is Status.OK
