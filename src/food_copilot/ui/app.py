"""Local Gradio shell. Filtering stays in the discovery service."""

import csv
import json

from food_copilot.agents.orchestrator import get_restaurant_details, handle_message
from food_copilot.config.settings import WORK_REVIEW_PATH
from food_copilot.data.repository import get_default_repository
from food_copilot.evaluation.runner import evaluate, format_summary
from food_copilot.services.discovery import DiscoveryService


def chat_submit(message: str) -> tuple[str, str]:
    outcome = handle_message(message or "")
    constraints = {
        "constraints": outcome.get("constraints"),
        "language": outcome.get("language"),
        "needs_clarification": outcome.get("needs_clarification"),
        "exclusion_counts": outcome.get("exclusion_counts"),
        "tools_called": outcome.get("tools_called"),
        "retriever": outcome.get("retriever"),
    }
    return outcome.get("answer") or "", json.dumps(constraints, ensure_ascii=False, indent=2)


def _staging_row(restaurant_id: str) -> dict | None:
    if not WORK_REVIEW_PATH.exists():
        return None
    with WORK_REVIEW_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("restaurant_id") == restaurant_id:
                return row
    return None


def review_lookup(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "Enter a restaurant ID or part of a name. This view does not approve or import records."
    repository = get_default_repository()
    if text.startswith("MY-OSM-") or text.startswith("fixture-"):
        details = get_restaurant_details(text, repository=repository)
        rows = [details["restaurant"]] if details.get("ok") else []
        missing = None if details.get("ok") else details.get("error")
    else:
        rows = repository.search_by_name(text)
        missing = None
    lines = [
        "Canonical records come from the processed restaurant file.",
        "The staging work CSV is shown only as an unapproved side file. It is not used for recommendations.",
        f"Staging file: {WORK_REVIEW_PATH.name}",
    ]
    if missing:
        lines.append(f"No canonical record for {text} ({missing}).")
    if not rows and not missing:
        lines.append("No canonical name match.")
    for row in rows:
        price = (row.get("price_range_myr") or {}).get("status")
        halal = (row.get("halal_status") or {}).get("status")
        lines.append(
            f"\n{row.get('restaurant_id')} | {row.get('name')}\n"
            f"regions={row.get('regions')} location_verified={row.get('location_verified')} "
            f"address={row.get('address')}\n"
            f"price_status={price} halal_status={halal} family={row.get('suitable_for_family')} "
            f"record_status={row.get('record_status')}"
        )
        staged = _staging_row(row.get("restaurant_id") or "")
        if staged:
            lines.append(
                "Unapproved staging row (not imported): "
                f"review_status={staged.get('review_status')} "
                f"price_status={staged.get('price_status')} "
                f"halal_status={staged.get('halal_status')} "
                f"location_verified={staged.get('location_verified')}"
            )
        else:
            lines.append("No row in the unapproved first-batch work file.")
    return "\n".join(lines)


def evaluation_summary() -> str:
    return format_summary(evaluate(DiscoveryService()))


def launch(share: bool = False):
    import gradio as gr

    with gr.Blocks(title="Malaysia Food Copilot") as demo:
        gr.Markdown(
            "Old Klang Road pilot. Hard filters are Python rules. "
            "Unknown prices are not treated as within budget. Optional model features are off by default."
        )
        with gr.Tab("Chat"):
            message = gr.Textbox(label="Request", lines=3)
            submit = gr.Button("Submit")
            answer = gr.Textbox(label="Answer", lines=14)
            parsed = gr.Textbox(label="Extracted constraints", lines=10)
            submit.click(chat_submit, inputs=message, outputs=[answer, parsed])
        with gr.Tab("Data review"):
            lookup = gr.Textbox(label="Restaurant ID or name")
            review_button = gr.Button("Look up")
            review_out = gr.Textbox(label="Stored fields", lines=18)
            review_button.click(review_lookup, inputs=lookup, outputs=review_out)
        with gr.Tab("Evaluation"):
            eval_button = gr.Button("Run baseline evaluation")
            eval_out = gr.Textbox(label="Evaluation summary", lines=16)
            eval_button.click(evaluation_summary, inputs=[], outputs=eval_out)
    demo.launch(share=share, server_name="127.0.0.1", server_port=7860)
