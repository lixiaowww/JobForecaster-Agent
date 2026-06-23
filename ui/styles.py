"""Dashboard CSS (dark glassmorphism)."""
CUSTOM_CSS = """<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    /* Main body background and font */
    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        font-family: 'Outfit', sans-serif;
        background-color: #0d1117;
        color: #f0f6fc !important;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }

    /* Ensure all text elements, widget labels, and UI headers are bright and highly legible */
    p, span, label, h1, h2, h3, h4, h5, h6, [data-testid="stWidgetLabel"] p {
        color: #f0f6fc !important;
    }

    /* Keep subtitles and muted labels styled correctly but readable */
    .subtitle {
        color: #8b949e !important;
        font-size: 1rem;
    }
    .metric-label {
        font-size: 0.8rem;
        color: #8b949e !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Header decoration */
    .header-container {
        padding: 1.5rem 0rem 1rem 0rem;
        border-bottom: 1px solid #30363d;
        margin-bottom: 1.5rem;
    }
    
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #58a6ff 0%, #bc8cff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.3rem;
    }
    
    .subtitle {
        color: #8b949e;
        font-size: 1rem;
    }
    
    /* Metric card custom styling */
    .metric-card {
        background: rgba(22, 27, 34, 0.6);
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
        backdrop-filter: blur(10px);
    }
    
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(56, 139, 253, 0.15);
        border-color: #38bdf8;
    }
    
    .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        color: #58a6ff;
        margin-bottom: 0.1rem;
    }
    
    .metric-label {
        font-size: 0.8rem;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Styling tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 45px;
        white-space: pre-wrap;
        background-color: #161b22;
        border-radius: 6px 6px 0px 0px;
        padding: 0px 16px;
        border: 1px solid #30363d;
        color: #c9d1d9;
        font-weight: 600;
    }

    .stTabs [aria-selected="true"] {
        background-color: #0d1117;
        border-bottom: 2px solid #58a6ff;
        color: #58a6ff !important;
    }
</style>
"""
