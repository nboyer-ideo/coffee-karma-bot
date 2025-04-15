from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
from flask import jsonify
import schedule
import time
import random
import requests
import os
import datetime
import json
import copy
import re
import csv
from sheet import (
    add_karma,
    get_karma,
    get_leaderboard,
    ensure_user,
    deduct_karma,
    get_runner_capabilities,
    log_order_to_sheet,
    fetch_order_data,
    mark_code_redeemed,
)

def format_order_message(order_data):
    print(f"🚨 format_order_message invoked — order_id: {order_data.get('order_id')}")
    print(f"🧩 Raw input keys: {list(order_data.keys())}")
    print(f"🧩 Raw order_id type: {type(order_data.get('order_id'))}, value: {order_data.get('order_id')}")
    print(f"🧩 Fallback check? missing: {not order_data.get('order_id')}, space: {' ' in str(order_data.get('order_id', ''))}, colon: {':' in str(order_data.get('order_id', ''))}")
    current_id = str(order_data.get("order_id", "")).strip()
    if " " in str(current_id) or ":" in str(current_id):
        raise RuntimeError(f"Invalid order_id format detected during countdown: {current_id}")
    if not current_id or current_id.strip() == "" or ":" in current_id or " " in current_id:
        print("⚠️ [format_order_message] Missing or invalid order_id — attempting fallback from known TS")
        possible_ts = order_data.get("ts") or order_data.get("timestamp")
        fallback_id = order_extras.get(possible_ts, {}).get("order_id") if possible_ts else None
        # ⛑️ Only assign fallback if it's clean
        if fallback_id and ":" not in fallback_id and " " not in fallback_id:
            order_data["order_id"] = fallback_id
        elif str(possible_ts).replace('.', '', 1).isdigit():
            # Use timestamp as string if it's numeric-ish
            order_data["order_id"] = str(possible_ts)
        else:
            order_data["order_id"] = f"fallback-{int(datetime.datetime.now().timestamp())}"
        print(f"✅ [format_order_message] order_id fallback assigned: {order_data['order_id']}")
    else:
        order_data["order_id"] = current_id.strip()
        print(f"🧷 [format_order_message] Using provided order_id: {current_id.strip()}")
    print(f"🧪 ENTERING format_order_message with order_id={order_data.get('order_id', '[MISSING]')}")
    print(f"📨 format_order_message called with order_data: {order_data}")
    print(f"🧪 format_order_message FROM: {order_data.get('requester_real_name')} TO: {order_data.get('recipient_real_name')}")
    border_top = "+------------------------------------------------+"
    border_mid = "+------------------------------------------------+"
    border_bot = "+------------------------------------------------+"
    lines = [
        border_top,
        *wrap_line("", "☠ DRINK ORDER ☠", width=50),
    ]
    lines.append(border_mid)
    lines.append(f'| DROP ID:      {order_data["order_id"]:<32} |')
    requester_display = order_data.get("requester_real_name", "")
    recipient_display = order_data.get("recipient_real_name", "")
    lines.append(f'| FROM:         {requester_display.upper():<32} |')
    lines.append(f'| TO:           {recipient_display.upper():<32} |')
    lines.append(f'| DRINK:        {order_data["drink"].upper():<32} |')
    lines.append(f'| LOCATION:     {order_data["location"].upper():<32} |')
    lines.append(f'| NOTES:        {(order_data["notes"] or "NONE").upper():<32} |')
    lines.append(border_mid)
    lines.append(f'| REWARD:       {order_data["karma_cost"]} KARMA{" " * (32 - len(str(order_data["karma_cost"]) + " KARMA"))} |')
    if order_data.get("delivered_by"):
        lines.append(f'| STATUS:       COMPLETED {" " * 22} |')
        lines.append(f'|               DELIVERED BY {order_data["delivered_by"].upper():<19} |')
        lines.append("| ---------------------------------------------- |")
        earned = order_data.get('karma_cost', 1) * int(order_data.get('bonus_multiplier', 1))
        total = order_data.get('runner_karma', 0)
        karma_line = f"+{earned} KARMA EARNED — TOTAL: {total} KARMA"
        total_width = 46
        karma_line_centered = karma_line.center(total_width)
        lines.append(f"| {karma_line_centered} |")
        lines.append("| ---------------------------------------------- |")
    elif order_data.get("claimed_by"):
        claimed_name = order_data.get("runner_real_name") or order_data.get("claimed_by", "")
        lines.append(f'| STATUS:       CLAIMED BY {claimed_name.upper():<21} |')
        lines.append(f'|               WAITING TO BE DELIVERED          |')
    else:
        total_blocks = 20
        remaining = int(order_data.get("remaining_minutes", 10))
        filled_blocks = max(0, min(total_blocks, remaining * 2))  # 2 blocks per minute
        empty_blocks = total_blocks - filled_blocks
        progress_bar = "[" + ("█" * filled_blocks) + ("░" * empty_blocks) + "]"
        status_line = f'{order_data.get("remaining_minutes", 10)} MINUTES TO CLAIM'
        lines.append(f'| STATUS:       {status_line:<32} |')
        lines.append(f'|               {progress_bar:<32} |')
    
    # Only add call-to-action if order is not delivered
    if not order_data.get("delivered_by"):
        lines.append("| ---------------------------------------------- |")
        if order_data.get("claimed_by"):
            lines.append("|     ↓ CLICK BELOW ONCE ORDER IS DROPPED ↓      |")
        else:
            lines.append("|      ↓ CLICK BELOW TO CLAIM THIS ORDER ↓       |")
        lines.append("| ---------------------------------------------- |")
    lines.append(border_bot)
    lines += [
        "| /ORDER        PLACE AN ORDER                   |",
        "| /DELIVER      DELIVER ORDERS                   |",
        "| /KARMA        CHECK YOUR KARMA                 |",
        "| /LEADERBOARD  TOP KARMA EARNERS                |",
        border_bot
    ]
 
    # Define button elements based on order claim status
    elements = []
    if order_data.get("delivered_by"):
        pass  # Do not add any buttons
    elif order_data.get("claimed_by"):
        elements.append({
            "type": "button",
            "action_id": "mark_delivered",
            "text": {
                "type": "plain_text",
                "text": "MARK AS DELIVERED",
                "emoji": True
            },
            "style": "primary",
            "value": order_data.get("order_id") or "unknown"
        })
    else:
        elements.append({
            "type": "button",
            "action_id": "claim_order",
            "text": {
                "type": "plain_text",
                "text": "CLAIM ORDER",
                "emoji": True
            },
            "value": order_data.get("order_id") or "unknown"
        })
        elements.append({
            "type": "button",
            "action_id": "cancel_order",
            "text": {
                "type": "plain_text",
                "text": "CANCEL",
                "emoji": True
            },
            "style": "danger",
            "value": f"{order_data['order_id']}|{order_data.get('requester_id')}"
        })

    # Insert corrected mini-map logic before constructing blocks
    if order_data.get("location"):
        mini_map = build_mini_map(order_data["location"])
 
        # Add header for map panel
        map_title = "+--------------------------+"
        padded_map = [f"{line:<26}"[:26] for line in mini_map]
        map_lines = [map_title, "|         LION MAP         |", map_title]
        map_lines += [f"|{line}|" for line in padded_map]
        map_lines.append("+--------------------------+")
        map_legend = [
            "| ✗ = DRINK LOCATION       |",
            "| ☕ = CAFÉ                 |",
            "| ▯ = ELEVATOR             |",
            "| ≋ = BATHROOM             |",
            "+--------------------------+"
        ]
        map_lines.extend(map_legend)
 
        # Merge lines side-by-side
        merged_lines = []
        max_lines = max(len(lines), len(map_lines))
        for i in range(max_lines):
            left = lines[i] if i < len(lines) else " " * 50
            right = map_lines[i] if i < len(map_lines) else ""
            merged_lines.append(f"{left}  {right}")
        lines = merged_lines

    blocks = [
        {
            "type": "section",
            "block_id": "order_text_block",
            "text": {
                "type": "mrkdwn",
                "text": "```" + "\n".join(lines) + "```"
            }
        }
    ]

    if elements:
        blocks.append({
            "type": "actions",
            "block_id": "buttons_block",
            "elements": elements
        })

    return blocks

last_selected_location = {}

def resolve_real_name(user_id, client):
    try:
        user_info = client.users_info(user=user_id)
        return user_info["user"]["real_name"]
    except Exception as e:
        print(f"⚠️ Failed to resolve real name for {user_id}:", e)
        return f"<@{user_id}>"

def send_koffee_welcome(client, user_id):
    welcome_message = (
        "¤ A new vessel joins the order.\n"
        "Your starting balance: 3 Karma\n"
        "Your rank: The Initiate.\n\n"
        "To participate in the rituals:\n\n"
        "1. Type \"/\" in the #koffee-karma-sf channel.\n"
        "2. Select one of the commands below.\n"
        "3. Hit enter to activate the command.\n\n"
        "`/order` — Request a drink\n"
        "`/deliver` — Available to deliver orders\n"
        "`/karma` — Check your current Koffee Karma\n"
        "`/redeem` — Redeem codes for bonus karma\n"
        "`/leaderboard` — Show the top Koffee Karma earners\n\n"
        "The café watches."
    )
    client.chat_postMessage(channel=user_id, text=welcome_message)

    public_welcome_templates = [
        "§ <@{user}> joined the rebellion. Brew responsibly.\nUse `/order` to request. `/deliver` to offer.",
        "¤ New operative detected: <@{user}>.\nRun a drop with `/order` or offer to deliver with `/deliver`.",
        "‡ Transmission inbound — <@{user}> enters the grid.\nKick things off: `/order` or `/deliver` to volunteer.",
        ":: Alert :: <@{user}> has entered the cycle.\nInitiate contact via `/order` or offer with `/deliver`.",
        "§ The order grows — <@{user}> now among us.\nUse `/order` to summon. `/deliver` to volunteer.",
        "¤ Initiate registered: <@{user}>.\nStart your descent with `/order` or offer a run with `/deliver`.",
        "‡ <@{user}> breaches the brewline.\nFirst move: `/order` to place. `/deliver` to serve.",
        ":: Access granted: <@{user}> onboarded to the grind.\nReady up — `/order` to request, `/deliver` to offer.",
        "§ System notification: <@{user}> is now in play.\nDispatch via `/order`. Volunteer via `/deliver`.",
        "¤ <@{user}> joins the collective.\nStir the system with `/order` or offer with `/deliver`."
    ]
    public_message = random.choice(public_welcome_templates).replace("{user}", user_id)
    client.chat_postMessage(channel=os.environ.get("KOFFEE_KARMA_CHANNEL"), text=public_message)

def box_label(label, value, width=40):
    """
    Return a single line like: | LABEL:       VALUE               |
    Pads everything to ensure right border lines up.
    """
    label = label.rstrip(":").upper()
    label_prefix = f"| {label:<13}"  # 13-character label field
    value_field = f"{value}".upper()
    space = width - len(label_prefix) - 2  # 2 for trailing ' |'
    return f"{label_prefix} {value_field:<{space}} |"

def format_full_map_with_legend(mini_map_lines):
    legend_lines = [
        "+--------------------------+",
        "|         LEGEND           |",
        "+--------------------------+",
        "| ✗ = DRINK LOCATION       |",
        "| ☕ = CAFÉ                 |",
        "| ▯ = ELEVATOR             |",
        "| ≋ = BATHROOM             |",
        "+--------------------------+",
        "|                          |",
        "| USE THE DROPDOWN ABOVE   |",
        "| TO PICK YOUR DELIVERY    |",
        "| SPOT IN THE STUDIO. THE  |",
        "| ✗ IN THE MAP SHOWS WHERE |",
        "| YOUR DRINK WILL ARRIVE.  |",
        "|                          |",
        "|                          |",
        "+--------------------------+"
    ]

    padded_map = [f"{line:<26}"[:26] for line in mini_map_lines]
    map_header = [
        "+--------------------------+",
        "|         LION MAP         |",
        "+--------------------------+"
    ]
    map_footer = ["+--------------------------+"]
    full_map = map_header + [f"|{line}|" for line in padded_map] + map_footer

    merged_lines = []
    max_len = max(len(full_map), len(legend_lines))
    for i in range(max_len):
        left = full_map[i] if i < len(full_map) else " " * 28
        right = legend_lines[i] if i < len(legend_lines) else ""
        merged_lines.append(f"{left}  {right}")
    return "\n".join(merged_lines)

# Global safety initialization
if 'runner_offer_metadata' not in globals():
    runner_offer_metadata = {}

def safe_chat_update(client, channel, ts, text, blocks=None):
    try:
        client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
    except Exception as e:
        print("⚠️ safe_chat_update failed:", e)

cached_coordinates = None
cached_map_template = None

def strip_formatting(s):
    import re
    s = re.sub(r"<@[^>]+>", "", s)  # remove Slack user mentions
    s = re.sub(r"[^\x00-\x7F]", "", s)  # remove non-ASCII characters (e.g., emojis)
    return s

order_extras = {}
countdown_timers = {}  # order_ts -> remaining minutes
countdown_timers = {}
runner_offer_claims = {}  # key: runner_id, value: user_id of matched requester (or None if still open)
orders = {}
 
