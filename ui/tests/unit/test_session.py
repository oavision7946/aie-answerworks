import unittest

from streamlit.testing.v1 import AppTest

from app.state import session


def _script():
    import streamlit as st

    from app.state import session

    session.init_messages()
    st.session_state.messages.append("kept")
    session.init_messages()  # must not wipe existing messages
    st.write(str(len(st.session_state.messages)))
    session.reset_messages()
    st.write(str(len(st.session_state.messages)))


class TestSessionState(unittest.TestCase):
    def test_init_is_idempotent_and_reset_clears(self):
        at = AppTest.from_function(_script).run()

        self.assertFalse(at.exception)
        self.assertEqual([m.value for m in at.markdown], ["1", "0"])

    def test_module_exposes_helpers(self):
        self.assertTrue(callable(session.init_messages))
        self.assertTrue(callable(session.reset_messages))


if __name__ == "__main__":
    unittest.main()
