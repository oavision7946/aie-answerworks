"""Page chrome: global CSS for the chat UI."""

import streamlit as st

CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap');

    :root {
        --ink: #25231f;
        --muted: #77716a;
        --line: #e7e0d7;
        --paper: #fbfaf7;
        --panel: #f3eee7;
        --accent: #c96942;
        --accent-dark: #9d482c;
    }

    .stApp {
        background: radial-gradient(circle at 50% -10%, #fffdf8 0, var(--paper) 43%, #f5f0e8 100%);
        color: var(--ink);
        font-family: 'DM Sans', sans-serif;
    }
    [data-testid="stSidebar"] {
        background: #f0ebe3;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] .stButton button {
        width: 100%;
        border: 1px solid #d9d0c5;
        background: transparent;
        color: var(--ink);
    }
    .brand {
        padding: 1.2rem 0 .8rem;
        border-bottom: 1px solid var(--line);
        margin-bottom: 1.3rem;
    }
    .brand-mark {
        color: var(--accent);
        font-size: 1.6rem;
        line-height: 1;
    }
    .brand-name {
        font-family: 'Source Serif 4', serif;
        font-size: 1.2rem;
        font-weight: 600;
        margin-top: .45rem;
    }
    .brand-copy, .side-label {
        color: var(--muted);
        font-size: .78rem;
        line-height: 1.5;
    }
    .side-label {
        text-transform: uppercase;
        letter-spacing: .09em;
        font-size: .68rem;
        margin: 1.5rem 0 .55rem;
    }
    .hero {
        padding: 3.5rem 0 2.1rem;
        text-align: center;
    }
    .hero-kicker {
        color: var(--accent-dark);
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: .8rem;
    }
    .hero h1 {
        color: var(--ink);
        font-family: 'Source Serif 4', serif;
        font-size: clamp(2.1rem, 6vw, 3.5rem);
        font-weight: 500;
        letter-spacing: 0;
        line-height: 1.1;
        margin: 0;
    }
    .hero p {
        color: var(--muted);
        font-size: .98rem;
        margin: .9rem auto 0;
        max-width: 30rem;
    }
    [data-testid="stChatMessage"] {
        background: transparent;
        border: 0;
        padding: .7rem 0;
    }
    [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
        line-height: 1.65;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        background: rgba(243, 238, 231, .72);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 1.1rem 1.2rem;
    }
    .metadata {
        border-top: 1px solid var(--line);
        color: var(--muted);
        display: flex;
        flex-wrap: wrap;
        gap: .8rem 1.3rem;
        font-size: .72rem;
        margin-top: 1rem;
        padding-top: .7rem;
    }
    .metadata strong { color: var(--ink); font-weight: 600; }
    [data-testid="stChatInput"] {
        padding-bottom: 1.5rem;
    }
    [data-testid="stChatInput"] textarea {
        background: #fffdfa;
        border: 1px solid #d8cec2;
        border-radius: 14px;
        color: var(--ink);
        min-height: 3.3rem;
    }
    [data-testid="stChatInput"] textarea:focus {
        border-color: var(--accent);
        box-shadow: 0 0 0 1px var(--accent);
    }
    .empty-note {
        color: var(--muted);
        font-size: .8rem;
        text-align: center;
        margin-top: 1.2rem;
    }
</style>
"""


def apply_styles() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