def wrap_line(label, value, width=50):
    if not label and value:
        centered = value.upper().center(width - 4)
        return [f"| {centered} |"]

    label = label.rstrip(":").upper()
    value_str = value.upper()
    max_content = width - 4
    label_with_colon = f"{label}:"
    first_line_indent = f"| {label_with_colon:<13} "
    wrapped_lines = []

    current_line = ""
    words = value_str.split()
    for word in words:
        if len(current_line + (" " if current_line else "") + word) <= max_content - len(first_line_indent):
            current_line += (" " if current_line else "") + word
        else:
            if not wrapped_lines:
                wrapped_lines.append(f"{first_line_indent}{current_line:<{max_content - len(first_line_indent)}} |")
            else:
                wrapped_lines.append(f"| {'':<13}{current_line:<{max_content - 13}} |")
            current_line = word

    if current_line:
        if not wrapped_lines:
            wrapped_lines.append(f"{first_line_indent}{current_line:<{max_content - len(first_line_indent)}} |")
        else:
            wrapped_lines.append(f"| {'':<13}{current_line:<{max_content - 13}} |")

    return wrapped_lines

def box_line(text="", label=None, value=None, width=42, align="left", auto_colon=True, label_field=13):
    """
    Unified function for formatting boxed lines at exactly 42 characters.
    If a label and value are provided, it formats them with multi-line wrapping.
    If auto_colon is True, a colon is appended to the label if it doesn't already end with one.
    """
    lines = []
    # The interior content area is width - 4 (for "| " and " |")
    content_width = width - 4

    # Case 1: text-only mode.
    if label is None and value is None:
        text = text.upper()
        if align == "center":
            content = text.center(content_width)
        elif align == "right":
            content = text.rjust(content_width)
        else:
            content = text.ljust(content_width)
        return [f"| {content} |"]
    
    # Case 2: Label + value formatting.
    label = label.upper().rstrip()
    if auto_colon and not label.endswith(":"):
        label += ":"
    
    value = value.upper()
    words = value.split()
    # The first line gets the label, padded to label_field, and then the value.
    first_line_prefix = f"| {label:<{label_field}}"
    available_for_value = content_width - label_field  # Remaining space for the value on the first line
    indent = " " * label_field  # For subsequent lines.
    
    wrapped_lines = []
    current_line = ""
    for word in words:
        proposed = (current_line + " " + word).strip() if current_line else word
        if len(proposed) <= available_for_value:
            current_line = proposed
        else:
            wrapped_lines.append(current_line)
            current_line = word
    if current_line:
        wrapped_lines.append(current_line)
    
    for i, val_line in enumerate(wrapped_lines):
        if i == 0:
            lines.append(f"{first_line_prefix}{val_line:<{available_for_value}} |")
        else:
            lines.append(f"| {indent}{val_line:<{available_for_value}} |")
    return lines

def wrap_line_runner(label, value, width=40):
    """
    Wrap a label and value to fit in a fixed-width terminal-style box (40 char wide).
    Preserves left-alignment of values under the label and ensures consistent line lengths.
    """
    lines = []
    label = label.rstrip(":").upper()
    value = value.upper()
 
    # Space for content between borders: width - 2 (for '|') - 1 space after '|' = width - 3
    total_content_width = width - 3
    label_prefix = f"{label:<11}"  # Label gets 11 characters
    indent = " " * 13  # 2 spaces for '| ' plus 11-character label
    line_prefix = "| "
 
    words = value.split()
    current_line = ""
 
    for word in words:
        if len(current_line + (" " if current_line else "") + word) <= total_content_width - len(label_prefix):
            current_line += (" " if current_line else "") + word
        else:
            if not lines:
                line = f"{line_prefix}{label_prefix}{current_line:<{total_content_width - len(label_prefix)}} |"
            else:
                line = f"{line_prefix}{indent}{current_line:<{total_content_width - len(indent)}} |"
            lines.append(line)
            current_line = word
 
    # Add final line
    if current_line:
        if not lines:
            line = f"{line_prefix}{label_prefix}{current_line:<{total_content_width - len(label_prefix)}} |"
        else:
            line = f"{line_prefix}{indent}{current_line:<{total_content_width - len(indent)}} |"
        lines.append(line)
 
    return lines

def build_mini_map(location_name, coord_file="Room_Coordinates_Mapping_Table.json", map_file="lion_map_template.txt"):
    import json
    print(f"🔍 build_mini_map called with location_name={location_name}")
    print(f"📍 [DEBUG] build_mini_map received location_name: '{location_name}'")
    global cached_map_template
    if cached_map_template is None:
        try:
            with open(map_file, "r") as mf:
                cached_map_template = mf.read()
        except Exception as e:
            print("⚠️ Failed to load map template:", e)
            return []
    map_template = cached_map_template

    global cached_coordinates
    if cached_coordinates is None:
        try:
            with open(coord_file, "r") as f:
                cached_coordinates = json.load(f)
        except Exception as e:
            print("⚠️ Failed to load coordinates:", e)
            cached_coordinates = {}
    coordinates = cached_coordinates
    print(f"📌 Checking if location exists in coordinates: {location_name in coordinates}")
    if location_name not in coordinates:
        print(f"❌ Location '{location_name}' not found in coordinate mapping keys: {list(coordinates.keys())}")
    print(f"📌 Loaded coordinates for {len(coordinates)} locations")

    map_lines = map_template.splitlines()
    if location_name in coordinates:
        x = int(coordinates[location_name]["x"])
        y = int(coordinates[location_name]["y"])
        print(f"🗺️ [DEBUG] Coordinates for {location_name} → X: {x}, Y: {y}")
        print(f"🗺️ Marking location on map at ({x}, {y}) for {location_name}")
        if 0 <= y < len(map_lines):
            line = list(map_lines[y])
            if 0 <= x < len(line):
                print(f"✍️ [DEBUG] Placing ✗ on map at line[{y}][{x}]")
                print(f"✍️ Placing '✗' on map at ({x}, {y})")
                line[x] = "✗"
                map_lines[y] = "".join(line)
                print(f"🆗 map_lines[{y}] updated with '✗'")
    return map_lines

# Load secrets from .env
from dotenv import load_dotenv
load_dotenv()

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

import re
import threading

def safe_chat_update(client, channel, ts, text, blocks):
    from slack_sdk.errors import SlackApiError
    try:
        response = client.chat_update(
            channel=channel,
            ts=ts,
            text=text,
            blocks=blocks
        )
        print("✅ Slack message successfully updated via safe_chat_update.")
        return response
    except SlackApiError as e:
        print("🚨 Slack API error during chat_update:", e.response['error'])
    except Exception as e:
        print("🚨 General error in safe_chat_update:", e)

def update_countdown(client, remaining, order_ts, order_channel, user_id, gifted_id, drink, location, notes, karma_cost):
    order_ts = str(order_ts)
    import sys
    print("🔥 ENTERED update_countdown()")
    sys.stdout.flush()
    print(f"🔁 Countdown tick for {order_ts} — remaining: {remaining}")
    try:
        print(f"👤 User: {user_id}, Gifted: {gifted_id}")
        print(f"🥤 Drink: {drink}, 📍 Location: {location}, 📝 Notes: {notes}, 💰 Karma Cost: {karma_cost}")

        extras = order_extras.get(order_ts)
        if extras is None:
            order_extras[order_ts] = {}
            extras = order_extras[order_ts]
        print(f"🧪 Debug: order_extras for {order_ts} = {extras}")
        print(f"🧭 Entering update_countdown for order_ts: {order_ts} with remaining: {remaining}")
        print(f"🧭 order_channel: {order_channel}, user_id: {user_id}, gifted_id: {gifted_id}")
        print(f"🧭 Checking active: {extras.get('active', False)}, status: {extras.get('status')}")
        print(f"📦 order_extras for {order_ts}: {extras}")
        sys.stdout.flush()
        
        # Added check: stop countdown if order is already claimed or delivered
        if extras and extras.get("status") in ["claimed", "delivered", "canceled"]:
            print("Countdown halted due to status:", extras.get("status"))
            return
        
        if not extras or not extras.get("active", True):
            print(f"⛔ Countdown aborted — order_extras missing or marked inactive for {order_ts}")
            return
        print(f"✅ Countdown proceeding for {order_ts}, remaining: {remaining}")

        current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
        order_data = {
            "order_id": "",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "requester_id": user_id,
            "requester_real_name": extras.get("requester_real_name") or "",
            "runner_id": "",
            "runner_real_name": "",
            "recipient_id": gifted_id if gifted_id else user_id,
            "recipient_real_name": extras.get("recipient_real_name") or "",
            "drink": drink,
            "location": location,
            "notes": notes,
            "karma_cost": karma_cost,
            "status": extras.get("status", "ordered"),
            "bonus_multiplier": "",
            "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time_claimed": "",
            "time_delivered": "",
            "claimed_by": extras.get("claimed_by", ""),
            "runner_real_name": extras.get("runner_real_name", ""),
            "delivered_by": extras.get("delivered_by", "")
        }
        if not order_data.get("order_id") or ":" in str(order_data["order_id"]) or " " in str(order_data["order_id"]):
            fallback_candidate = order_extras.get(order_ts, {}).get("order_id")
            if fallback_candidate and ":" not in fallback_candidate and " " not in fallback_candidate:
                order_data["order_id"] = fallback_candidate
                print(f"✅ Using fallback order_id from extras: {fallback_candidate}")
            else:
                print(f"⚠️ order_id missing or invalid — falling back to TS: {order_ts}")
                order_data["order_id"] = order_ts
        # Ensure real names are resolved if missing or defaulting to Slack IDs
        if not order_data.get("requester_real_name") or order_data["requester_real_name"].startswith("U0"):
            order_data["requester_real_name"] = resolve_real_name(user_id, client)
        if not order_data.get("recipient_real_name") or order_data["recipient_real_name"].startswith("U0"):
            order_data["recipient_real_name"] = resolve_real_name(gifted_id or user_id, client)
        extras["requester_real_name"] = order_data["requester_real_name"]
        extras["recipient_real_name"] = order_data["recipient_real_name"]
        print("🛠️ Calling format_order_message with updated remaining time")
        print(f"🧪 Debug: order_data['order_id'] at countdown tick = {order_data['order_id']}")
        order_data["drink"] = extras.get("drink", drink)
        order_data["location"] = extras.get("location", location)
        order_data["notes"] = extras.get("notes", notes)
        order_data["claimed_by"] = extras.get("claimed_by", "")
        order_data["runner_real_name"] = extras.get("runner_real_name", "")
        order_data["delivered_by"] = extras.get("delivered_by", "")
        order_data["status"] = extras.get("status", "ordered")
 
        order_extras[order_ts]["requester_real_name"] = order_data["requester_real_name"]
        order_extras[order_ts]["recipient_real_name"] = order_data["recipient_real_name"]
        order_extras[order_ts]["drink"] = order_data["drink"]
        order_extras[order_ts]["location"] = order_data["location"]
        order_extras[order_ts]["notes"] = order_data["notes"]
        order_extras[order_ts]["claimed_by"] = order_data.get("claimed_by", "")
        order_extras[order_ts]["runner_real_name"] = order_data.get("runner_real_name", "")
        order_extras[order_ts]["delivered_by"] = order_data.get("delivered_by", "")
        order_extras[order_ts]["remaining_minutes"] = remaining
 
        print(f"🧩 [BEFORE format_order_message] order_data keys: {list(order_data.keys())}")
        print(f"🧩 [BEFORE format_order_message] order_id: {order_data.get('order_id')} ({type(order_data.get('order_id'))})")
        print(f"🧩 [BEFORE format_order_message] gifted_id: {gifted_id} → recipient_real_name: {order_data.get('recipient_real_name')}")
        print(f"🧪 Calling format_order_message with order_id={order_data.get('order_id', '[MISSING]')}")
        order_data["remaining_minutes"] = remaining
        if order_data.get("order_id"):
            updated_blocks = format_order_message(order_data)
        else:
            print(f"⚠️ Skipping format_order_message — missing order_id in payload: {order_data}")
            updated_blocks = []
 
        current_blocks = current_message["messages"][0].get("blocks", [])
        if any(block.get("block_id") == "reminder_block" for block in current_blocks):
            updated_blocks.insert(0, {
                "type": "section",
                "block_id": "reminder_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "*⚠️ STILL UNCLAIMED — CLOCK'S TICKING ⏳*"
                }
            })
        print(f"🔍 Progress bar update should now be reflected in updated_blocks:\n{updated_blocks}")
        print(f"📨 Message fetch result: {current_message}")
 
        original_text = current_message["messages"][0].get("text", "")
        print(f"📝 Original message text (repr): {repr(original_text)}")
        print(f"📤 Sending updated Slack message with remaining_minutes = {remaining}")
        print(f"🧾 Updated blocks:\n{updated_blocks}")
        print(f"🧪 Sending to Slack with FROM: {order_data.get('requester_real_name')} TO: {order_data.get('recipient_real_name')}")
        print(f"🧭 Preparing to push update to Slack for ts={order_ts} — countdown: {remaining}")
        safe_chat_update(client, order_channel, order_ts, "Order update: Countdown updated", updated_blocks)
        print(f"✅ safe_chat_update completed with order_id={order_data.get('order_id')}")
        print(f"🧩 Final order_data post-update: {json.dumps(order_data, indent=2)}")
        print(f"✅ Countdown update pushed to ts={order_ts} in channel={order_channel}")
        print("✅ Countdown block update pushed to Slack")
        print(f"📣 client.chat_update call completed for order {order_ts}")
        if remaining == 0 and extras.get("status") == "ordered":
            from sheet import add_karma
            add_karma(user_id, karma_cost)
            client.chat_postMessage(
                channel=user_id,
                text="∴ Order UNCLAIMED. Karma returned to your balance.."
            )
            if extras:
                extras["active"] = False
                extras["status"] = "expired"
            safe_chat_update(client, order_channel, order_ts, f"Order from <@{user_id}> EXPIRED — No claimant arose.", [])
            from sheet import update_order_status
            update_order_status(order_ts, status="expired")
            return

        if remaining > 0:
            print(f"🕒 Scheduling next countdown tick — remaining: {remaining - 1}")
            t = threading.Timer(60, update_countdown, args=(
                client, remaining - 1, str(order_ts), order_channel,
                user_id, gifted_id, drink, location, notes, karma_cost
            ))
            print("🌀 Starting new countdown thread with threading.Timer")
            sys.stdout.flush()
            t.start()
            print("🌀 Countdown timer thread started")
    except Exception as e:
        print("⚠️ Error in update_countdown:", e)

