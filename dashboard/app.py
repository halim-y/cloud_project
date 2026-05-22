import streamlit as st

st.set_page_config(
    page_title="IoT Weather Station",
    page_icon="🌤",
    layout="wide",
)

pg = st.navigation([
    st.Page("pages/overview.py",  title="Overview",        icon="🏠", default=True),
    st.Page("pages/history.py",   title="History",         icon="📅"),
    st.Page("pages/forecast.py",  title="Forecast",        icon="🌤"),
    st.Page("pages/voice.py",     title="AI Assistant",    icon="🤖"),
])
pg.run()
