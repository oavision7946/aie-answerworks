"""The dashboard link, the session cookie and the proxy in front of Grafana."""

import unittest
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import respx
from sqlalchemy.orm import Session

from app.core import grafana_auth
from app.core.grafana_auth import launch_token, session_token
from app.db.models import Role
from app.db.repositories import user_repo
from tests.auth_helpers import AuthTestCase

MONITORING_SECRET = "monitoring-secret-with-more-than-32-characters"
GRAFANA = "http://grafana.test:3000"
PUBLIC = "https://dashboards.example.com"


class DashboardTestCase(AuthTestCase):
    def setUp(self):
        super().setUp()
        grafana_auth.reset()
        self.addCleanup(grafana_auth.reset)
        env = self.settings.env
        env.monitoring_jwt_secret = MONITORING_SECRET
        env.grafana_url = GRAFANA
        env.api_public_url = "http://localhost:8000"
        self.monitor = self.add_user("monitor@example.com", role=Role.MONITOR)
        self.admin = self.add_user("admin@example.com", role=Role.ADMIN)
        self.alice = self.add_user("alice@example.com")

    def link_token(self, user) -> str:
        response = self.client.post("/monitoring/token", headers=self.headers(user))
        self.assertEqual(response.status_code, 200)
        return parse_qs(urlparse(response.json()["login_url"]).query)["token"][0]

    def sign_in(self, user) -> dict[str, str]:
        """Use a fresh link and return the request headers a browser would then send."""
        response = self.client.get(
            "/monitoring/login", params={"token": self.link_token(user)}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        return {"Cookie": f"aw_monitoring={response.cookies['aw_monitoring']}"}

    def change(self, user, **fields):
        with Session(self.engine, expire_on_commit=False) as db:
            stored = user_repo.get_by_id(db, user.id)
            for name, value in fields.items():
                setattr(stored, name, value)
            user_repo.save(db, stored)


class TestDashboardToken(DashboardTestCase):
    def test_monitors_and_administrators_get_a_link(self):
        for user in (self.monitor, self.admin):
            with self.subTest(role=user.role):
                response = self.client.post("/monitoring/token", headers=self.headers(user))

                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["expires_in"], 300)
                self.assertTrue(
                    body["login_url"].startswith("http://localhost:8000/monitoring/login?token=")
                )

    def test_the_link_uses_the_public_address_of_the_api(self):
        self.settings.env.api_public_url = PUBLIC + "/"

        response = self.client.post("/monitoring/token", headers=self.headers(self.monitor))

        self.assertTrue(response.json()["login_url"].startswith(f"{PUBLIC}/monitoring/login?"))

    def test_the_link_carries_a_launch_token_for_the_caller(self):
        token = self.link_token(self.monitor)

        claims = jwt.decode(token, MONITORING_SECRET, algorithms=["HS256"])

        self.assertEqual(claims["sub"], str(self.monitor.id))
        self.assertEqual(claims["type"], "monitoring_launch")

    def test_regular_users_and_anonymous_callers_are_refused(self):
        self.assertEqual(self.client.post("/monitoring/token").status_code, 401)
        response = self.client.post("/monitoring/token", headers=self.headers(self.alice))
        self.assertEqual(response.status_code, 403)

    def test_a_pending_password_change_or_deactivation_is_refused(self):
        self.change(self.monitor, must_change_password=True)
        response = self.client.post("/monitoring/token", headers=self.headers(self.monitor))
        self.assertEqual(response.status_code, 403)

        self.change(self.monitor, must_change_password=False, is_active=False)
        response = self.client.post("/monitoring/token", headers=self.headers(self.monitor))
        self.assertEqual(response.status_code, 403)

    def test_without_a_secret_the_dashboards_are_off(self):
        self.settings.env.monitoring_jwt_secret = ""

        response = self.client.post("/monitoring/token", headers=self.headers(self.monitor))

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])