@app.action("location_select")
def handle_location_select(ack, body, client):
    print("📩 [DEBUG] location_select triggered")
    user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]
    selected_location = body["actions"][0]["selected_option"]["value"]
    if not selected_location:
        selected_location = body["view"].get("private_metadata", "")
    print(f"📍 [DEBUG] selected_location from dropdown = {selected_location}")

    global last_selected_location
    last_selected_location[user_id] = selected_location
    print(f"📝 [DEBUG] Saved last_selected_location for {user_id} = {selected_location}")

    print("📐 [DEBUG] Calling build_order_modal with selected_location...")
    modal = build_order_modal(trigger_id, selected_location=selected_location)
    client.views_update(view_id=body["container"]["view_id"], view=modal["view"])
    ack()
    print("🧱 [DEBUG] Updated modal blocks:")

@app.action("claim_order")
def handle_claim_order(ack, body, client):
    print("🎯 claim_order button clicked!")
    ack()
    import datetime
    import json
    from sheet import update_order_status
    order_id = body["actions"][0]["value"]
    from sheet import fetch_order_data
    order_data = fetch_order_data(order_id)
    # Fill in missing keys with safe defaults to avoid KeyErrors
    defaults = {
        "drink": "UNKNOWN",
        "location": "UNKNOWN",
        "notes": "",
        "karma_cost": 1,
        "runner_real_name": f"<@{body['user']['id']}>",
        "requester_real_name": "",
        "recipient_real_name": "",
    }
    for key, default in defaults.items():
        if key not in order_data:
            order_data[key] = default
    if not order_data or "requester_id" not in order_data:
        print(f"🚨 Missing order data or requester_id for order_id {order_id}")
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=body["user"]["id"],
            text="‡ Failed to claim order. Something went wrong — try again in a moment."
        )
        return
    order_data["claimed_by"] = order_data.get("runner_real_name")
    runner_id = body["user"]["id"]
    if order_data.get("requester_id") == runner_id and runner_id != "U02EY5S5J0M":
        client.chat_postEphemeral(
            channel=runner_id,
            user=runner_id,
            text="§ You cannot claim your own orders. Wait for another to rise."
        )
        return
    order_data["runner_id"] = runner_id
    try:
        user_info = client.users_info(user=runner_id)
        order_data["runner_real_name"] = user_info["user"]["real_name"]
        order_data["runner_name"] = user_info["user"]["real_name"]
        order_data["claimed_by"] = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch runner real name:", e)
        order_data["runner_real_name"] = f"<@{runner_id}>"
        order_data["runner_name"] = f"<@{runner_id}>"
    order_data["claimed_by"] = order_data["runner_real_name"]

    channel = body.get("container", {}).get("channel_id")
    ts = body.get("container", {}).get("message_ts")
    if channel and ts:
        from sheet import update_order_status
        print(f"📝 update_order_status(order_id={order_data['order_id']}, status={order_data['status']}, claimed_time={order_data['time_claimed']})")
        update_order_status(
            order_id,
            status="claimed",
            claimed_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            runner_id=order_data["runner_id"],
            runner_name=order_data["runner_real_name"]
        )
        from sheet import fetch_order_data  # ensure this is imported
        order_data = fetch_order_data(order_id)
        order_data["order_id"] = order_id
        order_data["status"] = "claimed"
        if order_id not in order_extras:
            order_extras[order_id] = {}
        order_extras[order_id]["status"] = "claimed"
        order_extras[order_id]["active"] = False
        blocks = format_order_message(order_data)
        print(f"🧪 [DEBUG] Final blocks length: {len(blocks)} — intended update to ts={order_data['order_id']}")
        safe_chat_update(client, channel, ts, "Order update: Order claimed", blocks)

    try:
        client.chat_postMessage(channel=order_data["requester_id"], text="¤ Order CLAIMED. Delivery en route.")
    except Exception as e:
        print("⚠️ Failed to notify requester:", e)

    try:
        if order_data.get("runner_id"):
            client.chat_postMessage(channel=order_data["runner_id"], text="¤ Delivery CLAIMED. Mark as delivered when dropped.")
    except Exception as e:
        print("⚠️ Failed to notify runner:", e)

@app.action("mark_delivered")
def handle_mark_delivered(ack, body, client):
    ack()
    import datetime
    from sheet import update_order_status

    order_id = body["actions"][0]["value"]
    user_id = body["user"]["id"]
    order_ts = body.get("container", {}).get("message_ts")
    order_channel = body.get("container", {}).get("channel_id")

    # Rely solely on fetch_order_data and Slack API lookups; fallback parsing removed.
    order_data = fetch_order_data(order_id)

    from random import random
    r = random()
    if r < 0.1:
        multiplier = 3
    elif r < 0.2:
        multiplier = 2
    else:
        multiplier = 1
    print(f"🎲 Bonus multiplier roll: r={r} → multiplier={multiplier}")
    bonus_multiplier = multiplier

    # Calculate final karma
    karma_cost = int(order_data.get("karma_cost", 1))
    total_karma = karma_cost * multiplier
    from sheet import add_karma, get_title
    runner_karma = add_karma(order_data["runner_id"], total_karma)
    title = get_title(runner_karma)
    client.chat_postMessage(
        channel=order_data["runner_id"],
        text=f"¤ Delivery COMPLETED. +{total_karma} karma granted. Title: {title}."
    )

    order_data.update({
        "status": "delivered",
        "time_delivered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bonus_multiplier": bonus_multiplier,
        "runner_karma": runner_karma,
        "runner_id": user_id,
        "delivered_by": order_data.get("runner_real_name") or order_data.get("runner_name") or f"<@{user_id}>"
    })

    if order_data.get("order_id"):
        blocks = format_order_message(order_data)
    else:
        print(f"⚠️ Skipping format_order_message — missing order_id in payload: {order_data}")
        blocks = []
    safe_chat_update(client, order_channel, order_ts, "Order update: Order delivered", blocks)

    update_order_status(
        order_id,
        status=order_data["status"],
        bonus_multiplier=order_data["bonus_multiplier"],
        delivered_time=order_data["time_delivered"]
    )
    order_data["status"] = "delivered"
    if order_id not in order_extras:
        order_extras[order_id] = {}
    order_extras[order_id]["status"] = "delivered"
    order_extras[order_id]["active"] = False
    
    # Mark runner's claim as delivered
    if order_data.get("runner_id") in runner_offer_claims:
        runner_offer_claims[order_data["runner_id"]]["delivered"] = True

    if multiplier > 1:
        bonus_msg = f"¤ <@{user_id}> earned {multiplier}x bonus karma on this run."
        try:
            client.chat_postMessage(channel=order_channel, text=bonus_msg)
        except Exception as e:
            print("⚠️ Failed to post bonus message:", e)

@app.action("cancel_order")
def handle_cancel_order(ack, body, client):
    ack()
    try:
        value = body["actions"][0]["value"]
        order_id, requester_id = value.split("|")
        ts = body["container"]["message_ts"]
        channel = body["container"]["channel_id"]

        cancel_text = f"Order canceled by <@{requester_id}>."
        safe_chat_update(client, channel, ts, cancel_text, [])

        from sheet import update_order_status
        update_order_status(order_id, status="canceled")
        if order_id not in order_extras:
            order_extras[order_id] = {}
        order_extras[order_id]["status"] = "canceled"
        order_extras[order_id]["active"] = False
        from sheet import fetch_order_data, add_karma
        order_data = fetch_order_data(order_id)
        refund_amount = order_data.get("karma_cost", 1)
        add_karma(requester_id, refund_amount)

        client.chat_postMessage(
            channel=requester_id,
            text="× Order CANCELED. Karma returned to your balance."
        )
    except Exception as e:
        print("⚠️ Failed to cancel order:", e)

@app.action("cancel_ready_offer")
def handle_cancel_ready_offer(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    channel = body["container"]["channel_id"]
    ts = body["container"]["message_ts"]

    try:
        # Replace the runner terminal with a cancellation message
        cancel_text = f"Delivery offer canceled by <@{user_id}>."
        client.chat_update(channel=channel, ts=ts, text=cancel_text, blocks=[])
        from sheet import update_order_status
        update_order_status(ts, status="canceled")

        # Cleanup any existing claim
        runner_offer_claims[user_id] = {"canceled": True}
        if ts not in order_extras:
            order_extras[ts] = {}
        order_extras[ts]["status"] = "canceled"
        order_extras[ts]["active"] = False

        print(f"🛑 Runner offer canceled by {user_id}")
    except Exception as e:
        print("⚠️ Failed to cancel runner offer:", e)

def handle_modal_submission(view, client, channel):
    import json, datetime
    # Extract source_order_id from private_metadata and determine order_ts
    meta = json.loads(view.get("private_metadata", "{}"))
    source_order_id = meta.get("source_order_id", "")
    order_ts = source_order_id or str(datetime.datetime.now().timestamp())
    # Use source_order_id as order_id if provided, otherwise fallback to order_ts
    order_data = {}  # Build order_data from view submission as needed
    order_data["order_id"] = source_order_id or order_ts

    # Replace terminal chat_postMessage with safe_chat_update to update the existing message
    safe_chat_update(client, channel, source_order_id, "Order update: Drop claimed", format_order_message(order_data))

def update_ready_countdown(client, remaining, ts, channel, user_id, original_total_time):
    print(f"🕵️ Entered update_ready_countdown: remaining={remaining}, ts={ts}, user_id={user_id}")
    extras = order_extras.get(ts)
    if extras and extras.get("status") in ["delivered", "canceled"]:
        print(f"⛔ Skipping expiration — order {ts} is already marked as {extras.get('status')}")
        return
    print(f"DEBUG: Countdown tick for order {ts} with remaining = {remaining}")
    extras = order_extras.get(ts)
    if extras and extras.get("status") in ["delivered", "canceled"]:
        print(f"⛔ Skipping expiration — order {ts} is already marked as {extras.get('status')}")
        return
    print(f"🧪 Checking if message should expire: remaining={remaining}")
    if ts in order_extras:
        status = order_extras[ts].get("status", "")
        if status in ["delivered", "canceled"]:
            print(f"⛔ Skipping expiration — order {ts} is already marked as {status}")
            return
    if user_id in runner_offer_claims and runner_offer_claims[user_id].get("delivered") is True:
        print(f"⛔ Countdown halted — delivery offer by {user_id} already completed.")
        return

    if user_id in runner_offer_claims and runner_offer_claims[user_id].get("canceled") is True:
        print(f"⛔ Countdown halted — delivery offer by {user_id} already canceled.")
        return
    if user_id in runner_offer_claims and runner_offer_claims[user_id].get("fulfilled") is True:
        print(f"⛔ Countdown halted — delivery offer by {user_id} already fulfilled.")
        return
    if remaining <= 0:
        if ts in order_extras:
            status = order_extras[ts].get("status", "")
            if status in ["delivered", "canceled"]:
                print(f"⛔ Skipping expiration — order {ts} is already marked as {status}")
                return
        print("🚨 Countdown reached zero — attempting to expire message")
        try:
            from slack_sdk.errors import SlackApiError
            expired_text = f"Delivery offer from <@{user_id}> EXPIRED — No order was placed."
            client.chat_update(
                channel=channel,
                ts=ts,
                text=expired_text,
                blocks=[]
            )
            from sheet import update_order_status
            update_order_status(ts, status="expired")
            print(f"✅ Successfully expired runner message ts={ts} for user_id={user_id}")
            print("☠️ Runner offer expired and message replaced.")
        except SlackApiError as e:
            print("⚠️ Slack API error during runner expiration update:", e.response['error'])
        except Exception as e:
            print("⚠️ Failed to update expired runner offer message:", e)
        return
    from sheet import get_runner_capabilities
    runner_capabilities = get_runner_capabilities(user_id)
    real_name = runner_capabilities.get("Name", f"<@{user_id}>")
    pretty_caps = {
        "water": "Water",
        "drip_coffee": "Drip Coffee",
        "espresso_drinks": "Espresso Drinks",
        "tea": "Tea"
    }
    saved_caps = runner_capabilities.get("Capabilities", [])
    all_options = ["water", "tea", "drip_coffee", "espresso_drinks"]
    can_make = [pretty_caps[c] for c in saved_caps if c in pretty_caps]
    cannot_make = [pretty_caps[c] for c in all_options if c not in saved_caps]
    can_make_str = ", ".join(can_make) if can_make else "NONE"
    cannot_make_str = ", ".join(cannot_make) if cannot_make else "NONE"
    
    total_blocks = 20
    filled_blocks = round((remaining / original_total_time) * total_blocks)
    empty_blocks = total_blocks - filled_blocks
    progress_bar = "[" + ("█" * filled_blocks) + ("░" * empty_blocks) + "]"
    print(f"DEBUG: Progress bar: filled_blocks = {filled_blocks}, empty_blocks = {empty_blocks}")
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "```"
                    + "+----------------------------------------+\n"
                    + "|       𐂀 DRINK RUNNER AVAILABLE 𐂀       |\n"
                    + "+----------------------------------------+\n"
                    + "\n".join(box_line(label="RUNNER", value=real_name.upper(), width=42)) + "\n"
                    + "\n".join(box_line(label="CAN MAKE", value=can_make_str, width=42)) + "\n"
                    + "\n".join(box_line(label="CAN'T MAKE", value=cannot_make_str, width=42)) + "\n"
                    + "+----------------------------------------+\n"
                    + "\n".join(box_line(text=f"TIME LEFT ON SHIFT: {remaining} MINUTES", width=42, align="center")) + "\n"
                    + "\n".join(box_line(text=progress_bar, width=42, align="center")) + "\n"
                    + "\n".join(box_line(text="------------------------------------", width=42, align="center")) + "\n"
                    + "\n".join(box_line(text="↓ CLICK BELOW TO PLACE AN ORDER ↓", width=42, align="center")) + "\n"
                    + "\n".join(box_line(text="------------------------------------", width=42, align="center")) + "\n"
                    + "+----------------------------------------+```"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_order_modal_for_runner",
                    "text": {
                        "type": "plain_text",
                        "text": "ORDER NOW",
                        "emoji": True
                    },
                    "value": json.dumps({"runner_id": user_id, "source_order_id": ts})
                },
                {
                    "type": "button",
                    "action_id": "cancel_ready_offer",
                    "text": {
                        "type": "plain_text",
                        "text": "CANCEL",
                        "emoji": True
                    },
                    "style": "danger",
                    "value": user_id
                }
            ]
        }
    ]
    safe_chat_update(
        client,
        channel,
        ts,
        f"<@{user_id}> IS READY TO DELIVER — {remaining} MINUTES LEFT.",
        blocks
    )
    if ts not in order_extras:
        order_extras[ts] = {}
    order_extras[ts]["order_id"] = ts

        # 🔁 Always schedule next tick if countdown is not done
    import threading
    import threading
    print(f"DEBUG: Scheduling next tick for order {ts}, remaining = {remaining - 1}")
    threading.Timer(60, update_ready_countdown, args=(client, remaining - 1, ts, channel, user_id, original_total_time)).start()
    print(f"🕓 Next tick scheduled for ts={ts}, remaining={remaining - 1}")
    if remaining == 1:
        print(f"⚠️ WARNING: This countdown will end after this tick. Watch for expiration.")

