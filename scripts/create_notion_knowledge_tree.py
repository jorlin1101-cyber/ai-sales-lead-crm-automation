#!/usr/bin/env python3
"""
Notion Knowledge Base Page Tree Creator (RAG v1).

Creates or reuses a Notion page tree structure for the Eastogo
inbound-travel knowledge base. Each leaf page is pre-populated with
structured business content (products, destinations, pricing, FAQ)
designed for downstream RAG chunking and retrieval.

Usage:
    python scripts/create_notion_knowledge_tree.py

Environment Variables:
    NOTION_API_KEY                   (required) Notion integration token
    NOTION_KNOWLEDGE_ROOT_PAGE_ID    (optional) existing root page to reuse
    NOTION_PARENT_PAGE_ID            (optional) parent under which to create root

    Either NOTION_KNOWLEDGE_ROOT_PAGE_ID or NOTION_PARENT_PAGE_ID must be set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
OUTPUT_PATH = Path("data/knowledge_snapshot/notion_page_tree_ids.json")

# ---------------------------------------------------------------------------
# Page tree definition
#   A dict key with a dict value → folder (nested children)
#   A dict key with a string value → leaf content page (string = content type)
# ---------------------------------------------------------------------------

PAGE_TREE: dict[str, Any] = {
    "AI Sales Knowledge Base": {
        "Products": {
            "Western Sichuan": {"Western Sichuan Private Tour": "product"},
            "Tibet": {"Tibet Cultural Tour": "product"},
            "Yunnan": {"Yunnan Family Tour": "product"},
        },
        "Destinations": {
            "Western Sichuan Destination Overview": "destination",
            "Tibet Destination Overview": "destination",
            "Yunnan Destination Overview": "destination",
        },
        "Pricing": {
            "Private Tour Pricing Rules": "pricing",
        },
        "FAQ": {
            "Travel Permit and Payment FAQ": "faq",
        },
    }
}


# ---------------------------------------------------------------------------
# Content builders – return list of Notion API block objects
# ---------------------------------------------------------------------------

def _text(text: str) -> dict[str, Any]:
    """Shortcut for a single rich_text item."""
    return {"type": "text", "text": {"content": text}}


def _heading_2(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [_text(text)]},
    }


def _heading_3(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [_text(text)]},
    }


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [_text(text)]},
    }


def _bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [_text(text)]},
    }


def _build_product_blocks(
    items_suitable: list[str],
    items_experiences: list[str],
    items_duration: list[str],
    items_season: list[str],
    items_pricing: list[str],
    items_sales: list[str],
) -> list[dict[str, Any]]:
    """Build blocks for a product-style page."""
    blocks: list[dict[str, Any]] = []
    blocks.append(_heading_2("Suitable For"))
    for item in items_suitable:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Key Experiences"))
    for item in items_experiences:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Typical Duration"))
    for item in items_duration:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Best Season"))
    for item in items_season:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Pricing Notes"))
    for item in items_pricing:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Sales Follow-up Notes"))
    for item in items_sales:
        blocks.append(_bullet(item))
    return blocks


def _build_destination_blocks(
    items_overview: list[str],
    items_best_for: list[str],
    items_style: list[str],
    items_seasonality: list[str],
    items_operations: list[str],
    items_sales: list[str],
) -> list[dict[str, Any]]:
    """Build blocks for a destination-style page."""
    blocks: list[dict[str, Any]] = []
    blocks.append(_heading_2("Region Overview"))
    for item in items_overview:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Best For"))
    for item in items_best_for:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Travel Style"))
    for item in items_style:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Seasonality"))
    for item in items_seasonality:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Operational Notes"))
    for item in items_operations:
        blocks.append(_bullet(item))
    blocks.append(_heading_2("Sales Follow-up Notes"))
    for item in items_sales:
        blocks.append(_bullet(item))
    return blocks


# ---------------------------------------------------------------------------
# Page content data
# ---------------------------------------------------------------------------

PAGE_CONTENT: dict[str, list[dict[str, Any]]] = {
    "Western Sichuan Private Tour": _build_product_blocks(
        items_suitable=[
            "Travel agencies and tour operators seeking custom group programs for western Sichuan.",
            "Small to medium private groups (2–16 pax) wanting a guided road trip experience.",
            "Cultural travelers interested in Tibetan Buddhist monasteries and highland scenery.",
            "Photography enthusiasts targeting Tagong Grassland, Yading Nature Reserve, and mountain landscapes.",
        ],
        items_experiences=[
            "Scenic drive along the Sichuan-Tibet Highway (G318) with stops at Kangding, Xinduqiao, and Tagong.",
            "Visit to Yading Nature Reserve — three sacred snow peaks, alpine lakes, and yak pastures.",
            "Tibetan monastery tours: Lithang Monastery, Tagong Monastery, and local Gompa visits.",
            "Cultural encounters with Khampa Tibetan families, including butter tea and tsampa making.",
        ],
        items_duration=[
            "Standard itinerary: 8 days / 7 nights (Chengdu → Kangding → Litang → Daocheng → Yading → return).",
            "Extended option: 10–12 days to include Danba Valley, Sêrtar (Larung Gar), and Luhuo.",
            "Custom duration available for agency groups; minimum 5 days for a condensed western loop.",
        ],
        items_season=[
            "Best travel window: May through October. July–August offers green pastures and active festivals.",
            "Peak foliage season: October (golden highland autumn). Also the busiest period — book early.",
            "Winter (November–March): many high passes may be closed due to snow; not recommended for first-time visitors.",
            "Spring (April–May): cooler temperatures, fewer crowds, occasional road maintenance delays.",
        ],
        items_pricing=[
            "Pricing is heavily driven by group size — larger groups receive a lower per-person rate for transport and guide.",
            "Hotel level (comfortable 3-star vs premium 4–5-star) is the second largest variable after group size.",
            "Highland surcharge may apply for routes passing above 4000 m (extra oxygen, driver allowance).",
            "Quotations should clearly separate land package (transport + guide + accommodation) from internal flights (if Chengdu-Daocheng air segment is used).",
        ],
        items_sales=[
            "Confirm whether the client wants to include the Yading horse trek — it adds half a day and has limited daily capacity.",
            "Ask if the client has specific Tibetan monastery interests — some monasteries charge separate photography fees.",
            "For agency groups, check if they need English-Chinese bilingual guide or English-only; bilingual costs extra.",
            "Recommend altitude acclimatisation in Kangding (2900 m) for 1–2 nights before proceeding higher.",
        ],
    ),
    "Tibet Cultural Tour": _build_product_blocks(
        items_suitable=[
            "Cultural travellers and history enthusiasts seeking an in-depth exploration of Tibet.",
            "Small private groups (2–10 pax) wanting a guided tour with structured itinerary.",
            "Agency clients organising cultural tours for clients with strong interest in Tibetan Buddhism.",
            "Return visitors who have already toured eastern China and now want a dedicated Tibet experience.",
        ],
        items_experiences=[
            "Lhasa city tour: Potala Palace, Jokhang Temple, Barkhor Street kora circuit.",
            "Sacred lakes excursion: Yamdrok Lake (turquoise highland lake) and Namtso Lake (heavenly lake).",
            "Gyantse and Shigatse heritage tour: Pelkor Chöde Monastery, Tashilhunpo Monastery.",
            "Everest Base Camp (EBC) extension for adventure-minded travellers — permits and 4×4 required.",
        ],
        items_duration=[
            "Essential Lhasa itinerary: 5 days / 4 nights (includes acclimatisation day).",
            "Full cultural circuit: 8–10 days covering Lhasa, Gyantse, Shigatse, and EBC.",
            "Extended tour (12–14 days) for Mt Kailash kora — available only in May–September.",
        ],
        items_season=[
            "Peak season: April to October. Best weather is May–June and September–October.",
            "July–August is warm but also the monsoon season — rain possible especially in eastern Tibet.",
            "Winter (November–March): cold but fewer tourists; Potala and Jokhang remain open; some passes may be icy.",
            "Festival highlights: Saga Dawa (May/June) and Shoton (August) — book well in advance.",
        ],
        items_pricing=[
            "Tibet tour pricing is higher than western Sichuan due to mandatory guided tour requirement and permit processing fees.",
            "Group size affects per-person land cost significantly — 4–6 pax is the sweet spot for cost and comfort.",
            "Hotel level options: comfortable 3-star in Lhasa city, basic guesthouses in remote areas (no 5-star outside Lhasa).",
            "Vehicle: 4WD Land Cruiser or similar required for EBC extension; standard minibus for Lhasa–Shigatse highway sections.",
        ],
        items_sales=[
            "Remind clients well in advance: Tibet Travel Permit requires passport scan at least 14 working days before departure.",
            "Confirm whether the client requires the alien travel permit for areas beyond Lhasa (Nagari, Mount Kailash).",
            "Ask about any health concerns related to high altitude (Lhasa 3650 m, EBC 5200 m).",
            "Agency clients: clarify if they need the guide to meet the group at Lhasa airport or join from Chengdu.",
        ],
    ),
    "Yunnan Family Tour": _build_product_blocks(
        items_suitable=[
            "Family groups (2–8 pax) including children and elderly members seeking a relaxed multi-destination tour.",
            "Multi-generational travellers wanting a safe, well-supported itinerary with diverse scenery and culture.",
            "Agency clients organising family trips to Yunnan for small private groups.",
            "First-time China visitors who prefer a mild climate and easier travel conditions than Tibet or western Sichuan.",
        ],
        items_experiences=[
            "Old Town of Lijiang (UNESCO World Heritage): cobblestone streets, canals, Naxi culture.",
            "Dali ancient town and Erhai Lake cycling — relaxed pace suitable for all ages.",
            "Shangri-La (Zhongdian): Tibetan monastery visits and Pudacuo National Park.",
            "Kunming stone forest and local flower market — a gentle start or end to the itinerary.",
        ],
        items_duration=[
            "Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).",
            "Extended family tour: 10–12 days adding Yuanyang rice terraces and Xishuangbanna (winter only).",
            "Minimum suggested duration: 6 days for a relaxed Dali + Lijiang combination without rushing.",
        ],
        items_season=[
            "Year-round destination: Yunnan has a mild climate compared to Tibet or western Sichuan.",
            "Best season: March–April for flowers, October–November for clear skies and pleasant temperatures.",
            "Summer (June–August): rainy season in central Yunnan, but still travelable with proper gear.",
            "Winter (December–February): cold in Shangri-La (down to -10°C) but mild in Kunming and Dali.",
        ],
        items_pricing=[
            "Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.",
            "Hotel level: 4–5 star preferred for family travellers; Western-brand hotels available in major cities.",
            "Private vehicle with driver-guide recommended for families — adds cost but greatly improves convenience.",
            "Internal flights (Kunming–Shangri-La or Lijiang–Kunming) can reduce travel time but increase budget.",
        ],
        items_sales=[
            "Ask for the age range of children and elderly members — this affects activity choices and pace.",
            "Confirm whether the family prefers a private guide or a self-guided approach with pre-arranged transport.",
            "Check dietary preferences: some family members may prefer Western food or have specific dietary needs.",
            "Recommend travel insurance that covers high-altitude activities if Shangri-La or Deqin is included.",
        ],
    ),
    "Western Sichuan Destination Overview": _build_destination_blocks(
        items_overview=[
            "Western Sichuan (川西) refers to the western part of Sichuan province, culturally and geographically part of the Kham Tibetan region.",
            "The area features dramatic highland scenery: snow peaks above 6000 m, alpine lakes, vast grasslands, and deep river valleys.",
            "Major towns include Kangding (the gateway), Litang (world's highest city at 4014 m), Daocheng, and Sêrtar (Larung Gar Buddhist Academy).",
            "The region is less developed for international tourism than Tibet but offers more flexible travel arrangements.",
        ],
        items_best_for=[
            "Travellers seeking a Tibetan cultural experience without the full permit complexity of the Tibet Autonomous Region.",
            "Nature and photography enthusiasts — the landscape diversity rivals any destination in China.",
            "Small private groups wanting a customisable road trip itinerary with moderate infrastructure.",
            "Agency clients looking for a unique product that combines Tibetan culture, mountain scenery, and accessible logistics.",
        ],
        items_style=[
            "Primary travel style is private road trip with a dedicated vehicle and driver-guide.",
            "Sites are connected by national highways G318 and G227 — road conditions are generally good but mountain passes can be challenging.",
            "Accommodation ranges from comfortable 4-star hotels in Kangding and Daocheng to basic guesthouses in remote areas.",
            "Light trekking at Yading and optional horse trek add an active element to the itinerary.",
        ],
        items_seasonality=[
            "High season: July–October. October is peak for autumn colours. July–August for green grasslands and horse festivals.",
            "Shoulder season: May–June and early November. Fewer crowds and moderate weather.",
            "Low season: December–March. Many mountain passes closed; Yading may be inaccessible due to snow.",
            "Rain pattern: July–August has afternoon thunderstorms; morning sightseeing is recommended.",
        ],
        items_operations=[
            "Altitude is a key operational concern — most itineraries spend the first night at Kangding (2900 m) for acclimatisation.",
            "Road conditions: G318 is paved but subject to landslides in heavy rain. A 4WD vehicle is recommended for the full circuit.",
            "Permits: no special permits required for western Sichuan (unlike Tibet). Foreign tourists only need standard visa.",
            "Mobile network coverage is available in all towns but may be intermittent on mountain passes.",
        ],
        items_sales=[
            "For agency clients, highlight that western Sichuan offers 'Tibet-lite' culture with easier logistics and no permit delays.",
            "Ask whether the group is comfortable with daily driving distances of 4–6 hours on mountain roads.",
            "Recommend a minimum of 8 days to do a proper loop without rushing the itinerary.",
            "Spring (May–June) is the best compromise between good weather and off-peak pricing — suggest this window to price-sensitive groups.",
        ],
    ),
    "Tibet Destination Overview": _build_destination_blocks(
        items_overview=[
            "Tibet (Xizang Autonomous Region) is a high-altitude plateau with an average elevation above 4000 m, bordered by the Himalayas to the south.",
            "Lhasa, the capital, is the cultural and spiritual heart of Tibetan Buddhism, home to the Potala Palace and Jokhang Temple.",
            "Key regions include Central Tibet (Lhasa–Gyantse–Shigatse), Western Tibet (Mt Kailash and Ali), and Eastern Tibet (Nyingchi).",
            "Tourism in Tibet is regulated: all foreign tourists must join a pre-organised tour through a licensed travel agency.",
        ],
        items_best_for=[
            "Cultural and spiritual travellers interested in Tibetan Buddhism, monastery architecture, and pilgrimage traditions.",
            "Experienced high-altitude travellers comfortable with extended periods above 3500 m.",
            "Small groups (2–8 pax) wanting a structured guided tour that covers both cultural sites and natural landscapes.",
            "Return China travellers looking for a deeper, more distinctive experience beyond mainstream Chinese destinations.",
        ],
        items_style=[
            "All foreign travellers to Tibet must be part of a guided tour with a registered Tibet travel agency. Independent travel is not permitted.",
            "Tour transport is typically by private minibus (Lhasa valley) or 4WD Land Cruiser (remote areas and EBC).",
            "Accommodation in Lhasa and Shigatse ranges from 3-star to 5-star hotels; remote area guesthouses are basic (no central heating).",
            "The tour pace needs to accommodate altitude acclimatisation — day 1 in Lhasa is rest only.",
        ],
        items_seasonality=[
            "Best travel months: April to October. May, June, September, and October offer the most stable weather.",
            "July–August: warm but peak tourist season; Potala Palace tickets may sell out early.",
            "November–March: winter season — very cold but fewer tourists; EBC and some mountain passes may be closed.",
            "Monsoon effect: July–August brings rain to central and eastern Tibet; morning sightseeing is more reliable.",
        ],
        items_operations=[
            "Tibet Travel Permit (TTP): required for all foreign travellers. Agency processes through PSB — takes 10–14 working days.",
            "Alien Travel Permit (ATP): required for areas beyond Lhasa (Shigatse, EBC, Mt Kailash).",
            "Military permit: additional permit needed for certain border areas near Arunachal Pradesh and Nepal.",
            "Health preparation: all travellers should have medical insurance covering high altitude (above 4000 m) and potential AMS issues.",
        ],
        items_sales=[
            "The biggest sales friction point is the permit timeline — tell clients to submit passport scans at least 3 weeks before departure.",
            "Solo travellers cannot join a tour independently in Tibet; they must be part of an organised group.",
            "Clarify whether the client needs an EBC extension — this adds 3 days, requires a 4WD vehicle, and involves rough road conditions.",
            "Tibet is not suitable for first-time China travellers or those with health concerns related to high altitude — recommend Yunnan or western Sichuan instead.",
        ],
    ),
    "Yunnan Destination Overview": _build_destination_blocks(
        items_overview=[
            "Yunnan province in southwest China is one of the most ethnically and geographically diverse regions in the country.",
            "Major destinations include Kunming (Spring City), Dali (Bai culture), Lijiang (Naxi heritage), and Shangri-La (Tibetan culture).",
            "The province features everything from subtropical rice terraces (Yuanyang) and tropical rainforests (Xishuangbanna) to snow-capped mountains (Meili Snow Mountain).",
            "Yunnan is the most accessible high-altitude destination for family travellers and first-time China visitors.",
        ],
        items_best_for=[
            "Family travellers and multi-generational groups wanting a gentle introduction to China's diverse landscapes and cultures.",
            "Cultural travellers interested in ethnic minority groups: Bai, Naxi, Yi, Tibetan, and Dai.",
            "Soft adventure travellers: cycling around Erhai Lake, hiking Tiger Leaping Gorge, and exploring Pudacuo Park.",
            "Agency clients seeking a reliable, all-season product with strong tourism infrastructure.",
        ],
        items_style=[
            "Yunnan offers the most flexible travel style in our portfolio — groups can choose private guided tours or self-guided with pre-booked hotels and transport.",
            "Domestic flights connect all major cities; high-speed trains cover Kunming–Dali (2 h) and Kunming–Lijiang (3 h).",
            "Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.",
            "The province is very walkable at lower altitudes (Kunming 1900 m, Dali 2000 m, Lijiang 2400 m) — no mandatory rest days needed.",
        ],
        items_seasonality=[
            "Yunnan is a year-round destination. Spring (March–May) is peak for flowers and mild weather.",
            "Summer (June–August): rainy season in central/southern Yunnan; Shangri-La is pleasant with daytime temps around 20°C.",
            "Autumn (September–November): clear skies, golden rice terraces, and comfortable temperatures everywhere.",
            "Winter (December–February): mild in Kunming and Dali (15–20°C daytime); cold in Shangri-La (-5 to 10°C).",
        ],
        items_operations=[
            "No special permits required for Yunnan (except for foreign journalists — standard tourist visa suffices).",
            "Altitude is manageable: Shangri-La at 3300 m is the highest point; most travellers acclimatise naturally.",
            "Road infrastructure is excellent: expressways connect Kunming–Dali–Lijiang; mountain roads to Deqin and Yuanyang are paved.",
            "Medical facilities are good in cities; remote areas have basic clinics. Recommend comprehensive travel insurance.",
        ],
        items_sales=[
            "For family groups, suggest the 'Dali + Lijiang' combo as the core with optional Shangri-La extension if the family wants a Tibetan experience.",
            "Ask whether the group prefers boutique guesthouses (more character) or standard hotels (more predictable comfort).",
            "For agency clients, emphasise that Yunnan works well as a standalone destination or paired with a Yangtse River cruise or Xi'an.",
            "Winter family travellers: recommend Kunming + Dali only; Shangri-La may be too cold for children and elderly.",
        ],
    ),
    "Private Tour Pricing Rules": [
        _heading_2("Pricing Variables"),
        _bullet("Private tour pricing is calculated based on: group size, hotel level, vehicle type, guide service, and season."),
        _bullet("Each quotation is built from a base per-person cost adjusted by service tier and seasonal multiplier."),
        _bullet("Domestic flights (if needed, e.g. Chengdu–Daocheng, Kunming–Shangri-La) are quoted separately and subject to airline availability."),
        _bullet("All quotations should be provided in USD or EUR for agency clients; RMB pricing for direct B2C Chinese clients."),
        _heading_2("Group Size"),
        _bullet("1–2 pax: highest per-person cost. Uses private car (5-seat sedan or SUV)."),
        _bullet("3–6 pax: sweet spot for cost efficiency. Uses 7-seat MPV or minibus. Per-person cost drops significantly."),
        _bullet("7–12 pax: uses 17–22 seat minibus. Per-person cost continues to decrease; benefits from shared guide and driver costs."),
        _bullet("13–25+ pax: uses full-size coach. Requires 2 guides for groups above 20. Hotel block booking discounts available."),
        _heading_2("Hotel Level"),
        _bullet("Standard (3-star / Comfort): basic clean accommodation with private bathroom. Suitable for budget-conscious groups."),
        _bullet("Premium (4-star / Superior): better location, breakfast buffet included, English-speaking staff at reception."),
        _bullet("Luxury (5-star / Deluxe): highest tier available in each city. Not available in remote areas (Tagong, Daocheng basic)."),
        _bullet("Hotel level consistency matters: if one night is luxury and the next is basic, clients may complain about inconsistency."),
        _heading_2("Vehicle Type"),
        _bullet("Sedan / SUV (1–3 pax): flexible, easy parking, comfortable for long-distance driving. Best for small groups."),
        _bullet("MPV / Minibus (4–7 pax): recommended for family groups. Extra legroom for long days on the road."),
        _bullet("Midibus (8–14 pax): cost-effective for medium groups. Luggage space limited — advise soft luggage only."),
        _bullet("Coach (15+ pax): requires advance booking. Not suitable for mountain passes above 4000 m on western Sichuan routes."),
        _heading_2("Guide Requirement"),
        _bullet("English-speaking guide included in all private tour packages. Chinese-speaking guide available at lower cost."),
        _bullet("Bilingual guide (English + Chinese) adds 20–30% to guide fee. Useful for agency groups with mixed-language participants."),
        _bullet("Specialist guides (photography, birding, monastery history): available on request at premium rates. Book 2 weeks in advance."),
        _bullet("Tibet tours require a licensed Tibet guide registered with the Tibet Tourism Bureau. This cost is non-negotiable."),
        _heading_2("Seasonal Factors"),
        _bullet("Peak season (July–October): hotel rates 30–50% higher. Vehicle and guide availability limited — book 4+ weeks ahead."),
        _bullet("Shoulder season (April–June, November): moderate pricing with good availability. Recommended for price-sensitive groups."),
        _bullet("Low season (December–March): lowest rates, but many mountain routes and attractions may be closed due to snow."),
        _bullet("Chinese National Holidays (Golden Week: October 1–7, Spring Festival, May 1–3): avoid scheduling during these periods — prices double and crowds are extreme."),
        _heading_2("Quotation Notes"),
        _bullet("All quotations should clearly state: included items (transport, guide, accommodation, listed meals, listed entrance fees) and excluded items (flights, visa fees, tips, personal expenses, travel insurance)."),
        _bullet("Agency commission: standard B2B commission is 10–15% of the land package. Negotiable for high-volume partners."),
        _bullet("Deposit: 30% deposit required to confirm booking. Balance due 14 days before arrival."),
        _bullet("Cancellation policy: free cancellation 30+ days before departure; 50% charge 15–30 days; no refund within 14 days."),
    ],
    "Travel Permit and Payment FAQ": [
        _heading_2("Common Questions"),
        _bullet("Q: Do I need a permit to travel to Tibet? A: Yes, all foreign travellers need a Tibet Travel Permit (TTP) processed through a licensed travel agency."),
        _bullet("Q: How long does the Tibet permit take? A: The permit processing takes 10–14 working days. We need a clear passport scan at least 3 weeks before the planned entry date."),
        _bullet("Q: What payment methods do you accept? A: We accept bank wire transfer, PayPal (4% surcharge), and Alipay. Credit card payments processed through Stripe for most currencies."),
        _bullet("Q: What is the deposit and cancellation policy? A: 30% deposit confirms the booking. Balance due 14 days before arrival. Free cancellation 30+ days before departure."),
        _heading_2("Short Answers"),
        _bullet("Tibet Travel Permit (TTP): required for all foreign nationals. Your guide will carry the permit and present it at checkpoints."),
        _bullet("Alien Travel Permit (ATP): required if the itinerary goes beyond Lhasa (Shigatse, EBC, Mt Kailash). We process this together with TTP."),
        _bullet("Visa: foreign travellers need a Chinese L-visa (tourist visa). Tibet permits do not replace a Chinese visa — both are required."),
        _bullet("Payment schedule: deposit → confirms booking. Balance → charged 14 days before departure. Last-minute bookings (<14 days): full payment required upfront."),
        _heading_2("Sales Notes"),
        _bullet("Always remind clients about the permit timeline at the first email. Many Tibet trip cancellations happen because clients didn't know about the 3-week lead time."),
        _bullet("For western Sichuan, Yunnan, and other non-Tibet destinations: no special permits needed — standard tourist visa is sufficient."),
        _bullet("Group booking payments: for agency groups, we can issue a single invoice for the entire group. We do not split invoices per traveller."),
        _bullet("If a client asks about last-minute Tibet travel (<14 days), be honest about feasibility — express permit processing is sometimes possible but not guaranteed and costs extra."),
        _heading_2("Risk Notes"),
        _bullet("Tibet permit rejection: rare but possible if the client has a restricted nationality or incomplete documentation. Refund policy for permit rejection: full refund of land package."),
        _bullet("Payment fraud: for first-time agency clients, verify the company registration and consider requiring full payment before the tour starts."),
        _bullet("Currency fluctuation: for quotations held longer than 30 days, we reserve the right to adjust pricing if exchange rates move more than 5%."),
        _bullet("Force majeure: if the Chinese government suspends Tibet tourism (as happened during COVID), we offer full credit for future travel but no cash refund for permits and non-recoverable costs."),
    ],
}


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

def _notion_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _list_child_blocks(client: httpx.Client, headers: dict[str, str], block_id: str) -> list[dict[str, Any]]:
    """Return child blocks of *block_id*. Handles pagination up to 200 items."""
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        response = client.get(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            headers=headers,
            params=params,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to list children of {block_id}: "
                f"{response.status_code} {response.text}"
            )
        data = response.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _get_child_page_map(
    client: httpx.Client,
    headers: dict[str, str],
    parent_id: str,
) -> dict[str, str]:
    """Return {page_title: page_id} for all immediate child_page blocks under parent_id."""
    blocks = _list_child_blocks(client, headers, parent_id)
    mapping: dict[str, str] = {}
    for block in blocks:
        if block.get("type") == "child_page":
            child_info = block.get("child_page", {})
            title = child_info.get("title", "")
            if title:
                mapping[title] = block["id"]
    return mapping


def _create_page(
    client: httpx.Client,
    headers: dict[str, str],
    parent_id: str,
    title: str,
    children: list[dict[str, Any]] | None = None,
) -> str:
    """Create a child page under *parent_id* and return its page_id."""
    body: dict[str, Any] = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}],
            }
        },
    }
    if children:
        body["children"] = children

    response = client.post(
        f"{NOTION_API_BASE}/pages",
        headers=headers,
        json=body,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to create page '{title}': "
            f"{response.status_code} {response.text}"
        )
    return response.json()["id"]


def _build_source_path(segments: list[str]) -> str:
    """Build the manifest-style source path from page title segments."""
    return "/".join(segments)


# ---------------------------------------------------------------------------
# Tree walker
# ---------------------------------------------------------------------------

def _ensure_page(
    client: httpx.Client,
    headers: dict[str, str],
    parent_id: str,
    page_title: str,
    path_segments: list[str],
    id_map: dict[str, str],
    content: list[dict[str, Any]] | None,
    dry_run: bool,
) -> str:
    """Create or reuse a single page and return its page_id."""
    if dry_run:
        print(f"  [dry-run] would create/reuse: {page_title}")
        return f"dry-run-{page_title}"

    # Build source path for manifest key
    source_path = _build_source_path(path_segments)

    # Check existing children
    child_map = _get_child_page_map(client, headers, parent_id)
    if page_title in child_map:
        existing_id = child_map[page_title]
        id_map[source_path] = existing_id
        print(f"  reused existing page: {page_title}")
        return existing_id

    # Create the page
    page_id = _create_page(client, headers, parent_id, page_title, children=content)
    id_map[source_path] = page_id
    print(f"  created: {page_title}")
    return page_id


def _walk_tree(
    client: httpx.Client | None,
    headers: dict[str, str] | None,
    parent_id: str,
    subtree: dict[str, Any],
    path_segments: list[str],
    id_map: dict[str, str],
    dry_run: bool,
) -> None:
    """Recursively walk the page tree, creating or reusing pages."""
    for node_name, node_value in subtree.items():
        segments = path_segments + [node_name]

        if isinstance(node_value, dict):
            # Folder page — create it, then recurse into children
            folder_id = _ensure_page(
                client=client,
                headers=headers,
                parent_id=parent_id,
                page_title=node_name,
                path_segments=segments,
                id_map=id_map,
                content=None,  # folders get no content blocks
                dry_run=dry_run,
            )
            _walk_tree(client, headers, folder_id, node_value, segments, id_map, dry_run)
        elif isinstance(node_value, str):
            # Leaf content page — get content blocks from PAGE_CONTENT
            content_blocks = PAGE_CONTENT.get(node_name)
            _ensure_page(
                client=client,
                headers=headers,
                parent_id=parent_id,
                page_title=node_name,
                path_segments=segments,
                id_map=id_map,
                content=content_blocks,
                dry_run=dry_run,
            )
        else:
            print(f"  [skip] invalid node value for '{node_name}': {node_value}")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _validate_env() -> tuple[str, str | None, str | None]:
    """Read and validate environment variables. Returns (api_key, root_id, parent_id)."""
    api_key = os.getenv("NOTION_API_KEY")
    if not api_key:
        print("ERROR: Missing NOTION_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    root_id = os.getenv("NOTION_KNOWLEDGE_ROOT_PAGE_ID")
    parent_id = os.getenv("NOTION_PARENT_PAGE_ID")

    if not root_id and not parent_id:
        print(
            "ERROR: Missing page id. Please set NOTION_KNOWLEDGE_ROOT_PAGE_ID "
            "or NOTION_PARENT_PAGE_ID.",
            file=sys.stderr,
        )
        sys.exit(1)

    return api_key, root_id, parent_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Create or reuse the Notion knowledge base page tree."""
    # Validate environment
    api_key, root_id, parent_id = _validate_env()

    # Dry-run check: if NOTION_API_KEY starts with "test_" or we are in CI,
    # we can run a dry-run mode without making real API calls.
    dry_run = api_key.startswith("test_") or os.getenv("CI", "").lower() in ("1", "true")

    if dry_run:
        print("Dry-run mode: no API calls will be made.")
        print()

    id_map: dict[str, str] = {}

    if root_id:
        # Mode 1: root page already exists
        root_page_id = root_id
        print(f"Using existing Knowledge Root Page: {root_id}")
        print()

        # Walk the subtree (the value under the root key)
        root_name = list(PAGE_TREE.keys())[0]
        id_map[root_name] = root_id
        tree_value = PAGE_TREE[root_name]

        if dry_run:
            _walk_tree(None, None, root_id, tree_value, [root_name], id_map, dry_run=True)
        else:
            with httpx.Client(timeout=30.0) as client:
                headers = _notion_headers(api_key)
                _walk_tree(client, headers, root_id, tree_value, [root_name], id_map, dry_run=False)
    else:
        # Mode 2: create root page under parent
        assert parent_id is not None
        root_name = list(PAGE_TREE.keys())[0]

        if dry_run:
            id_map[root_name] = "dry-run-root"
            print(f"  [dry-run] would create root: {root_name} under parent {parent_id}")
            print()
            tree_value = PAGE_TREE[root_name]
            _walk_tree(None, None, "dry-run-root", tree_value, [root_name], id_map, dry_run=True)
        else:
            with httpx.Client(timeout=30.0) as client:
                headers = _notion_headers(api_key)

                # Check if root already exists under parent
                child_map = _get_child_page_map(client, headers, parent_id)
                if root_name in child_map:
                    root_page_id = child_map[root_name]
                    print(f"Reused existing root page: {root_name}")
                else:
                    root_page_id = _create_page(client, headers, parent_id, root_name)
                    print(f"Created root page: {root_name}")

                id_map[root_name] = root_page_id
                print()
                tree_value = PAGE_TREE[root_name]
                _walk_tree(client, headers, root_page_id, tree_value, [root_name], id_map, dry_run=False)

    # Print summary
    print()
    print("Created / Reused pages:")
    for path, pid in id_map.items():
        print(f"  - {path}: {pid}")

    # Save ID mapping
    output_path = OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(id_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved page ID mapping to: {output_path}")


if __name__ == "__main__":
    main()
