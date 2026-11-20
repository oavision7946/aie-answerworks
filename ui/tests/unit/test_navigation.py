import unittest

from app.navigation import PAGES, visible_pages


class TestVisiblePages(unittest.TestCase):
    def test_users_do_not_get_admin_or_monitoring_pages(self):
        titles = [p.title for p in visible_pages("user")]

        self.assertEqual(titles, ["Chat", "Conversations", "Documents", "Ask"])

    def test_monitors_get_the_monitoring_page_and_no_admin_page(self):
        titles = [p.title for p in visible_pages("monitor")]

        self.assertEqual(titles, ["Chat", "Conversations", "Documents", "Ask", "Monitoring"])

    def test_admins_get_everything(self):
        self.assertEqual(visible_pages("admin"), list(PAGES))

    def test_an_unknown_role_is_treated_like_a_user(self):
        self.assertEqual(visible_pages("guest"), visible_pages("user"))

    def test_exactly_one_default_page_and_it_is_chat(self):
        defaults = [p for p in PAGES if p.default]

        self.assertEqual([p.title for p in defaults], ["Chat"])

    def test_every_page_file_exists(self):
        from tests.app.helpers import APP_DIR

        for page in PAGES:
            with self.subTest(page=page.path):
                self.assertTrue((APP_DIR / page.path).is_file())
