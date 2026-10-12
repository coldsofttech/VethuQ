from __future__ import annotations

from api_support import ORIGIN, TOKEN


class TestSignIn:
    def test_token_is_exchanged_for_a_strict_http_only_cookie_and_redirects_to_clean_url(
        self, client
    ):
        response = client.get(f"/?t={TOKEN}", base_url=ORIGIN)
        assert response.status_code == 303
        assert response.headers["Location"] == "/"
        cookie = response.headers["Set-Cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert TOKEN not in cookie

    def test_token_works_only_once(self, client):
        assert client.get(f"/?t={TOKEN}", base_url=ORIGIN).status_code == 303
        assert client.get(f"/?t={TOKEN}", base_url=ORIGIN).status_code == 403

    def test_wrong_token_is_refused_and_does_not_use_up_the_real_one(self, client):
        assert client.get("/?t=wrong", base_url=ORIGIN).status_code == 403
        assert client.get(f"/?t={TOKEN}", base_url=ORIGIN).status_code == 303


class TestApiAccess:
    def test_api_needs_a_session(self, client):
        response = client.get("/api/about", base_url=ORIGIN)
        assert response.status_code == 401
        assert response.get_json() == {"error": "Not signed in"}

    def test_a_forged_cookie_is_refused(self, client):
        client.set_cookie("vethuq_session", "forged", domain="127.0.0.1")
        assert client.get("/api/about", base_url=ORIGIN).status_code == 401

    def test_signed_in_client_can_use_the_api(self, signed_in):
        response = signed_in.get("/api/about", base_url=ORIGIN)
        assert response.status_code == 200
        assert response.get_json()["vethuq"] == "9.9.9"

    def test_health_is_public_and_says_nothing_else(self, client):
        response = client.get("/api/health", base_url=ORIGIN)
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_unknown_api_path_is_json_404_when_signed_in(self, signed_in):
        response = signed_in.get("/api/nope", base_url=ORIGIN)
        assert response.status_code == 404
        assert response.is_json


class TestHostAndOrigin:
    def test_unexpected_host_is_refused_even_with_a_session(self, signed_in):
        assert signed_in.get("/api/about", base_url="http://evil.example:5000").status_code == 403
        assert signed_in.get("/api/about", base_url="http://localhost:5000").status_code == 403

    def test_post_without_origin_is_refused(self, signed_in):
        assert signed_in.post("/api/window/maximize", base_url=ORIGIN).status_code == 403

    def test_post_from_another_origin_is_refused(self, signed_in):
        response = signed_in.post(
            "/api/window/maximize", base_url=ORIGIN, headers={"Origin": "http://evil.example"}
        )
        assert response.status_code == 403

    def test_post_from_own_origin_is_accepted(self, signed_in, window):
        response = signed_in.post(
            "/api/window/maximize", base_url=ORIGIN, headers={"Origin": ORIGIN}
        )
        assert response.status_code == 200
        assert window.calls == ["maximize"]


class TestHeaders:
    def test_every_response_carries_the_security_headers(self, client):
        response = client.get("/api/health", base_url=ORIGIN)
        csp = response.headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "default-src 'self'" in csp
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"

    def test_no_cors_headers_are_ever_sent(self, signed_in):
        response = signed_in.get("/api/about", base_url=ORIGIN, headers={"Origin": ORIGIN})
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_api_responses_are_not_cached(self, signed_in):
        assert signed_in.get("/api/about", base_url=ORIGIN).headers["Cache-Control"] == "no-store"
