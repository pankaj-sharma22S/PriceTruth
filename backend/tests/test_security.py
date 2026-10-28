import pytest
from app.security import validate_public_product_url


def test_only_https_configured_retailer_hosts_allowed(monkeypatch):
    monkeypatch.setattr("app.security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    assert validate_public_product_url("https://www.amazon.in/dp/example")
    with pytest.raises(ValueError):
        validate_public_product_url("http://www.amazon.in/dp/example")
    with pytest.raises(ValueError):
        validate_public_product_url("https://localhost/")


def test_rejects_private_dns_result(monkeypatch):
    monkeypatch.setattr("app.security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        validate_public_product_url("https://www.amazon.in/dp/example")


def test_robots_policy_combines_repeated_wildcard_groups_and_specific_allows():
    from app.security import RobotsPolicy
    policy = RobotsPolicy.parse("""User-agent: *
Disallow: /search?

User-agent: *
Disallow: /search
Allow: /search/product
""")
    assert policy.can_fetch("PriceTruthAI", "https://www.example.com/search/product/123")
    assert not policy.can_fetch("PriceTruthAI", "https://www.example.com/search?q=phone")


def test_robots_policy_keeps_blank_lines_inside_agent_group():
    from app.security import RobotsPolicy
    policy = RobotsPolicy.parse("""User-agent: *

Allow: /*
Disallow: /searchB
Disallow: *?q=*
""")
    assert policy.can_fetch("PriceTruthAI", "https://www.croma.com/product/p/123")
    assert not policy.can_fetch("PriceTruthAI", "https://www.croma.com/searchB?q=phone")


def test_html_robots_response_fails_closed_with_status_metadata(monkeypatch):
    import app.security as security
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(security, "_ROBOTS_CACHE", {})
    monkeypatch.setattr(security, "fetch_bounded_response", lambda *args, **kwargs: security.BoundedResponse(200, "text/html", b"<html>maintenance</html>", 17))
    with pytest.raises(security.AccessCheckError) as error:
        security.validate_permitted_page("https://www.myntra.com/search?q=phone")
    assert error.value.access_status == "rules_unavailable"
    assert error.value.http_status == 200
    assert error.value.content_type == "text/html"


def test_disallowed_search_route_is_not_requested_and_is_diagnostic(monkeypatch):
    import app.security as security
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))])
    policy = security.RobotsPolicy.parse("User-agent: *\nDisallow: /search\n", 200, "text/plain", 12)
    monkeypatch.setattr(security, "_ROBOTS_CACHE", {"https://www.ajio.com": (float("inf"), policy)})
    with pytest.raises(security.AccessCheckError) as error:
        security.validate_permitted_page("https://www.ajio.com/search/?text=phone")
    assert error.value.access_status == "disallowed"
    assert error.value.http_status == 200