@app.command("/redeem")
def handle_redeem(ack, body, client):
    ack()
    code = body.get("text", "").strip()
    user_id = body["user_id"]
    result = mark_code_redeemed(code, user_id)
    client.chat_postEphemeral(channel=body["channel_id"], user=user_id, text=f"Redemption result: {result}")

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    if request.headers.get("Content-Type") == "application/json":
        if request.json and "challenge" in request.json:
            return jsonify({"challenge": request.json["challenge"]})
    
    print("📩 Incoming Slack event")
    response = handler.handle(request)
    print("✅ Passed to Bolt handler")
    return response

@app.event("app_mention")
def say_hello(event, say):
    print("🎯 Bot was mentioned!", event)
    user = event["user"]
    say(f"What do you want, <@{user}>? Orders in. Deliveries pending. Let’s move.")

@app.event("app_home_opened")
def handle_app_home_opened_events(body, logger):
    # Silently ignore app_home_opened events to suppress 404 log messages
    pass

def build_order_modal(trigger_id, runner_id="", selected_location="", source_order_id=""):
    
    print(f"📍 [DEBUG] build_order_modal called with selected_location: {selected_location}")
    if selected_location is None:
        selected_location = ""

    location_block = {
    "type": "section",
    "block_id": "location",
    "text": {"type": "mrkdwn", "text": "*Drop location?*"},
    "accessory": {
        "type": "static_select",
        "action_id": "location_select",
        "options": [ 
            {"text": {"type": "plain_text", "text": "4A"}, "value": "4A"},
            {"text": {"type": "plain_text", "text": "4B"}, "value": "4B"},
            {"text": {"type": "plain_text", "text": "4C"}, "value": "4C"},
            {"text": {"type": "plain_text", "text": "4D"}, "value": "4D"},
            {"text": {"type": "plain_text", "text": "4E"}, "value": "4E"},
            {"text": {"type": "plain_text", "text": "4F"}, "value": "4F"},
            {"text": {"type": "plain_text", "text": "4H"}, "value": "4H"},
            {"text": {"type": "plain_text", "text": "4I"}, "value": "4I"},
            {"text": {"type": "plain_text", "text": "4J"}, "value": "4J"},
            {"text": {"type": "plain_text", "text": "4K"}, "value": "4K"},
            {"text": {"type": "plain_text", "text": "4L"}, "value": "4L"},
            {"text": {"type": "plain_text", "text": "4M"}, "value": "4M"},
            {"text": {"type": "plain_text", "text": "4N"}, "value": "4N"},
            {"text": {"type": "plain_text", "text": "4O"}, "value": "4O"},
            {"text": {"type": "plain_text", "text": "4P"}, "value": "4P"},
            {"text": {"type": "plain_text", "text": "4Q"}, "value": "4Q"},
            {"text": {"type": "plain_text", "text": "AV Closet"}, "value": "AV Closet"},
            {"text": {"type": "plain_text", "text": "Beach 1"}, "value": "Beach 1"},
            {"text": {"type": "plain_text", "text": "Beach 2"}, "value": "Beach 2"},
            {"text": {"type": "plain_text", "text": "Café"}, "value": "Café"},
            {"text": {"type": "plain_text", "text": "Café Booths"}, "value": "Café Booths"},
            {"text": {"type": "plain_text", "text": "Cavity 1"}, "value": "Cavity 1"},
            {"text": {"type": "plain_text", "text": "Cavity 2"}, "value": "Cavity 2"},
            {"text": {"type": "plain_text", "text": "Cherry Pit"}, "value": "Cherry Pit"},
            {"text": {"type": "plain_text", "text": "Cork Canyon"}, "value": "Cork Canyon"},
            {"text": {"type": "plain_text", "text": "Digital Dream Lab"}, "value": "Digital Dream Lab"},
            {"text": {"type": "plain_text", "text": "Elevator"}, "value": "Elevator"},
            {"text": {"type": "plain_text", "text": "Facilities Storage"}, "value": "Facilities Storage"},
            {"text": {"type": "plain_text", "text": "Hive"}, "value": "Hive"},
            {"text": {"type": "plain_text", "text": "Honey"}, "value": "Honey"},
            {"text": {"type": "plain_text", "text": "Lactation Lounge"}, "value": "Lactation Lounge"},
            {"text": {"type": "plain_text", "text": "Mini Shop"}, "value": "Mini Shop"},
            {"text": {"type": "plain_text", "text": "NW Studio"}, "value": "NW Studio"},
            {"text": {"type": "plain_text", "text": "Play Lab"}, "value": "Play Lab"},
            {"text": {"type": "plain_text", "text": "Play Lab Photo Studio"}, "value": "Play Lab Photo Studio"},
            {"text": {"type": "plain_text", "text": "Production"}, "value": "Production"},
            {"text": {"type": "plain_text", "text": "Production/Shop Storage"}, "value": "Production/Shop Storage"},
            {"text": {"type": "plain_text", "text": "Prototyping Kitchen"}, "value": "Prototyping Kitchen"},
            {"text": {"type": "plain_text", "text": "Redwood 1"}, "value": "Redwood 1"},
            {"text": {"type": "plain_text", "text": "Redwood 2"}, "value": "Redwood 2"},
            {"text": {"type": "plain_text", "text": "Redwood 3"}, "value": "Redwood 3"},
            {"text": {"type": "plain_text", "text": "Redwood 4"}, "value": "Redwood 4"},
            {"text": {"type": "plain_text", "text": "Redwood Booths"}, "value": "Redwood Booths"},
            {"text": {"type": "plain_text", "text": "Restrooms"}, "value": "Restrooms"},
            {"text": {"type": "plain_text", "text": "Shipping/Receiving"}, "value": "Shipping/Receiving"},
            {"text": {"type": "plain_text", "text": "Shop"}, "value": "Shop"},
            {"text": {"type": "plain_text", "text": "Spray Booth"}, "value": "Spray Booth"},
            {"text": {"type": "plain_text", "text": "Sugar Cube 1"}, "value": "Sugar Cube 1"},
            {"text": {"type": "plain_text", "text": "Sugar Cube 2"}, "value": "Sugar Cube 2"},
            {"text": {"type": "plain_text", "text": "Sugar Cube 3"}, "value": "Sugar Cube 3"},
            {"text": {"type": "plain_text", "text": "Sugar Cube 4"}, "value": "Sugar Cube 4"},
            {"text": {"type": "plain_text", "text": "SW Studio"}, "value": "SW Studio"},
            {"text": {"type": "plain_text", "text": "Technology"}, "value": "Technology"},
            {"text": {"type": "plain_text", "text": "The Cookie Jar"}, "value": "The Cookie Jar"},
            {"text": {"type": "plain_text", "text": "The Courtyard"}, "value": "The Courtyard"},
            {"text": {"type": "plain_text", "text": "The Crumb"}, "value": "The Crumb"},
            {"text": {"type": "plain_text", "text": "The Jam"}, "value": "The Jam"},
            {"text": {"type": "plain_text", "text": "The Jelly"}, "value": "The Jelly"},
            {"text": {"type": "plain_text", "text": "The Lookout"}, "value": "The Lookout"},
            {"text": {"type": "plain_text", "text": "The Scoop"}, "value": "The Scoop"},
            {"text": {"type": "plain_text", "text": "Theater"}, "value": "Theater"},
            {"text": {"type": "plain_text", "text": "Vista 1"}, "value": "Vista 1"},
            {"text": {"type": "plain_text", "text": "Vista 2"}, "value": "Vista 2"},
            {"text": {"type": "plain_text", "text": "Vista 3"}, "value": "Vista 3"}
        ]
    }
}
    if selected_location:
        location_block["accessory"]["initial_option"] = {
            "text": {"type": "plain_text", "text": selected_location},
            "value": selected_location
        }

    return {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "koffee_request_modal",
            "title": {"type": "plain_text", "text": "Place An Order"},
            "submit": {"type": "plain_text", "text": "Submit Drop"},
            "close": {"type": "plain_text", "text": "Nevermind"},
            "private_metadata": json.dumps({
                "mode": "order",
                "location": selected_location,
                **({"runner_id": runner_id} if runner_id else {}),
                **({"source_order_id": source_order_id} if source_order_id else {})
            }),
            "blocks": [
                { 
                    "type": "input",
                    "block_id": "drink_category",
                    "label": {"type": "plain_text", "text": "Select your drink category"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Water (Still/Sparkling) — 1 Karma"},
                                "value": "water"
                            },
                            {
                                "text": {"type": "plain_text", "text": "Tea — 2 Karma"},
                                "value": "tea"
                            },
                            {
                                "text": {"type": "plain_text", "text": "Drip Coffee — 2 Karma"},
                                "value": "drip"
                            },
                            {
                                "text": {"type": "plain_text", "text": "Espresso Drinks — UNAVAILABLE ⊘"},
                                "value": "espresso"
                            }
                        ]
                    }
                },
                {
                    "type": "input",
                    "block_id": "drink_detail",
                    "label": {"type": "plain_text", "text": "Specify your drink"},
                    "element": {"type": "plain_text_input", "action_id": "input", "max_length": 30}
                },
                location_block,
                {
                "type": "section",
                "block_id": "ascii_map_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "```" + format_full_map_with_legend(build_mini_map(selected_location)) + "```"
                }
                },
                {
                    "type": "input",
                    "block_id": "gift_to",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Gift drink to"},
                    "element": {
                        "type": "users_select",
                        "action_id": "input",
                    }
                },
                {
                    "type": "input",
                    "block_id": "notes",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Additional notes"},
                    "element": {"type": "plain_text_input", "action_id": "input", "max_length": 30}
                }
            ]
        }
    }

@app.command("/leaderboard")
def handle_leaderboard(ack, body, client):
    ack()
    from sheet import get_leaderboard, get_title
    leaderboard = get_leaderboard()
 
    # We'll define a consistent table format with extra spacing for RANK and KARMA,
    # and ensure NAME/TITLE entries are left-aligned with one space of padding at the start.
 
    lines = []
    # Header bar (unchanged, though note it won't perfectly match new column widths)
    lines.append("||=================[ ⚙ THE BREW SCROLL ⚙ ]=================||")
 
    # Column headings:
    # - RANK and KARMA get a single space padding on both sides: " RANK ", " KARMA "
    # - 8 chars wide for each of them, centered (^8).
    # - 20 chars wide for NAME and TITLE, each centered (^20) in the header row.
    lines.append("|{:^8}|{:^20}|{:^8}|{:^20}|".format(" RANK ", " NAME ", " KARMA ", " TITLE "))
 
    # Divider line with exact widths: 8 for RANK, 20 for NAME, 8 for KARMA, 20 for TITLE
    lines.append("|--------|--------------------|--------|--------------------|")
 
    # Build each row of the leaderboard
    for i, entry in enumerate(leaderboard):
        # Convert the user name to uppercase, add one space at the front, then slice to 18
        raw_name = entry.get("Name", f"<@{entry['Slack ID']}>") or ""
        name_str = " " + raw_name.upper()[:18]  # e.g. " NEAL BOYER"
        
        # Convert the title to uppercase, also adding one space in front
        karma_value = int(entry.get("Karma", 0))
        raw_title = get_title(karma_value).upper() 
        title_str = " " + raw_title[:18]
 
        # RANK is centered in an 8-wide field
        rank_str = str(i + 1).center(8)
        # KARMA is centered in an 8-wide field
        karma_str = str(karma_value).center(8)
 
        # NAME and TITLE columns are left-aligned in 20 chars using {:<20}
        lines.append("|{:^8}|{:<20}|{:^8}|{:<20}|".format(
            rank_str,
            name_str,
            karma_str,
            title_str
        ))
 
    # Bottom navigation commands
    lines.append("+===========================================================+")
    lines.append("|      /ORDER  /DELIVER  /KARMA  /LEADERBOARD  /REDEEM      |")
    lines.append("+===========================================================+")
 
    leaderboard_text = "```" + "\n".join(lines) + "```"
 
    # Send a public message to the channel
    client.chat_postMessage(
        channel=body["channel_id"],
        text=leaderboard_text
    )

