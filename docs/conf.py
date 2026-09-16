"""Sphinx configuration — build with:  sphinx-build -b html docs docs/_build"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

project = "ml-party"
author = "Paul Krug"
copyright = "2026, Paul Krug"  # noqa: A001

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",  # GitHub gives code blocks a copy button; the site should too
]

# strip prompt characters so a copied command pastes ready to run
copybutton_prompt_text = r"\$ |>>> |\.\.\. "
copybutton_prompt_is_regex = True

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

autodoc_member_order = "bysource"
autodoc_typehints = "description"

html_theme = "furo"
html_title = "ml-party"
templates_path = []
exclude_patterns = ["_build"]
