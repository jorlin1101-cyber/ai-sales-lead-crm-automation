from lead_cleaner.schemas.policy import LeadFeatures


CUSTOMER_KIND_LABELS = {
    "agency": "travel agency",
    "operator": "tour operator",
    "school": "school group",
    "corporate": "corporate group",
    "influencer": "travel influencer",
    "individual": "individual traveler",
    "unknown": "traveler",
}


def build_lead_features_query(features: LeadFeatures) -> str:
    """Build a deterministic retrieval query from approved lead features."""

    parts = [CUSTOMER_KIND_LABELS[features.customer_kind]]

    destinations = list(
        dict.fromkeys(
            destination.strip() for destination in features.destinations if destination.strip()
        )
    )
    if destinations:
        parts.append(f"destinations {' '.join(destinations)}")

    if features.group_size is not None:
        parts.append(f"group size {features.group_size} people")

    if features.requests_private_or_custom_service:
        parts.append("private custom tour")

    if features.asks_for_price:
        parts.append("pricing quotation cost")

    if features.asks_for_availability:
        parts.append("availability booking")

    if features.mentions_specific_dates:
        parts.append("specific travel dates")

    if features.requests_partnership:
        parts.append("travel partnership")

    if len(parts) == 1 and features.customer_kind == "unknown":
        parts.append("general travel product information")

    return " | ".join(parts)