@app.command("/order")
def handle_order(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_order_modal(body["trigger_id"], selected_location="")["view"]
    )

@app.command("/karma")
def handle_karma(ack, body, client):
    ack()
    from sheet import get_karma, get_title
    user_id = body["user_id"]
    points = get_karma(user_id)
    title = get_title(points)
    message = f"¤ Balance: {points} karma — Title: {title}."
    client.chat_postEphemeral(channel=body["channel_id"], user=user_id, text=message)

@app.action("open_order_modal_for_runner")
def handle_open_order_modal_for_runner(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]
    selected_location = last_selected_location.get(user_id, "")  # ✅ Now defined first
    print(f"📍 [DEBUG] open_order_modal_for_runner — user_id: {user_id}")
    print(f"📍 [DEBUG] open_order_modal_for_runner — selected_location: {selected_location}")
    
    modal = build_order_modal(
        trigger_id=trigger_id,
        runner_id=user_id,
        source_order_id=body.get("message", {}).get("ts", ""),
        selected_location=selected_location
    )
    client.views_open(trigger_id=trigger_id, view=modal["view"])

@app.view("koffee_request_modal")
def handle_modal_submission(ack, body, client):
    global runner_offer_metadata
    ack()

    import datetime
    import json

    user_id = body["user"]["id"]

    private_metadata_raw = body["view"].get("private_metadata", "{}")
    try:
        metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        print("⚠️ Failed to parse private_metadata:", private_metadata_raw)
        metadata = {}
    print(f"📦 [DEBUG] Extracted metadata: {metadata}")

    # Use metadata here now that it's defined
    parent_ts = metadata.get("parent_ts", "")
    channel_id = metadata.get("channel_id", "")
    generated_ts = str(datetime.datetime.now().timestamp())
    order_id = parent_ts if parent_ts else generated_ts

    source_order_id = metadata.get("source_order_id", "")
    location = metadata.get("location", "")
    runner_id = metadata.get("runner_id", "")
    mode = metadata.get("mode", "order")
    print(f"📦 [DEBUG] Extracted metadata: location={location}, runner_id={runner_id}, mode={mode}")

    
    if parent_ts:
        print("🧾 [DEBUG] update_order_status invoked because parent_ts is present")
        from sheet import update_order_status, fetch_order_data

        existing_data = fetch_order_data(parent_ts)
        if existing_data:
            print("🧾 [DEBUG] Existing row found. Preparing to update instead of log.")

            # ⬇️ Parse modal values FIRST
            values = body["view"]["state"]["values"]
            drink = values["drink_category"]["input"]["selected_option"]["value"]
            drink_detail = values["drink_detail"]["input"]["value"]
            notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and isinstance(values["notes"]["input"]["value"], str) else ""
            gifted_id = values["gift_to"]["input"].get("selected_user") if "gift_to" in values and "input" in values["gift_to"] else None

            karma_cost = 1 if drink == "water" else (2 if drink in ["tea", "drip"] else 3)
            drink = drink_detail.strip()

            existing_data["drink"] = drink
            existing_data["notes"] = notes
            existing_data["location"] = metadata.get("location", "UNKNOWN")
            existing_data["karma_cost"] = karma_cost

            # THEN set up order_data
            order_data = {
                **existing_data,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "claimed",
                "time_claimed": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "requester_id": user_id,
                "requester_real_name": resolve_real_name(user_id, client),
                "recipient_id": gifted_id or user_id,
                "recipient_real_name": resolve_real_name(gifted_id or user_id, client),
            }

            # THEN update the row
            update_order_status(
                order_id=parent_ts,
                status="claimed",
                claimed_time=order_data["time_claimed"],
                requester_name=order_data["requester_real_name"],
                recipient_name=order_data["recipient_real_name"],
                order_data=order_data
            )

            print("🧾 [DEBUG] Skipping log_order_to_sheet because update_order_status handled the row")
            return
    else:
        # ⬇️ Parse modal values for standard /order flow
        values = body["view"]["state"]["values"]
        drink = values["drink_category"]["input"]["selected_option"]["value"]
        drink_detail = values["drink_detail"]["input"]["value"]
        notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and isinstance(values["notes"]["input"]["value"], str) else ""
        gifted_id = values["gift_to"]["input"].get("selected_user") if "gift_to" in values and "input" in values["gift_to"] else None

    karma_cost = 1 if drink == "water" else (2 if drink in ["tea", "drip"] else 3)
    drink = drink_detail.strip()

    print("📥 [DEBUG] In submission handler, view raw payload:")
    print(f"🔁 Entered handle_modal_submission for order from {user_id} at {datetime.datetime.now()}")

    order_extras[order_id] = {
        'active': True,
        'status': 'ordered',
        'order_id': order_id,
        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'ts': body.get("container", {}).get("message_ts", "")
    }

    print("📥 [DEBUG] In submission handler, view raw payload:")
    print(f"🔁 Entered handle_modal_submission for order from {user_id} at {datetime.datetime.now()}")

    if "order_data" not in locals():
        order_data = {
            "order_id": order_id,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "claimed",
            "time_claimed": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "requester_id": user_id,
            "requester_real_name": resolve_real_name(user_id, client),
            "recipient_id": user_id,
            "recipient_real_name": resolve_real_name(user_id, client),
            "drink": drink,
            "location": metadata.get("location", "UNKNOWN"),
            "notes": notes,
            "karma_cost": karma_cost,
            "bonus_multiplier": "",
            "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time_delivered": ""
        }

    order_data["order_id"] = order_id
    if order_id not in order_extras:
        order_extras[order_id] = {}
    order_extras[order_id]["order_id"] = order_id

    order_channel = os.environ.get("KOFFEE_KARMA_CHANNEL")
    source_order_id = metadata.get("source_order_id", "")

    if source_order_id:
        print(f"🔁 Overriding order_id with source_order_id: {source_order_id}")
        order_data["order_id"] = source_order_id
        order_ts = source_order_id
        blocks = format_order_message(order_data)
        safe_chat_update(client, order_channel, source_order_id, "Order update: Claimed", blocks)
    else:
        response = client.chat_postMessage(
            channel=order_channel,
            text="New order posted",
            blocks=format_order_message(order_data)
        )
        order_ts = response["ts"]

    location = metadata.get("location", "")
    runner_id = metadata.get("runner_id", "")
    mode = metadata.get("mode", "order")

    if not order_ts and runner_id in runner_offer_metadata:
        order_ts = runner_offer_metadata[runner_id]["ts"]
        order_channel = runner_offer_metadata[runner_id]["channel"]
        print(f"🧠 Using original runner message — order_ts: {order_ts}, order_channel: {order_channel}")
    else:
        print("⚠️ runner_offer_metadata missing — fallback to raw runner_id")
        order_ts = runner_id
        order_channel = os.environ.get("KOFFEE_KARMA_CHANNEL")
    print(f"🧪 [DEBUG] handle_modal_submission mode={mode}, runner_id={runner_id}")
    if mode == "order" and runner_id:
        order_data["order_id"] = runner_id  # runner_id holds the original /deliver ts
        order_data["status"] = "claimed"
        order_data["time_claimed"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Update the existing Slack message for the delivery offer with order details
        print(f"🧪 [DEBUG] Committed order_id: {order_data['order_id']}")
        print(f"🧪 [DEBUG] Should update ts = {order_ts}, channel = {order_channel}")
        print(f"🧪 [DEBUG] Logging order_data: {json.dumps(order_data, indent=2)}")
        blocks = format_order_message(order_data)
        safe_chat_update(
            client,
            channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
            ts=order_data["order_id"],
            text="Order update: Order placed from delivery offer",
            blocks=blocks
        )
        from sheet import update_order_status
        print(f"🧪 Updating existing order_id: {order_data['order_id']}")
        update_order_status(
            order_id=order_data["order_id"],
            status="claimed",
            claimed_time=order_data["time_ordered"],
            requester_name=order_data["requester_real_name"],
            recipient_name=order_data["recipient_real_name"],
            drink=order_data["drink"],
            location=order_data["location"],
            notes=order_data["notes"],
            karma_cost=order_data["karma_cost"],
            order_data=order_data
        )
        print(f"📤 [DEBUG] safe_chat_update called — channel={os.environ.get('KOFFEE_KARMA_CHANNEL')}, ts={order_data['order_id']}")
        print(f"📤 [DEBUG] Updating Slack message for /deliver flow — ts={order_data['order_id']}, order_id={order_data['order_id']}")
        state = body["view"]["state"]["values"]
        category = state["drink_category"]["input"]["selected_option"]["value"]
        drink = state["drink_detail"]["input"]["value"]
        notes = state["notes"]["input"]["value"]
        gifted_id = state["gift_to"]["input"].get("selected_user") or user_id

        order_data["drink"] = drink
        order_data["location"] = location
        order_data["notes"] = notes
        order_data["recipient_id"] = gifted_id
        order_data["recipient_real_name"] = resolve_real_name(gifted_id, client)

        order_data["karma_cost"] = (
            1 if category == "water" else
            2 if category in ["tea", "drip"] else
            3
        )

        # In /deliver flow, the runner_id (actually the message_ts) is the order_id
        order_data["order_id"] = runner_id
        print(f"🧪 Using runner_id as order_id (for /deliver flow): {order_data['order_id']}")
        existing = fetch_order_data(runner_id)
        order_data.update(existing)  # Start with the original row data
        print(f"🧩 [DEBUG] After merge — order_data keys: {list(order_data.keys())}, order_id: {order_data.get('order_id')}")
        order_data["requester_id"] = user_id
        order_data["requester_real_name"] = resolve_real_name(user_id, client)
        order_data["recipient_id"] = user_id
        order_data["recipient_real_name"] = resolve_real_name(user_id, client)
        order_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order_data["claimed_by"] = existing.get("runner_name") or existing.get("runner_real_name") or order_data.get("runner_id")
        order_data["runner_name"] = existing.get("runner_name") or resolve_real_name(existing.get("runner_id"), client)
        order_data["runner_real_name"] = order_data["runner_name"]
        order_data["ts"] = order_data["order_id"]
        order_data["channel"] = os.environ.get("KOFFEE_KARMA_CHANNEL")
        countdown_timers[order_data["order_id"]] = 10
        order_data["runner_id"] = existing.get("runner_id")
        order_data["initiated_by"] = "runner"
        order_extras[order_data["order_id"]] = {"active": False, "status": "claimed"}
        # Update Slack message and log order to sheet
        blocks = format_order_message(order_data)
        print(f"🧪 [DEBUG] Final blocks length: {len(blocks)} — intended update to ts={order_data['order_id']}")
        print(f"🛠️ [DEBUG] Updating Slack message for order_id={order_data['order_id']} in /deliver flow")
        safe_chat_update(
            client,
            channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
            ts=order_data["order_id"],
            text="Order update: Order placed from delivery offer",
            blocks=blocks
        )
        print("DEBUG: update_order_status called with arguments:")
        print(f"  status: claimed")
        print(f"  claimed_time: {order_data['time_claimed']}")
        print(f"  requester_name: {order_data['requester_real_name']}")
        print(f"  recipient_name: {order_data['recipient_real_name']}")
        print(f"  drink: {order_data['drink']}")
        print(f"  location: {order_data['location']}")
        print(f"  notes: {order_data['notes']}")
        print(f"  karma_cost: {order_data['karma_cost']}")
        update_order_status(
            order_data["order_id"],
            status="claimed",
            claimed_time=order_data["time_claimed"],
            requester_name=order_data["requester_real_name"],
            recipient_name=order_data["recipient_real_name"],
            drink=order_data["drink"],
            location=order_data["location"],
            notes=order_data["notes"],
            karma_cost=order_data["karma_cost"]
        )
        print("✅ update_order_status completed for delivery-initiated order")

        
        # Mark the runner offer as fulfilled
        if runner_id:
            if runner_id and order_id in order_extras:
                print(f"🛠 Updating existing /deliver row with details from /order modal — order_id: {order_id}")
                from sheet import update_order_status
                update_order_status(
                    order_id,
                    order_data=order_data
                )
            if runner_id not in runner_offer_claims:
                runner_offer_claims[runner_id] = {}
            runner_offer_claims[runner_id]["fulfilled"] = True
    else:
        order_data["order_id"] = str(datetime.datetime.now().timestamp())
    print(f"🧪 [DEBUG] Assigned order_id = {order_data['order_id']}")
    if mode == "order" and runner_id:
        if not order_ts and runner_id in runner_offer_metadata:
            order_data["order_id"] = runner_offer_metadata[runner_id]["ts"]
            order_data["channel"] = runner_offer_metadata[runner_id]["channel"]
            print(f"🧪 Fallback restored ts={order_data['order_id']} and channel={order_data['channel']}")
        else:
            print("⚠️ No runner_offer_metadata found — cannot update original runner post")
            order_data["order_id"] = runner_id  # fallback to raw ts
            order_data["channel"] = os.environ.get("KOFFEE_KARMA_CHANNEL")
        blocks = format_order_message(order_data)
        print(f"📤 [DEBUG] Updating Slack message for /deliver flow — ts={order_data['order_id']}, order_id={order_data['order_id']}")
        safe_chat_update(
            client,
            channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
            ts=order_data["order_id"],
            text="Order update: Order placed from delivery offer",
            blocks=blocks
        )
        from sheet import update_order_status, log_order_to_sheet
        countdown_timers[order_data["order_id"]] = 10
        update_order_status(
            order_data["order_id"],
            status="claimed",
            claimed_time=order_data["time_claimed"],
            requester_name=order_data["requester_real_name"],
            recipient_name=order_data["recipient_real_name"],
            drink=order_data["drink"],
            location=order_data["location"],
            notes=order_data["notes"],
            karma_cost=order_data["karma_cost"],
            order_data=order_data

        )
        order_data["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # log_order_to_sheet(order_data)  # Removed to prevent duplicate logging
        order_extras[order_data["order_id"]] = {
            "active": False,
            "status": "claimed",
            "requester_real_name": order_data["requester_real_name"],
            "recipient_real_name": order_data["recipient_real_name"],
            "runner_real_name": order_data["runner_real_name"],
            "drink": order_data["drink"],
            "location": order_data["location"],
            "notes": order_data["notes"],
            "karma_cost": order_data["karma_cost"],
            "claimed_by": order_data["runner_real_name"],
            "delivered_by": "",
            "remaining_minutes": 10
        }
        countdown_timers[order_data["order_id"]] = 10
        return  # prevent further logic from treating it like a new order
    print(f"🆕 Initializing order_extras for order_id={order_data['order_id']}")
    order_extras[order_data["order_id"]] = {"active": True, "status": "ordered"}
    print(f"📦 [DEBUG] Initialized order_extras[{order_data['order_id']}] = {order_extras[order_data['order_id']]}")
    order_data["order_id"] = str(order_data["order_id"])  # ensure it's a string for downstream use

    if 'runner_offer_metadata' not in globals():
        print("⚠️ runner_offer_metadata not defined — initializing.")
        runner_offer_metadata = {}
    values = body["view"]["state"]["values"]
    if not location:
        print("❌ Modal submission blocked: location not selected — refreshing modal with error")
        modal = build_order_modal(trigger_id="", selected_location=location)
        blocks = modal["view"]["blocks"]
        error_block = {
            "type": "context",
            "block_id": "location_error",
            "elements": [
                { "type": "mrkdwn", "text": "∆ You must select a location before submitting." }
            ]
        }
        blocks.insert(3, error_block)
 
        # Preserve previous inputs
        drink_value = values["drink_category"]["input"]["selected_option"]["value"]
        drink_detail = values["drink_detail"]["input"]["value"]
        notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and isinstance(values["notes"]["input"]["value"], str) else ""
        gifted_id = values["gift_to"]["input"].get("selected_user") if "gift_to" in values and "input" in values["gift_to"] else None
 
        for block in blocks:
            if block.get("block_id") == "drink_category":
                for option in block["element"]["options"]:
                    if option["value"] == drink_value:
                        block["element"]["initial_option"] = option
                        break
            elif block.get("block_id") == "drink_detail":
                block["element"]["initial_value"] = drink_detail
            elif block.get("block_id") == "notes":
                block["element"]["initial_value"] = notes
            elif block.get("block_id") == "gift_to" and gifted_id:
                block["element"]["initial_user"] = gifted_id
            elif block.get("block_id") == "location":
                for ascii_block in blocks:
                    if ascii_block.get("block_id") == "ascii_map_block":
                        from app import format_full_map_with_legend, build_mini_map
                        ascii_block["text"]["text"] = "```" + format_full_map_with_legend(build_mini_map(location)) + "```"
 
        ack(response_action="update", view={
            "type": "modal",
            "callback_id": "koffee_request_modal",
            "title": {"type": "plain_text", "text": "Place An Order"},
            "submit": {"type": "plain_text", "text": "Submit Drop"},
            "close": {"type": "plain_text", "text": "Nevermind"},
            "private_metadata": json.dumps({
                "mode": mode,
                "location": location,
                "runner_id": runner_id
            }),
            "blocks": modal["view"]["blocks"]
        })

        modal = build_order_modal(trigger_id="", selected_location=location)
        blocks = modal["view"]["blocks"]

        # Insert error message below location dropdown
        error_block = {
            "type": "context",
            "block_id": "location_error",
            "elements": [
                { "type": "mrkdwn", "text": "∆ You must select a location before submitting." }
            ]
        }
        blocks.insert(3, error_block)

        # Preserve previous selections/input
        drink_value = values["drink_category"]["input"]["selected_option"]["value"]
        drink_detail = values["drink_detail"]["input"]["value"]
        notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and isinstance(values["notes"]["input"]["value"], str) else ""
        gifted_id = values["gift_to"]["input"]["selected_user"] if "gift_to" in values and "input" in values["gift_to"] else None

        for block in blocks:
            if block.get("block_id") == "drink_category":
                for option in block["element"]["options"]:
                    if option["value"] == drink_value:
                        block["element"]["initial_option"] = option
                        break
            elif block.get("block_id") == "drink_detail":
                block["element"]["initial_value"] = drink_detail
            elif block.get("block_id") == "notes":
                block["element"]["initial_value"] = notes
            elif block.get("block_id") == "gift_to" and gifted_id:
                block["element"]["initial_user"] = gifted_id
            elif block.get("block_id") == "location":
                # No location selected, so do not set initial_option
 
                # Refresh the map using the selected location
                for ascii_block in blocks:
                    if ascii_block.get("block_id") == "ascii_map_block":
                        from app import format_full_map_with_legend, build_mini_map
                        ascii_block["text"]["text"] = "```" + format_full_map_with_legend(build_mini_map(location)) + "```"

        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "koffee_request_modal",
                "title": {"type": "plain_text", "text": "Place An Order"},
                "submit": {"type": "plain_text", "text": "Submit Drop"},
                "close": {"type": "plain_text", "text": "Nevermind"},
                "private_metadata": json.dumps({
                    "mode": mode,
                    "location": location,
                    "runner_id": runner_id
                }),
                "blocks": blocks
            }
        )
        return
    print(f"📦 private_metadata raw: {body['view'].get('private_metadata', '')}")
    if not runner_id:
        print("🛠 DEBUG: Order submission path triggered (runner_id not provided).")
        print("🛠 DEBUG: Initialized order_data =", order_data)
        # Initialize order_data and extract modal state values

        order_data["order_id"] = order_id
        order_data["status"] = "ordered"
        order_data["time_ordered"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        drink = values["drink_category"]["input"]["selected_option"]["value"]
        drink_detail = values["drink_detail"]["input"]["value"]
        notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and isinstance(values["notes"]["input"]["value"], str) else ""
        gifted_id = values["gift_to"]["input"].get("selected_user") if "gift_to" in values and "input" in values["gift_to"] else None

        if drink == "water":
            karma_cost = 1
        elif drink in ["tea", "drip"]:
            karma_cost = 2
        else:
            karma_cost = 3

        drink = drink_detail.strip()

        if not parent_ts:
            placeholder = client.chat_postMessage(
                channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
                text="...",  # Temporary placeholder to be overwritten
                blocks=[]
            )
            ts = placeholder["ts"]
            channel = placeholder["channel"]
            order_ts = source_order_id if source_order_id else str(datetime.datetime.now().timestamp())
            order_channel = channel
            print(f"🧪 [DEBUG] Assigned order_ts = {order_ts}")
            print(f"🧪 [DEBUG] Assigned order_channel = {order_channel}")
        else:
            order_ts = parent_ts
            order_channel = channel_id
            print(f"🔁 Reusing existing Slack message: order_ts={order_ts}, order_channel={order_channel}")
            print(f"🧪 [DEBUG] Assigned order_ts = {order_ts}")
            print(f"🧪 [DEBUG] Assigned order_channel = {order_channel}")

        order_extras[order_ts] = {}
        order_extras[order_ts]["active"] = True
        order_extras[order_ts]["status"] = "ordered"
        order_extras[order_ts]["requester_real_name"] = order_data.get("requester_real_name", "")
        order_extras[order_ts]["recipient_real_name"] = order_data.get("recipient_real_name", "")
        order_extras[order_ts]["drink"] = drink
        order_extras[order_ts]["location"] = location
        order_extras[order_ts]["notes"] = notes
        order_extras[order_ts]["karma_cost"] = karma_cost
        import threading
        countdown_timers[order_ts] = karma_cost  # or 10 if that's the default
        order_extras[order_ts]["status"] = "ordered"
        order_extras[order_ts]["active"] = True
        requester_real_name = order_data.get("requester_real_name", user_id)
        order_extras[order_ts]["requester_real_name"] = requester_real_name
        recipient_real_name = order_data.get("recipient_real_name", gifted_id or user_id)
        order_extras[order_ts]["recipient_real_name"] = recipient_real_name
        order_extras[order_ts]["drink"] = drink
        order_extras[order_ts]["location"] = location
        order_extras[order_ts]["notes"] = notes
        order_extras[order_ts]["claimed_by"] = ""
        order_extras[order_ts]["runner_real_name"] = ""
        order_extras[order_ts]["delivered_by"] = ""
        order_extras[order_ts]["remaining_minutes"] = 10

        threading.Timer(60, update_countdown, args=(
            client, 9, order_ts, order_channel,
            user_id, gifted_id, drink, location,
            notes, karma_cost
        )).start()

        print(f"🧭 Countdown scheduled for /order — ts: {order_ts}, channel: {order_channel}, user_id: {user_id}")
        print(f"🧭 Initial extras: {order_extras.get(order_ts)}")
        
        order_data["location"] = location or "UNKNOWN"
        order_data["notes"] = notes or "NONE"
        order_data["drink"] = drink or "UNKNOWN"
        order_data["karma_cost"] = karma_cost
        order_data["requester_id"] = user_id
        order_data["requester_real_name"] = client.users_info(user=user_id)["user"]["real_name"]
        order_data["recipient_id"] = gifted_id if gifted_id else user_id
        order_data["recipient_real_name"] = order_data["requester_real_name"]
        order_data["status"] = "ordered"
        order_data["time_ordered"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        print(f"🧪 [DEBUG] Committed order_id: {order_id}")
        print(f"🧪 [DEBUG] Should update ts = {order_ts}, channel = {order_channel}")
        print(f"🧪 [DEBUG] Logging order_data: {json.dumps(order_data, indent=2)}")
        blocks = format_order_message(order_data)
        safe_chat_update(client, order_channel, order_ts, "Order update: Submitted", blocks)

        try:
            user_info = client.users_info(user=user_id)
            real_name = user_info["user"]["real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch real name for requester:", e)
            real_name = f"<@{user_id}>"

        # order_data = {
        #     "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #     "initiated_by": "requester",
        #     "requester_id": user_id,
        #     "requester_real_name": real_name,
        #     "runner_id": "",
        #     "runner_name": "",
        #     "recipient_id": gifted_id if gifted_id else user_id,
        #     "recipient_real_name": "",
        #     "drink": drink.strip(),
        #     "location": location,
        #     "notes": notes,
        #     "karma_cost": karma_cost,
        #     "status": "ordered",
        #     "bonus_multiplier": "",
        #     "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #     "time_claimed": "",
        #     "time_delivered": "",
        #     "order_id": order_ts
        # }

        order_data.update({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "initiated_by": "requester",
            "requester_id": user_id,
            "requester_real_name": real_name,
            "runner_id": "",
            "runner_name": "",
            "recipient_id": gifted_id if gifted_id else user_id,
            "recipient_real_name": "",
            "drink": drink.strip(),
            "location": location,
            "notes": notes,
            "karma_cost": karma_cost,
            "bonus_multiplier": "",
            "time_claimed": "",
            "time_delivered": ""
        })

        print("🛠 DEBUG: Final order_data for logging:", order_data)
        print(f"📝 [DEBUG] Final order_data payload: {json.dumps(order_data, indent=2)}")
        
        if order_data.get("status") == "claimed":
            print("ℹ️ Skipping log_order_to_sheet for claimed status.")
            from sheet import update_order_status
            update_order_status(
                order_id=parent_ts,
                status="claimed",
                claimed_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                requester_name=order_data.get("requester_real_name", ""),
                recipient_name=order_data.get("recipient_real_name", ""),
                order_data=order_data
            )
            return

        from sheet import log_order_to_sheet
        print(f"🧪 [DEBUG] Committed order_id: {order_data['order_id']}")
        print(f"🧪 [DEBUG] Should update ts = {order_ts}, channel = {order_channel}")
        print(f"🧪 [DEBUG] Logging order_data: {json.dumps(order_data, indent=2)}")
        if order_data.get("status") != "claimed":
            log_order_to_sheet(order_data)
        else:
            print("ℹ️ [DEBUG] Skipped log_order_to_sheet because status is 'claimed'")

        
    user_id = body["user"]["id"]
    drink_value = values["drink_category"]["input"]["selected_option"]["value"]
    if drink_value == "espresso":
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="Ø Espresso orders are temporarily unavailable — the machine's down. Choose something else while we fix it up."
        )
        print("❌ Espresso order blocked due to machine downtime.")
        print(f"⚠️ BLOCKED ORDER — {user_id} tried to order espresso while machine is down.")
        print("❌ Exiting early due to espresso block")
        return
    drink_detail = values["drink_detail"]["input"]["value"]
    drink_map = {
        "water": 1,
        "drip": 2,
        "tea": 2,
        "espresso": 3
    }
    karma_cost = drink_map[drink_value]
    drink = drink_detail
    location = ""
    if "location" in values:
        location_block = values["location"]
        if "location_select" in location_block and "selected_option" in location_block["location_select"]:
            location = location_block["location_select"]["selected_option"]["value"]
    notes = values["notes"]["input"]["value"] if "notes" in values and "input" in values["notes"] and values["notes"]["input"]["value"] else ""
    notes = notes[:30]
    gifted_id = None
    if "gift_to" in values and "input" in values["gift_to"]:
        gifted_id = values["gift_to"]["input"].get("selected_user", None)
    
    

    points = get_karma(user_id)
    if points < karma_cost:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="⊘ You do not have enough karma to place this order. Deliver drinks to earn more."
        )
        return
    order_data = {
        "order_id": "",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initiated_by": "runner" if runner_id else "requester",
        "requester_id": user_id,
        "requester_real_name": "",
        "runner_id": runner_id,
        "runner_name": "",
        "runner_real_name": "",
        "recipient_id": gifted_id if gifted_id else user_id,
        "recipient_real_name": "",
        "drink": drink,
        "location": location,
        "notes": notes,
        "karma_cost": karma_cost,
        "status": "ordered",
        "bonus_multiplier": "",
        "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_claimed": "",
        "time_delivered": "",
        "remaining_minutes": 10
    }
    from slack_sdk.web import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)

    try:
        requester_info = slack_client.users_info(user=order_data["requester_id"])
        order_data["requester_real_name"] = requester_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch requester real name:", e)

    try:
        if order_data["recipient_id"]:
            recipient_info = slack_client.users_info(user=order_data["recipient_id"])
            order_data["recipient_real_name"] = recipient_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch recipient real name:", e)

    try:
        if order_data["runner_id"]:
            runner_info = slack_client.users_info(user=order_data["runner_id"])
            order_data["runner_real_name"] = runner_info["user"]["real_name"]
            order_data["runner_name"] = runner_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch runner real name:", e)
    print(f"🏃 runner_id: {runner_id}")

    context_line = random.choice([
        "*☕ Caffeine + Chaos* — IDE☕O forever.",
        "*🥤 Caffeinate and dominate.*",
        "*// Brewed + Brutal //*",
        "*Wake. Rage. Repeat.* ☕",
        "*☠️ No cream. No sugar. Just rage.*",
        "*Deadlines & Drip* ☕",
        "*⛓️ Serve or be served.*",
        "*⚠️ Brew responsibly — or don’t.*",
        "*👀 The grind sees all.*",
        "*🥀 Steam. Spite. Salvation.*",
        "*🖤 Emo espresso drop incoming.*",
        "*🔥 Orders up. No mercy.*",
        "*😤 Grind now. Cry later.*",
        "*💀 Live by the brew. Die by the brew.*",
        "*📦 Drop incoming — stay sharp.*",
        "*😎 Zero chill. Full drip.*",
        "*🥵 Brewed under pressure.*",
        "*🚀 Boosted by beans.*",
        "*💼 All business. All brew.*",
        "*🎯 Hit the mark. Hit the café.*"
    ])
    
    # For display only: use uppercase formatting for message output.
    if 'runner_offer_metadata' not in globals():
        print("⚠️ runner_offer_metadata not defined — initializing.")
        runner_offer_metadata = {}
    if order_data["runner_id"]:
        print(f"🔁 Reached fallback block — checking if runner_id exists in runner_offer_metadata")
        print(f"🧪 runner_offer_metadata keys: {list(runner_offer_metadata.keys())}")
        if (not order_ts or not order_channel) and runner_offer_metadata.get(order_data["runner_id"]):
            print("🧪 Fallback metadata found. Attempting to restore ts and channel...")
            fallback_metadata = runner_offer_metadata[order_data["runner_id"]]
            if not order_ts:
                order_ts = fallback_metadata.get("ts", "")
        if not order_channel:
            order_channel = fallback_metadata.get("channel", "")
        # Fallback results already logged above.
        if not order_ts or not order_channel:
            print("🚨 Could not recover original /ready message from fallback metadata.")
            print(f"⚠️ Missing order_ts or order_channel for runner-initiated order — fallback failed.")
    # Post-fallback values already logged above.
    # Fetch runner and requester real names and format order message before fallback check
    from slack_sdk.web import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)
    try:
        runner_info = slack_client.users_info(user=order_data["runner_id"])
        order_data["runner_name"] = runner_info["user"]["real_name"]
        order_data["runner_real_name"] = runner_info["user"]["real_name"]
        order_data["claimed_by"] = order_data["runner_real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch runner real name:", e)
    try:
        requester_info = slack_client.users_info(user=user_id)
        order_data["requester_real_name"] = requester_info["user"]["real_name"]
        order_data["claimed_by"] = order_data["runner_real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch requester real name for runner-initiated order:", e)

    # Ensure formatted_blocks is initialized before fallback check
    formatted_blocks = format_order_message(order_data)

    if not order_ts or not order_channel:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="‡ Modal submitted, but we couldn’t find the original `/runner` message to update."
        )
        print("🚨 [MODAL SUBMIT] Fallback failed — cannot update message.")
        return

    order_data["requester_real_name"] = requester_info["user"]["real_name"]
    order_data["recipient_real_name"] = recipient_info["user"]["real_name"]

    if order_ts not in order_extras:
        order_extras[order_ts] = {}
    order_extras[order_ts]["requester_real_name"] = order_data["requester_real_name"]
    order_extras[order_ts]["recipient_real_name"] = order_data["recipient_real_name"]
    order_extras[order_ts]["runner_real_name"] = order_data["runner_real_name"]
    
    if gifted_id:
        try:
            recipient_info = slack_client.users_info(user=gifted_id)
            order_data["recipient_real_name"] = recipient_info["user"]["real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch recipient real name for runner-initiated order:", e)
    else:
        order_data["recipient_real_name"] = order_data["requester_real_name"]

        # Prevent double-claiming runner offers unless cleared
        existing_claim = runner_offer_claims.get(order_data["runner_id"])
        now = datetime.datetime.now()
        if existing_claim:
            claim_info = existing_claim
            import json
            if isinstance(claim_info, str):
                claim_info = json.loads(claim_info)
            claim_time = claim_info.get("timestamp")
            is_expired = (now - claim_time).total_seconds() > 900  # 15 minutes
            is_delivered = claim_info.get("delivered", False)

            if not is_expired and not is_delivered:
                client.chat_postEphemeral(
                    channel=user_id,
                    user=user_id,
                    text="‡ TOO LATE. This runner is already bound to another order."
                )
                return

        # Set new claim
        runner_offer_claims[order_data["runner_id"]] = {
            "user_id": user_id,
            "timestamp": now,
            "delivered": False
        }

        # Schedule fallback cleanup after 15 minutes
        import threading
        def clear_runner_offer():
            current = runner_offer_claims.get(order_data["runner_id"])
            if current and current["user_id"] == user_id and not current["delivered"]:
                del runner_offer_claims[order_data["runner_id"]]

        threading.Timer(900, clear_runner_offer).start()

        runner_offer_claims[order_data["runner_id"]] = user_id

        # Schedule removal after 15 minutes as fallback
        import threading
        def clear_runner_offer():
            current = runner_offer_claims.get(order_data["runner_id"])
            if current == user_id:
                del runner_offer_claims[order_data["runner_id"]]

        threading.Timer(900, clear_runner_offer).start()


    try:
        user_info = slack_client.users_info(user=user_id)
        order_data["requester_real_name"] = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch requester real name:", e)
    # Ensure requester_real_name is added to order_extras early for countdown updates
    if order_ts not in order_extras:
        order_extras[order_ts] = {}
    order_extras[order_ts]["order_id"] = order_ts
    order_extras[order_ts]["requester_real_name"] = order_data["requester_real_name"]

    if gifted_id:
        try:
            recipient_info = slack_client.users_info(user=gifted_id)
            order_data["recipient_real_name"] = recipient_info["user"]["real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch recipient real name:", e)
    else:
        order_data["recipient_real_name"] = order_data["requester_real_name"]
    
    if order_data["runner_id"]:
        order_data["claimed_by"] = order_data["runner_real_name"]
        order_data["status"] = "claimed"
        formatted_blocks = format_order_message(order_data)
        print(f"🧪 About to call chat_update with channel={order_channel} and ts={order_ts}")
        print(f"📣 Debug: channel for chat_update is {order_channel}")
        if not order_channel:
            print("⚠️ Missing order_channel — falling back to default channel.")
            order_channel = os.environ.get("KOFFEE_KARMA_CHANNEL")
        print(f"⚙️ order_ts: {order_ts}")
        print(f"⚙️ order_channel: {order_channel}")
        print(f"📣 Attempting to update message {order_ts} in channel {order_channel}")
        print(f"🧾 Blocks: {formatted_blocks}")
        if not formatted_blocks:
            print("🚫 No formatted_blocks returned from format_order_message")
            return
        if not order_ts or not order_channel:
            print(f"🚨 Missing fallback data — order_ts: {order_ts}, order_channel: {order_channel}")
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
            text="‡ Modal submitted, but we couldn’t find the original `/runner` message to update."
            )
            return
        print(f"🧪 [DEBUG] Committed order_id: {order_data['order_id']}")
        print(f"🧪 [DEBUG] Should update ts = {order_ts}, channel = {order_channel}")
        print(f"🧪 [DEBUG] Logging order_data: {json.dumps(order_data, indent=2)}")
        safe_chat_update(client, order_channel, order_ts, "New Koffee Karma order posted", formatted_blocks)
        log_order_to_sheet(order_data)
        return
    else:
        formatted_blocks = format_order_message(order_data)
        print(f"🧪 About to call chat_update with channel={order_channel} and ts={order_ts}")
        print(f"📣 Debug: channel for chat_update is {order_channel}")
        if not order_channel:
            print("⚠️ Missing order_channel — falling back to default channel.")
            order_channel = os.environ.get("KOFFEE_KARMA_CHANNEL")
        print(f"⚙️ order_ts: {order_ts}")
        print(f"⚙️ order_channel: {order_channel}")
        print(f"📣 Attempting to update message {order_ts} in channel {order_channel}")
        print(f"🧾 Blocks: {formatted_blocks}")
        if not formatted_blocks:
            print("🚫 No formatted_blocks returned from format_order_message")
            return
        if not order_ts or not order_channel:
            print(f"🚨 Missing fallback data — order_ts: {order_ts}, order_channel: {order_channel}")
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="‡ Modal submitted, but we couldn’t find the original `/runner` message to update."
            )
            return
        print(f"🧪 [DEBUG] Committed order_id: {order_data['order_id']}")
        print(f"🧪 [DEBUG] Should update ts = {order_ts}, channel = {order_channel}")
        print(f"🧪 [DEBUG] Logging order_data: {json.dumps(order_data, indent=2)}")
        safe_chat_update(client, order_channel, order_ts, "New Koffee Karma order posted", formatted_blocks)