class TestDashboardLogin(DashboardTestCase):
    def login(self, token):
        return self.client.get("/monitoring/login", params={"token": token}, follow_redirects=False)

    def test_a_link_gives_a_private_cookie_and_moves_on_to_the_dashboards(self):
        response = self.login(self.link_token(self.monitor))

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/monitoring/grafana/")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["cache-control"], "no-store")
        cookie = response.headers["set-cookie"].lower()
        for part in ("httponly", "samesite=strict", "path=/monitoring", "max-age=3600"):
            self.assertIn(part, cookie)
        self.assertNotIn("secure", cookie)
        self.assertNotIn("token=", response.headers["location"])

    def test_the_cookie_is_secure_when_the_api_is_served_over_https(self):
        self.settings.env.api_public_url = PUBLIC

        response = self.login(self.link_token(self.monitor))

        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_a_link_works_once(self):
        token = self.link_token(self.monitor)

        self.assertEqual(self.login(token).status_code, 303)
        self.assertEqual(self.login(token).status_code, 401)

    def test_bad_links_are_refused(self):
        expired = grafana_auth._encode(
            {"sub": str(self.monitor.id), "type": "monitoring_launch", "jti": "x"},
            timedelta(seconds=-5),
            MONITORING_SECRET,
        )
        cases = {
            "garbage": "nonsense",
            "expired": expired,
            "a session token": session_token(self.monitor.id, MONITORING_SECRET),
            "another secret": launch_token(
                self.monitor.id, "another-secret-of-more-than-32-characters"
            ),
            "an access token": self.token(self.monitor),
        }
        for name, token in cases.items():
            with self.subTest(link=name):
                response = self.login(token)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("set-cookie", response.headers)

    def test_losing_access_before_using_the_link_is_final(self):
        token = self.link_token(self.monitor)
        self.change(self.monitor, role=Role.USER)

        self.assertEqual(self.login(token).status_code, 403)

    def test_a_deactivated_account_gets_no_cookie(self):
        token = self.link_token(self.monitor)
        self.change(self.monitor, is_active=False)

        response = self.login(token)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("set-cookie", response.headers)

    def test_a_deleted_account_gets_no_cookie(self):
        token = launch_token(uuid.uuid4(), MONITORING_SECRET)

        self.assertEqual(self.login(token).status_code, 403)

    def test_the_token_is_required_and_the_secret_must_be_set(self):
        self.assertEqual(self.client.get("/monitoring/login").status_code, 422)
        self.settings.env.monitoring_jwt_secret = ""
        self.assertEqual(self.login("x").status_code, 503)


