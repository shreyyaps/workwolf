from prompt_toolkit.styles import Style

BG = "on grey11"
FG = "white on grey11"
DIM = "grey70 on grey11"
ACCENT = "cyan on grey11"

PROMPT_STYLE = Style.from_dict(
    {
        "": "#f3f4f6 bg:#3a3a3a",
        "prompt": "ansicyan bold bg:#3a3a3a",
        "promptarrow": "#d1d5db bg:#3a3a3a",
        "bottombar": "bg:#3a3a3a #e5e7eb",
        "bottombarkey": "bg:#4b5563 #7dd3fc bold",
        "rightprompt": "#d1d5db bg:#3a3a3a",
    }
)
