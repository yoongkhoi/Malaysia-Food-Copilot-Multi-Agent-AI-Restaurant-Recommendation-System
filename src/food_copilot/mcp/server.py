"""One shared MCP server. It exposes existing business functions and does not add agents."""

from food_copilot.data.repository import get_default_repository
from food_copilot.mcp.tools import (
    conversation_summary,
    discover_restaurants,
    get_restaurant_reviews,
    restaurant_details,
    restaurant_evidence,
    save_user_preference,
    search_restaurants,
    user_preferences,
)
from food_copilot.memory.store import MemoryStore
from food_copilot.services.discovery import DiscoveryService


def build_mcp_server(service: DiscoveryService | None = None, memory: MemoryStore | None = None, repository=None):
    from mcp.server.fastmcp import FastMCP

    if repository is None and service is not None:
        repository = service.repository
    mcp = FastMCP(
        "malaysia-food-copilot",
        instructions=(
            "Restaurant facts come only from tool results. "
            "Do not treat a user preference as a verified price, address, or halal status."
        ),
    )

    @mcp.tool(name="search_restaurants")
    def search_restaurants_tool(
        query: str,
        region: str = "",
        cuisine: str = "",
        max_budget_myr: float = 0,
        name_contains: str = "",
        exclude_ids: str = "",
    ) -> dict:
        """Search the canonical restaurant dataset and return real restaurant ids."""
        skipped = [item.strip() for item in (exclude_ids or "").split(",") if item.strip()]
        return search_restaurants(
            query,
            region=region,
            cuisine=cuisine,
            max_budget_myr=max_budget_myr,
            name_contains=name_contains,
            service=service,
            exclude_ids=skipped,
        )

    @mcp.tool(name="get_restaurant_reviews")
    def get_restaurant_reviews_tool(restaurant_id: str = "", name: str = "", limit: int = 3) -> dict:
        """Read confirmed review excerpts for one restaurant. No match returns an empty list."""
        return get_restaurant_reviews(restaurant_id=restaurant_id, name=name, limit=limit)

    @mcp.tool(name="discover_restaurants")
    def discover_restaurants_tool(query: str) -> dict:
        """Find restaurants that pass the existing region, budget, and evidence filters."""
        return discover_restaurants(query, service=service)

    @mcp.tool(name="get_restaurant_details")
    def get_restaurant_details_tool(restaurant_id: str) -> dict:
        """Read one restaurant and its stored evidence by exact restaurant id."""
        return restaurant_details(restaurant_id, repository=repository)

    @mcp.tool(name="get_restaurant_evidence")
    def get_restaurant_evidence_tool(restaurant_id: str) -> dict:
        """Read the stored address, price, and halal evidence for one restaurant id."""
        return restaurant_evidence(restaurant_id, repository=repository)

    @mcp.tool(name="get_user_preferences")
    def get_user_preferences_tool(user_id: str) -> dict:
        """Read preferences explicitly saved for one user. These are not restaurant facts."""
        return user_preferences(user_id, memory=memory)

    @mcp.tool(name="save_user_preference")
    def save_user_preference_tool(user_id: str, key: str, value: str, confirmed: bool = False) -> dict:
        """Save one preference. confirmed must be true; a one-off request is not stored."""
        return save_user_preference(user_id, key, value, confirmed, memory=memory)

    @mcp.tool(name="get_conversation_summary")
    def get_conversation_summary_tool(session_id: str) -> dict:
        """Read the stored messages for one session. This does not invent a summary."""
        return conversation_summary(session_id, memory=memory)

    return mcp


def main() -> None:
    repository = get_default_repository()
    build_mcp_server(
        service=DiscoveryService(repository=repository),
        memory=MemoryStore(),
        repository=repository,
    ).run(transport="stdio")
