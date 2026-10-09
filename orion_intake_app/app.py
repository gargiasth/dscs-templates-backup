"""
Orion Launchpad — entry point.

Run this file. It just sets page config and calls the minimal intake
page's render() function.

Usage:
    streamlit run app.py
"""

import streamlit as st

from pages import minimal

st.set_page_config(page_title="Orion Launchpad — Minimal Intake", layout="centered")

minimal.render()