@app.command("/deliver")
def handle_ready_command(ack, body, client):
    ack()
    user_id = body["user_id"]
    cap_options = [
        {"text": {"type": "plain_text", "text": "Water"}, "value": "water"},
        {"text": {"type": "plain_text", "text": "Tea"}, "value": "tea"},
        {"text": {"type": "plain_text", "text": "Drip Coffee"}, "value": "drip_coffee"},
        {"text": {"type": "plain_text", "text": "Espresso Drinks"}, "value": "espresso_drinks"}
    ]
    runner_capabilities = get_runner_capabilities(user_id)
    raw_caps = runner_capabilities.get("Capabilities", [])
    if not isinstance(raw_caps, list):
        try:
            raw_caps = json.loads(raw_caps)
        except Exception:
            raw_caps = []
    valid_cap_values = {opt["value"] for opt in cap_options}
    saved_caps = [cap for cap in raw_caps if cap in valid_cap_values]
    initial_options = []
    for opt in cap_options:
        if opt["value"] in saved_caps:
            initial_options.append(opt)
    real_name = runner_capabilities.get("Name", f"<@{user_id}>")
    # Removed redundant capabilities reassignment block since saved_caps and initial_options are used.
    pretty_caps = {
        "water": "Water",
        "drip_coffee": "Drip Coffee",
        "espresso_drinks": "Espresso Drinks",
        "tea": "Tea"
    }
    can_make_str = ", ".join([pretty_caps.get(cap, cap.upper()) for cap in saved_caps]) or "NONE"
    user_id = body["user_id"]
    location = ""
    notes = ""
    karma_cost = ""
    # Replacing static block with countdown-rendered ready message
    # posted_ready = client.chat_postMessage(
    #     channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
    #     text=f"🖐️ {real_name.upper()} is *on the clock* as a runner.\n*⏳ 10 minutes left to send them an order.*",
    #     blocks=[
    #         {
    #             "type": "section",
    #             "block_id": "runner_text_block",
    #             "text": {
    #                 "type": "mrkdwn",
    #                 "text": f"```+----------------------------------------+\n|       DRINK RUNNER AVAILABLE          |\n+----------------------------------------+\n| RUNNER: {real_name.upper():<32}|\n| STATUS: READY TO DELIVER               |\n| CAN MAKE: {can_make_str:<32}|\n+----------------------------------------+\n| TIME LEFT ON SHIFT: 10 MINUTES         |\n|         [██████░░░░░░░░░░░░░░]         |\n|  ------------------------------------  |\n|   ↓ CLICK BELOW TO PLACE AN ORDER ↓    |\n|  ------------------------------------  |\n+----------------------------------------+```"
    #             }
    #         },
    #         {
    #             "type": "actions",
    #             "block_id": "runner_buttons",
    #             "elements": [
    #                 {
    #                     "type": "button",
    #                     "action_id": "open_order_modal_for_runner",
    #                     "text": {
    #                         "type": "plain_text",
    #                         "text": "ORDER NOW",
    #                         "emoji": True
    #                     },
    #                     "value": json.dumps({"runner_id": user_id})
    #                 },
    #                 {
    #                     "type": "button",
    #                     "action_id": "cancel_ready_offer",
    #                     "text": {
    #                         "type": "plain_text",
    #                         "text": "CANCEL",
    #                         "emoji": True
    #                     },
    #                     "style": "danger",
    #                     "value": user_id
    #                 }
    #             ]
    #         }
    #     ]
    # )
    # order_ts = posted_ready["ts"]
    # order_channel = posted_ready["channel"]
    # global runner_offer_metadata
    # if 'runner_offer_metadata' not in globals():
    #     print("⚠️ runner_offer_metadata not defined — initializing.")
    #     runner_offer_metadata = {}
    # runner_offer_metadata[user_id] = {
    #     "ts": order_ts,
    #     "channel": order_channel
    # }
    # runner_offer_claims[user_id] = None  # Mark this runner as available and unclaimed
    # print(f"🆕 Runner offer posted by {user_id} — awaiting match.")
    # drink = ""
    # location = ""
    # notes = ""
    # karma_cost = ""
 
    
    
    # Log order with "time_ordered" as the timestamp key
    from sheet import log_order_to_sheet
    gifted_id = None
    order_data = {
        "order_id": "",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "requester_id": user_id,
        "requester_real_name": "",
        "runner_id": "",
        "runner_real_name": "",
        "recipient_id": gifted_id if gifted_id else user_id,
        "recipient_real_name": "",
        "drink": "",
        "location": "",
        "notes": "",
        "karma_cost": "",
        "status": "ordered",
        "bonus_multiplier": "",
        "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_claimed": "",
        "time_delivered": ""
    }
    # log_order_to_sheet(order_data)
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "runner_settings_modal",
            "title": {"type": "plain_text", "text": "Offer to Deliver"},
            "submit": {"type": "plain_text", "text": "Raise Hand"},
            "close": {"type": "plain_text", "text": "Just Kidding"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "time_available",
                    "label": {"type": "plain_text", "text": "How much time do you have?"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
                        "initial_option": {
                            "text": {"type": "plain_text", "text": "10 minutes"},
                            "value": "10"
                        },
                        "options": [
                            {"text": {"type": "plain_text", "text": "5 minutes"}, "value": "5"},
                            {"text": {"type": "plain_text", "text": "10 minutes"}, "value": "10"},
                            {"text": {"type": "plain_text", "text": "15 minutes"}, "value": "15"}
                        ]
                    }
                },
                {
                    "type": "input",
                    "block_id": "capabilities",
                    "label": {"type": "plain_text", "text": "What drinks can you make?"},
                    "element": {
                        "type": "checkboxes",
                        "action_id": "input",
                        "initial_options": initial_options,
                        "options": cap_options
                    }
                }
            ]
        }
    )

    # Start countdown timer for order expiration
    import threading
    def cancel_unclaimed_order(order_ts, order_channel):
        try:
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if current_message["messages"]:
                current_text = current_message["messages"][0].get("text", "").lower()
                if any(phrase.lower() in current_text for phrase in ["Canceled", "Claimed", "Order canceled by", "❌ Order canceled", "DELIVERED", "✅ *DROP COMPLETED*"]):
                    return  # Skip if canceled, claimed, or delivered
            else:
                print(f"⚠️ No message found for order {order_ts}, skipping expiration.")
                return
            safe_chat_update(
                client,
                order_channel,
                order_ts,
                "Drop EXPIRED. No claimant arose.",
                [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "Drop EXPIRED. No claimant arose."}
                    }
                ]
            )
            import re
            match = re.search(r"from <@([A-Z0-9]+)>", current_text)
            if match:
                user_id = match.group(1)
            else:
                user_id = None

            # Refund Karma on expiration
            if "Water" in current_text:
                refund_amount = 1
            elif "Drip" in current_text:
                refund_amount = 2
            elif "Espresso" in current_text:
                refund_amount = 3
            else:
                refund_amount = 1  # Fallback
 
            if user_id:
                add_karma(user_id, refund_amount)
                print(f"📬 Sending DM to user_id: {user_id} with message: 🌀 Your order expired. {refund_amount} Karma refunded. Balance restored.")
                client.chat_postMessage(
                    channel=user_id,
                    text=f"☽ Order EXPIRED. +{refund_amount} karma returned to your balance."
                )
            from sheet import update_order_status
            update_order_status(order_ts, status="expired")
            if order_ts in order_extras:
                order_extras[order_ts]["active"] = False
                gif_ts = order_extras[order_ts].get("gif_ts")
                if gif_ts:
                    try:
                        client.chat_delete(channel=order_channel, ts=gif_ts)
                    except Exception as e:
                        print("⚠️ Failed to delete gif message:", e)
                del order_extras[order_ts]
        except Exception as e:
            print("⚠️ Failed to expire message:", e)

    print("⏰ Timer started for cancel_unclaimed_order (600s)")
    order_ts = ""
    order_channel = ""
    threading.Timer(600, cancel_unclaimed_order, args=(order_ts, order_channel)).start()  # 10 minutes
    # Reminder ping halfway through if still unclaimed
    def reminder_ping(order_ts, order_channel):
        try:
            if not order_channel or not order_ts:
                print("⚠️ Missing order_channel or order_ts; skipping reminder_ping")
                return
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if order_extras.get(order_ts, {}).get("claimed", False):
                print(f"🔕 Skipping reminder — order {order_ts} already claimed.")
                return
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if any(phrase in msg_text for phrase in ["Claimed by", "Expired", "Canceled", "Order canceled by"]):
                    return  # Skip reminder if already handled

            # Insert the reminder block without collapsing formatting
            current_blocks = current_message["messages"][0].get("blocks", [])

            reminder_block = {
                "type": "section",
                "block_id": "reminder_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "*⚠️ STILL UNCLAIMED — CLOCK'S TICKING ⏳*"
                }
            }

            updated_blocks = current_blocks + [reminder_block]

            # Commented out previous update that replaced the whole message text
            # order_extras[order_ts]["reminder_added"] = True

            safe_chat_update(
                client,
                order_channel,
                order_ts,
                msg_text,
                updated_blocks
            )
        except Exception as e:
            print("⚠️ Reminder ping failed:", e)

    print("🔔 Timer started for reminder_ping (300s)")
    threading.Timer(300, reminder_ping, args=(order_ts, order_channel)).start()  # 5-minute reminder

