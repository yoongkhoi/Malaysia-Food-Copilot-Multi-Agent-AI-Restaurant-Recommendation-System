"""Launch the local Gradio UI with the project on sys.path."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from food_copilot.ui.app import launch

if __name__ == "__main__":
    print("Starting local UI at http://127.0.0.1:7860", flush=True)
    launch()
