"""The shared access password.

What these pin down is mostly the ways a gate is *almost* a gate: it covers the
API but not the files mount, it covers the app but not the health probe the
platform restarts you for, it signs a cookie with a secret that changes on every
deploy, it takes `next=//evil.com` at face value. Each test below is one of
those.
"""
import time
import unittest

from fastapi.testclient import TestClient
from unittest.mock import patch

from app import access, config
from app.main import app

PASSWORD = "paper-gate-9f2a"


def client():
    return TestClient(app, follow_redirects=False)


class GateOffTests(unittest.TestCase):
    """No password set is the local case, and it must be untouched."""

    def test_no_password_means_no_gate(self):
        with patch.object(config, "ACCESS_PASSWORD", ""):
            self.assertEqual(client().get("/").status_code, 200)
            self.assertFalse(access.enabled())

    def test_the_login_page_sends_you_home_when_there_is_nothing_to_unlock(self):
        with patch.object(config, "ACCESS_PASSWORD", ""):
            response = client().get("/login")
        self.assertEqual((response.status_code, response.headers["location"]), (303, "/"))


class GatedTests(unittest.TestCase):
    def setUp(self):
        access._fails.clear()
        self.password = patch.object(config, "ACCESS_PASSWORD", PASSWORD)
        self.password.start()
        self.addCleanup(self.password.stop)
        self.client = client()

    def unlocked(self):
        """Through the real form: a cookie injected into the test jar carries no
        domain, so the server's own delete_cookie never matches it."""
        self.client.post("/api/login", data={"password": PASSWORD})
        return self.client

    # ---------- what the gate covers ----------

    def test_the_studio_redirects_to_the_login_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=%2F")

    def test_an_api_call_is_401_not_a_redirect(self):
        """A fetch() following a 303 would hand JSON.parse an HTML login page."""
        response = self.client.get("/api/projects")
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_the_files_mount_is_behind_the_gate_too(self):
        """data/ holds the papers themselves and every rendered video. A gate on
        /api only would leave the whole directory open to anyone with a URL."""
        self.assertEqual(self.client.get("/files/anything/paper.pdf").status_code, 401)

    def test_the_frontend_source_is_behind_the_gate_too(self):
        self.assertEqual(self.client.get("/assets/studio.js").status_code, 401)

    def test_the_watch_page_needs_the_password(self):
        response = self.client.get("/watch/sample")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=%2Fwatch%2Fsample")

    def test_the_gate_runs_outside_the_origin_check(self):
        """Both must pass, but an unauthenticated stranger should be told the
        password is missing, not be handed a CSRF message that implies the
        request would otherwise have been served."""
        response = self.client.post("/api/run_all", headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 401)

    # ---------- what stays open ----------

    def test_the_liveness_probe_stays_open(self):
        """Gating it gets the container restarted forever while it serves fine."""
        response = self.client.get("/api/ping")
        self.assertEqual((response.status_code, response.json()), (200, {"ok": True}))

    def test_the_probe_says_nothing_about_the_work_in_flight(self):
        """/api/health carries build staleness and the job count; that is for the
        operator and stays gated."""
        self.assertEqual(set(self.client.get("/api/ping").json()), {"ok"})
        self.assertEqual(self.client.get("/api/health").status_code, 401)

    # ---------- signing in ----------

    def test_the_right_password_grants_a_cookie_that_opens_the_studio(self):
        response = self.client.post("/api/login", data={"password": PASSWORD, "next": "/"})
        self.assertEqual(response.status_code, 303)
        self.assertIn(access.COOKIE, response.cookies)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_the_cookie_does_not_carry_the_password(self):
        response = self.client.post("/api/login", data={"password": PASSWORD})
        self.assertNotIn(PASSWORD, response.cookies[access.COOKIE])

    def test_the_cookie_is_httponly_so_a_script_cannot_read_it(self):
        response = self.client.post("/api/login", data={"password": PASSWORD})
        self.assertIn("httponly", response.headers["set-cookie"].lower())

    def test_a_wrong_password_sets_nothing(self):
        response = self.client.post("/api/login", data={"password": "nope"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(access.COOKIE, response.cookies)

    def test_the_login_page_does_not_echo_next_into_the_markup(self):
        page = self.client.get("/login", params={"next": '/"><script>x()</script>'}).text
        self.assertNotIn("<script>x()", page)

    # ---------- the cookie itself ----------

    def test_a_cookie_set_by_hand_is_really_sent(self):
        """Without this, every 'refused cookie' test below would also pass if the
        cookie were quietly never transmitted."""
        self.client.cookies.set(access.COOKIE, access.mint())
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_a_forged_cookie_is_refused(self):
        self.client.cookies.set(access.COOKIE, f"{int(time.time()) + 999}.{'0' * 64}")
        self.assertEqual(self.client.get("/").status_code, 303)

    def test_pushing_the_expiry_out_breaks_the_signature(self):
        stamp, _, mac = access.mint().partition(".")
        self.client.cookies.set(access.COOKIE, f"{int(stamp) + 86400}.{mac}")
        self.assertEqual(self.client.get("/").status_code, 303)

    def test_an_expired_cookie_is_refused(self):
        stale = str(int(time.time()) - 10)
        self.client.cookies.set(access.COOKIE, f"{stale}.{access._sign(stale)}")
        self.assertEqual(self.client.get("/").status_code, 303)

    def test_a_malformed_cookie_is_refused_rather_than_raising(self):
        for junk in ("", ".", "abc", "abc.def", "9999999999", "9999999999."):
            self.client.cookies.set(access.COOKIE, junk)
            self.assertEqual(self.client.get("/").status_code, 303, junk)

    def test_changing_the_password_revokes_every_outstanding_cookie(self):
        """This is the whole reason the signing key comes from the password and
        not from a random secret -- and the reason a redeploy does not log
        everyone out, because the key is the same on the other side."""
        issued = access.mint()
        with patch.object(config, "ACCESS_PASSWORD", "something-else"):
            self.assertFalse(access.valid(issued))

    def test_signing_out_clears_the_cookie(self):
        self.unlocked().post("/api/logout")
        self.assertEqual(self.client.get("/").status_code, 303)

    # ---------- throttling ----------

    def test_repeated_guesses_are_throttled(self):
        for _ in range(access.PER_IP):
            self.assertEqual(self.client.post("/api/login", data={"password": "nope"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", data={"password": "nope"}).status_code, 429)

    def test_a_locked_out_client_cannot_slip_the_right_password_through(self):
        for _ in range(access.PER_IP):
            self.client.post("/api/login", data={"password": "nope"})
        response = self.client.post("/api/login", data={"password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn(access.COOKIE, response.cookies)

    def test_rotating_the_forwarded_header_does_not_buy_unlimited_guesses(self):
        """x-forwarded-for is written by the client, so a per-IP counter alone is
        a counter the guesser controls. The global cap is the real limit."""
        for attempt in range(access.GLOBAL):
            self.client.post("/api/login", data={"password": "nope"},
                             headers={"x-forwarded-for": f"10.0.0.{attempt}"})
        response = self.client.post("/api/login", data={"password": "nope"},
                                    headers={"x-forwarded-for": "10.9.9.9"})
        self.assertEqual(response.status_code, 429)

    def test_flooding_the_table_does_not_reset_the_global_counter(self):
        """Purging oversized state is necessary; purging the global bucket with
        it would make the flood itself the way past the limit."""
        for attempt in range(access.GLOBAL):
            self.client.post("/api/login", data={"password": "nope"},
                             headers={"x-forwarded-for": f"10.1.{attempt // 256}.{attempt % 256}"})
        for attempt in range(access._MAX_BUCKETS + 50):
            access.note_failure(_Request(f"172.16.{attempt // 256}.{attempt % 256}"))
        self.assertLessEqual(len(access._fails), access._MAX_BUCKETS + 2)
        self.assertEqual(self.client.post("/api/login", data={"password": "nope"}).status_code, 429)

    def test_a_correct_password_clears_that_clients_failures(self):
        for _ in range(access.PER_IP - 1):
            self.client.post("/api/login", data={"password": "nope"})
        self.client.post("/api/login", data={"password": PASSWORD})
        self.assertNotIn("testclient", access._fails)

    # ---------- redirects ----------

    def test_a_protocol_relative_next_is_not_an_open_redirect(self):
        for hostile in ("//evil.example", "https://evil.example", "/\\evil.example", "/x\r\nSet-Cookie: a=b"):
            response = self.client.post("/api/login", data={"password": PASSWORD, "next": hostile})
            self.assertEqual(response.headers["location"], "/", hostile)
            self.client.cookies.clear()

    def test_the_page_you_asked_for_is_where_you_land(self):
        response = self.client.post("/api/login", data={"password": PASSWORD, "next": "/watch/sample"})
        self.assertEqual(response.headers["location"], "/watch/sample")


class CookieFlagTests(unittest.TestCase):
    """Secure must follow the browser's hop, not the app's."""

    def test_behind_a_tls_proxy_the_cookie_is_marked_secure(self):
        self.assertTrue(access._https(_Request("1.2.3.4", proto="https")))

    def test_on_plain_local_http_it_is_not(self):
        """A Secure cookie on http://localhost is dropped silently, and the login
        page just bounces back to itself with no error to go on."""
        self.assertFalse(access._https(_Request("127.0.0.1")))


class _Request:
    """The two fields access.py reads off a request, without a live server."""

    def __init__(self, ip: str, proto: str = ""):
        self.headers = {"x-forwarded-proto": proto} if proto else {}
        self.client = type("C", (), {"host": ip})()
        self.url = type("U", (), {"scheme": "http"})()


if __name__ == "__main__":
    unittest.main()
