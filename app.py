from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from bs4 import BeautifulSoup

st.set_page_config(page_title="PriceGauger Alpha", page_icon="📡", layout="wide")

CHANNEL = "Middle_East_Spectator"
ASSETS = {
    "Brent": "BZ=F",
    "Silver": "SI=F",
    "Gold": "GC