class TestDashboardProxy(DashboardTestCase):
    def setUp(self):
        super().setUp()
        self.upstream = respx.mock(assert_all_called=False)
        self.upstream.start()
        self.addCleanup(self.upstream.stop)

    def get(self, path, cookie=None, **kwargs):
        headers = {**(cookie or {}), **kwargs.pop("headers", {})}
        return self.client.get(f"/monitoring/grafana/{path}", headers=headers, **kwargs)

    def test_no_cookie_no_dashboards(self):
        route = self.upstream.route().respond(200)

        self.assertEqual(self.get("").status_code, 401)
        self.assertEqual(self.get("", {"Cookie": "aw_monitoring=nonsense"}).status_code, 401)
        self.assertEqual(self.get("", {"Cookie": "other=1"}).status_code, 401)
        self.assertFalse(route.called)

    def test_a_bearer_token_is_not_a_dashboard_session(self):
        route = self.upstream.route().respond(200)

        response = self.get("", headers=self.headers(self.admin))

        self.assertEqual(response.status_code, 401)
        self.assertFalse(route.called)

    def test_an_access_token_in_the_cookie_is_not_a_session(self):
        route = self.upstream.route().respond(200)

        response = self.get("", {"Cookie": f"aw_monitoring={self.token(self.admin)}"})

        self.assertEqual(response.status_code, 401)
        self.assertFalse(route.called)

    def test_requests_reach_grafana_as_a_viewer(self):
        route = self.upstream.get(f"{GRAFANA}/monitoring/grafana/d/health").respond(
            200, text="dashboard", headers={"Content-Type": "text/html"}
        )
        cookie = self.sign_in(self.monitor)

        response = self.get("d/health", cookie, params={"orgId": "1", "var-x": "a b"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "dashboard")
        self.assertEqual(response.headers["content-type"], "text/html")
        sent = route.calls.last.request
        self.assertEqual(dict(sent.url.params), {"orgId": "1", "var-x": "a b"})
        claims = jwt.decode(
            sent.headers["x-jwt-assertion"], MONITORING_SECRET, algorithms=["HS256"]
        )
        self.assertEqual(claims["sub"], "monitor@example.com")
        self.assertEqual(claims["role"], "Viewer")

    def test_administrators_are_viewers_too(self):
        route = self.upstream.get(url__startswith=GRAFANA).respond(200)
        cookie = self.sign_in(self.admin)

        self.get("", cookie)

        sent = route.calls.last.request
        claims = jwt.decode(
            sent.headers["x-jwt-assertion"], MONITORING_SECRET, algorithms=["HS256"]
        )
        self.assertEqual((claims["sub"], claims["role"]), ("admin@example.com", "Viewer"))

    def test_credentials_of_the_caller_never_reach_grafana(self):
        route = self.upstream.get(url__startswith=GRAFANA).respond(200)
        cookie = self.sign_in(self.monitor)
        spoof = jwt.encode(
            {"sub": "root", "role": "Admin"},
            "a-guessed-secret-of-32-characters-or-so",
            algorithm="HS256",
        )

        self.get(
            "x",
            {"Cookie": f"{cookie['Cookie']}; grafana_theme=dark"},
            headers={"Authorization": "Bearer secret-token", "X-JWT-Assertion": spoof},
        )

        sent = route.calls.last.request
        self.assertNotIn("authorization", sent.headers)
        self.assertNotEqual(sent.headers["x-jwt-assertion"], spoof)
        self.assertEqual(sent.headers["cookie"], "grafana_theme=dark")
        self.assertNotIn("aw_monitoring", sent.headers["cookie"])

    def test_the_cookie_is_not_forwarded_when_it_is_the_only_one(self):
        route = self.upstream.get(url__startswith=GRAFANA).respond(200)

        self.get("x", self.sign_in(self.monitor))

        self.assertNotIn("cookie", route.calls.last.request.headers)

    def test_the_original_host_is_kept_so_grafana_accepts_the_origin(self):
        route = self.upstream.post(f"{GRAFANA}/monitoring/grafana/api/ds/query").respond(
            200, json={"results": {}}
        )
        cookie = self.sign_in(self.monitor)

        response = self.client.post(
            "/monitoring/grafana/api/ds/query",
            headers={**cookie, "Origin": "http://testserver", "Content-Type": "application/json"},
            content=b'{"queries": []}',
        )

        self.assertEqual(response.json(), {"results": {}})
        sent = route.calls.last.request
        self.assertEqual(sent.headers["host"], "testserver")
        self.assertEqual(sent.headers["origin"], "http://testserver")
        self.assertEqual(sent.content, b'{"queries": []}')

    def test_the_answer_is_passed_back_as_it_is(self):
        self.upstream.get(url__startswith=GRAFANA).mock(
            return_value=httpx.Response(
                302,
                headers=[
                    ("Location", "/monitoring/grafana/login"),
                    ("Set-Cookie", "a=1; Path=/monitoring/grafana/"),
                    ("Set-Cookie", "b=2; Path=/monitoring/grafana/"),
                    ("Transfer-Encoding", "chunked"),
                ],
            )
        )
        cookie = self.sign_in(self.monitor)

        response = self.get("", cookie, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/monitoring/grafana/login")
        self.assertEqual(
            response.headers.get_list("set-cookie"),
            ["a=1; Path=/monitoring/grafana/", "b=2; Path=/monitoring/grafana/"],
        )

    def test_losing_the_role_closes_the_dashboards_at_once(self):
        route = self.upstream.get(url__startswith=GRAFANA).respond(200)
        cookie = self.sign_in(self.monitor)
        self.assertEqual(self.get("", cookie).status_code, 200)

        self.change(self.monitor, role=Role.USER)

        self.assertEqual(self.get("", cookie).status_code, 403)
        self.assertEqual(route.call_count, 1)

    def test_a_deactivated_or_deleted_account_is_shut_out(self):
        self.upstream.get(url__startswith=GRAFANA).respond(200)
        cookie = self.sign_in(self.monitor)
        self.change(self.monitor, is_active=False)
        self.assertEqual(self.get("", cookie).status_code, 403)

        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM users"))
        self.assertEqual(self.get("", cookie).status_code, 403)

    def test_an_expired_session_is_refused(self):
        expired = grafana_auth._encode(
            {"sub": str(self.monitor.id), "type": "monitoring_session"},
            timedelta(seconds=-5),
            MONITORING_SECRET,
        )

        response = self.get("", {"Cookie": f"aw_monitoring={expired}"})

        self.assertEqual(response.status_code, 401)

    def test_an_unreachable_grafana_is_a_bad_gateway(self):
        self.upstream.get(url__startswith=GRAFANA).mock(side_effect=httpx.ConnectError("down"))
        cookie = self.sign_in(self.monitor)

        response = self.get("", cookie)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "The dashboards are not reachable.")

    def test_the_bare_path_goes_to_the_dashboards(self):
        response = self.client.get("/monitoring/grafana", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/monitoring/grafana/")

    def test_the_proxy_is_not_part_of_the_published_api(self):
        paths = self.client.get("/openapi.json").json()["paths"]

        self.assertIn("/monitoring/token", paths)
        self.assertFalse([p for p in paths if "grafana" in p or p == "/monitoring/login"])


if __name__ == "__main__":
    unittest.main()
