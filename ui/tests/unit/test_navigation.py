import unittest

from app.navigation import PAGES, visible_pages


class TestVisiblePages(unittest.TestCase):
    def test_users_do_not_get_admin_pages(self):
        titles = [p.title for p in visible_pages(is_admin=False)]

        self.assertEqual(titles, ["Chat", "Conversations", "Ask"])

    def test_admins_get_everything(self):
        self.assertEqual(visible_pages(is_admin=True), list(PAGES))

    def test_exactly_one_default_page_and_it_is_chat(self):
        defaults = [p for p in PAGES if p.default]

        self.assertEqual([p.title for p in defaults], ["Chat"])

    def test_every_page_file_exists(self):
        from tests.app.helpers import APP_DIR

        for page in PAGES:
            with self.subTest(page=page.path):
                self.assertTrue((APP_DIR / page.path).is_file())