@app.view("runner_settings_modal")
def handle_runner_settings_modal(ack, body, client):
    ack()
    import os
    print("📥 /deliver modal submission received")
    from sheet import log_order_to_sheet
    import datetime

    global runner_offer_metadata
    if 'runner_offer_metadata' not in globals():
        runner_offer_metadata = {}
    
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
    selected = []
    if "capabilities" in values and "input" in values["capabilities"]:
        selected = [opt["value"] for opt in values["capabilities"]["input"].get("selected_options", [])]
    try:
        from slack_sdk import WebClient
        slack_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_client = WebClient(token=slack_token)
        user_info = slack_client.users_info(user=user_id)
        real_name = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch user real name for settings save:", e)
        real_name = f"<@{user_id}>"
    from sheet import save_runner_capabilities
    save_runner_capabilities(user_id, real_name, selected)

    placeholder = client.chat_postMessage(
        channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
        text="...",
        blocks=[]
    )
    ts = placeholder["ts"]
    channel = placeholder["channel"]
    order_ts = ts
    order_channel = channel

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    order_data = {
        "order_id": order_ts,
        "timestamp": timestamp,
        "initiated_by": "runner",
        "requester_id": "",
        "requester_real_name": "",
        "runner_id": user_id,
        "runner_name": real_name,
        "recipient_id": "",
        "recipient_real_name": "",
        "drink": "",
        "location": "",
        "notes": "",
        "karma_cost": "",
        "status": "offered",
        "bonus_multiplier": "",
        "time_ordered": timestamp,
        "time_claimed": "",
        "time_delivered": ""
    }
    log_order_to_sheet(order_data)

    selected = []
    if "capabilities" in values and "input" in values["capabilities"]:
        selected = [opt["value"] for opt in values["capabilities"]["input"].get("selected_options", [])]
    previous_caps_data = get_runner_capabilities(user_id)
    previous_caps = set(previous_caps_data.get("Capabilities", []))
    current_caps = set(selected)
    caps_changed = previous_caps != current_caps
 
    selected_time = 10  # default
    if "time_available" in values and "input" in values["time_available"]:
        selected_time = int(values["time_available"]["input"].get("selected_option", {}).get("value", 10))
 
    from sheet import save_runner_capabilities
    from slack_sdk import WebClient
    import os
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)
    try:
        user_info = slack_client.users_info(user=user_id)
        real_name = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch user real name for settings save:", e)
        real_name = f"<@{user_id}>"
 
 
    # post terminal message with the selected time and capabilities
    pretty_caps = {
        "water": "Water",
        "drip_coffee": "Drip Coffee",
        "espresso_drinks": "Espresso Drinks",
        "tea": "Tea"
    }
    can_make_str = ", ".join([pretty_caps.get(cap, cap.upper()) for cap in selected]) or "NONE"
    all_options = ["water", "tea", "drip_coffee", "espresso_drinks"]
    cannot_make = [pretty_caps[c] for c in all_options if c not in selected]
    cannot_make_str = ", ".join(cannot_make) if cannot_make else "NONE"
    total_blocks = 20
    filled_blocks = total_blocks
    progress_bar = "[" + ("█" * filled_blocks) + ("░" * (total_blocks - filled_blocks)) + "]"
 
    text = (
        "```+----------------------------------------+\n"
        + "|       𐂀 DRINK RUNNER AVAILABLE 𐂀       |\n"
        + "+----------------------------------------+\n"
        + "\n".join(box_line(label="RUNNER", value=real_name.upper(), width=42)) + "\n"
        + "\n".join(box_line(label="CAN MAKE", value=can_make_str, width=42)) + "\n"
        + "\n".join(box_line(label="CAN'T MAKE", value=cannot_make_str, width=42)) + "\n"
        + "+----------------------------------------+\n"
        + "\n".join(box_line(text=f"TIME LEFT ON SHIFT: {selected_time} MINUTES", width=42, align="center")) + "\n"
        + "\n".join(box_line(text=progress_bar, width=42, align="center")) + "\n"
        + "\n".join(box_line(text="------------------------------------", width=42, align="center")) + "\n"
        + "\n".join(box_line(text="↓ CLICK BELOW TO PLACE AN ORDER ↓", width=42, align="center")) + "\n"
        + "\n".join(box_line(text="------------------------------------", width=42, align="center")) + "\n"
        + "+----------------------------------------+```"
    )
    msg = "✷ Your delivery offer is now live."
    if caps_changed:
        msg = "✷ Your drink-making capabilities have been saved and your delivery offer is now live."
    
    msg = "✅ Your delivery offer is now live."
    client.chat_postMessage(channel=user_id, text=msg)

    blocks = [
        {
            "type": "section",
            "block_id": "runner_text_block",
            "text": {
                "type": "mrkdwn",
                "text": text
            }
        },
        {
            "type": "actions",
            "block_id": "runner_buttons",
            "elements": [
                {
                    "type": "button",
                    "action_id": "open_order_modal_for_runner",
                    "text": {
                        "type": "plain_text",
                        "text": "ORDER NOW",
                        "emoji": True
                    },
                    "value": json.dumps({"runner_id": user_id, "source_order_id": order_ts})
                },
                {
                    "type": "button",
                    "action_id": "cancel_ready_offer",
                    "text": {
                        "type": "plain_text",
                        "text": "CANCEL",
                        "emoji": True
                    },
                    "style": "danger",
                    "value": user_id
                }
            ]
        }
    ]

    safe_chat_update(client, order_channel, order_ts, text, blocks)

    # Then set the metadata
    if 'runner_offer_metadata' not in globals():
        runner_offer_metadata = {}
    runner_offer_metadata[user_id] = {
        "ts": order_ts,
        "channel": order_channel
    }

    import threading
    threading.Timer(
        60,
        update_ready_countdown,
        args=(client, selected_time - 1, order_ts, order_channel, user_id, selected_time)
    ).start()

@app.action("open_order_modal_for_runner")
def handle_open_order_modal_for_runner(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]
    try:
        payload = json.loads(body["actions"][0]["value"])
        runner_id = payload.get("runner_id", "")
        source_order_id = payload.get("source_order_id", "")
    except Exception as e:
        print("⚠️ Failed to parse modal value payload:", e)
        runner_id = user_id
        source_order_id = ""

    selected_location = last_selected_location.get(user_id, "")
    modal = build_order_modal(trigger_id, runner_id=runner_id, selected_location=selected_location, source_order_id=source_order_id)
    client.views_open(trigger_id=trigger_id, view=modal["view"])

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=10000)