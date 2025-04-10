from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import schedule
import time
import random
import requests
import os
import json
import datetime
import copy
import re
import csv
from sheet import get_runner_capabilities

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
        "| Use the dropdown above   |",
        "| to pick your delivery    |",
        "| spot in the studio. The  |",
        "| ✗ in the map shows where |",
        "| your drink will arrive.  |",
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



from sheet import add_karma, get_karma, get_leaderboard, ensure_user, deduct_karma, get_runner_capabilities
 
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

def box_line(text="", label=None, value=None, width=40, align="left"):
    """
    Unified function for formatting boxed lines.
    Handles:
    - Plain text (centered/left/right)
    - Label: Value with multi-line wrapping
    Always outputs lines that are exactly `width` characters wide.
    """
    lines = []
    border_space = width - 3  # for '| ' and '|'
    label_field = 13

    if label is None and value is None:
        text = text.upper()
        if align == "center":
            content = text.center(border_space)
        elif align == "right":
            content = text.rjust(border_space)
        else:
            content = text.ljust(border_space)
        return [f"| {content} |"]

    label = label.rstrip(":").upper()
    value = value.upper()
    words = value.split()
    label_prefix = f"{label:<{label_field}}"
    indent = " " * label_field
    current_line = ""

    for word in words:
        if len(current_line + (" " if current_line else "") + word) <= border_space - label_field:
            current_line += (" " if current_line else "") + word
        else:
            if not lines:
                lines.append(f"| {label_prefix}{current_line:<{border_space - label_field}} |")
            else:
                lines.append(f"| {indent}{current_line:<{border_space - label_field}} |")
            current_line = word

    if current_line:
        if not lines:
            lines.append(f"| {label_prefix}{current_line:<{border_space - label_field}} |")
        else:
            lines.append(f"| {indent}{current_line:<{border_space - label_field}} |")

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
        print(f"🗺️ Marking location on map at ({x}, {y}) for {location_name}")
        if 0 <= y < len(map_lines):
            line = list(map_lines[y])
            if 0 <= x < len(line):
                print(f"✍️ Placing '✗' on map at ({x}, {y})")
                line[x] = "✗"
                map_lines[y] = "".join(line)
                print(f"🆗 map_lines[{y}] updated with '✗'")
    return map_lines
 
def format_order_message(order_data):
    print(f"📨 format_order_message called with order_data: {order_data}")
    print(f"🧪 format_order_message FROM: {order_data.get('requester_real_name')} TO: {order_data.get('recipient_real_name')}")
    border_top = "+------------------------------------------------+"
    border_mid = "+------------------------------------------------+"
    border_bot = "+------------------------------------------------+"
    lines = [
        border_top,
        *wrap_line("", "KOFFEE KARMA TERMINAL", width=50),
    ]
    lines.append(border_mid)
    lines.append(f'| DROP ID :     {order_data["order_id"]:<32} |')
    requester_display = order_data.get("requester_real_name") or f"<@{order_data['requester_id']}>"
    recipient_display = order_data.get("recipient_real_name") or f"<@{order_data['recipient_id']}>"
    if order_data.get("requester_id") == order_data.get("recipient_id"):
        recipient_display += " (Self)"
    else:
        recipient_display += " (Gift)"
    lines.append(f'| FROM :        {requester_display.upper():<32} |')
    lines.append(f'| TO :          {recipient_display.upper():<32} |')
    lines.append(f'| DRINK :       {order_data["drink"].upper():<32} |')
    lines.append(f'| LOCATION :    {order_data["location"].upper():<32} |')
    lines.append(f'| NOTES :       {(order_data["notes"] or "NONE").upper():<32} |')
    lines.append(border_mid)
    lines.append(f'| REWARD :      {order_data["karma_cost"]} KARMA{" " * (32 - len(str(order_data["karma_cost"]) + " KARMA"))} |')
    if order_data.get("delivered_by"):
        lines.append(f'| STATUS :      COMPLETED {" " * 22} |')
        lines.append(f'|               DELIVERED BY {order_data["delivered_by"].upper():<19} |')
        lines.append("| ---------------------------------------------- |")
        karma_line = f"+{order_data['bonus_multiplier']} KARMA EARNED — TOTAL: {order_data['runner_karma']}"
        total_width = 46
        left_padding = (total_width - len(karma_line)) // 2
        right_padding = total_width - len(karma_line) - left_padding
        lines.append(f"| {' ' * left_padding}{karma_line}{' ' * right_padding} |")
        lines.append("| ---------------------------------------------- |")
    elif order_data.get("claimed_by"):
        claimed_name = order_data.get("runner_real_name") or order_data.get("claimed_by", "")
        lines.append(f'| STATUS :      CLAIMED BY {claimed_name.upper():<21} |')
        lines.append(f'|               WAITING TO BE DELIVERED          |')
    else:
        total_blocks = 20
        remaining = order_data.get("remaining_minutes", 10)
        filled_blocks = max(0, min(total_blocks, remaining * 2))  # 2 blocks per minute
        empty_blocks = total_blocks - filled_blocks
        progress_bar = "[" + ("█" * filled_blocks) + ("░" * empty_blocks) + "]"
        status_line = f'{order_data.get("remaining_minutes", 10)} MINUTES TO CLAIM'
        lines.append(f'| STATUS :      {status_line:<32} |')
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
        "| /KARMA        CHECK YOUR KARMA                 |",
        "| /LEADERBOARD  TOP KARMA EARNERS                |",
        "| /REDEEM       BONUS KARMA CODES                |",
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
            "value": order_data["order_id"]
        })
    else:
        elements.append({
            "type": "button",
            "action_id": "claim_order",
            "text": {
                "type": "plain_text",
                "text": "CLAIM THIS MISSION",
                "emoji": True
            },
            "value": order_data["order_id"]
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
    import sys
    print("🔥 ENTERED update_countdown()")
    sys.stdout.flush()
    print(f"🔁 Countdown tick for {order_ts} — remaining: {remaining}")
    try:
        print(f"👤 User: {user_id}, Gifted: {gifted_id}")
        print(f"🥤 Drink: {drink}, 📍 Location: {location}, 📝 Notes: {notes}, 💰 Karma Cost: {karma_cost}")

        extras = order_extras.get(order_ts)
        print(f"📦 order_extras for {order_ts}: {extras}")
        sys.stdout.flush()

        if not extras or not extras.get("active", True):
            print(f"⛔ Countdown aborted — order_extras missing or marked inactive for {order_ts}")
            return

        current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
        order_data = {
            "order_id": "",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "requester_id": user_id,
            "requester_real_name": extras.get("requester_real_name", ""),
            "runner_id": "",
            "runner_real_name": "",
            "recipient_id": gifted_id if gifted_id else user_id,
            "recipient_real_name": extras.get("recipient_real_name", ""),
            "drink": drink,
            "location": location,
            "notes": notes,
            "karma_cost": karma_cost,
            "status": "pending",
            "bonus_multiplier": "",
            "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "time_claimed": "",
            "time_delivered": "",
        "remaining_minutes": remaining
        }
        print("🛠️ Calling format_order_message with updated remaining time")
        updated_blocks = format_order_message(order_data)
 
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
        safe_chat_update(client, order_channel, order_ts, "New Koffee Karma order posted", updated_blocks)
        print("✅ Countdown block update pushed to Slack")
        print(f"📣 client.chat_update call completed for order {order_ts}")
 
        if remaining > 1 and extras.get("active", True):
            print(f"🕒 Scheduling next countdown tick — remaining: {remaining - 1}")
            t = threading.Timer(60, update_countdown, args=(
                client, remaining - 1, order_ts, order_channel,
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
    ack()
    user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]
    selected_location = body["actions"][0]["selected_option"]["value"]

    # Rebuild the modal with the new map based on selected location
    modal = build_order_modal(trigger_id)
    for block in modal["view"]["blocks"]:
        if block.get("block_id") == "ascii_map_block":
            from app import build_mini_map, format_full_map_with_legend
            ascii_map = "```" + format_full_map_with_legend(build_mini_map(selected_location)) + "```"
            block["text"]["text"] = ascii_map
        elif block.get("block_id") == "location":
            # Preserve the newly selected value with safe check for accessory key
            if "accessory" in block:
                block["accessory"]["initial_option"] = {
                    "text": {"type": "plain_text", "text": selected_location},
                    "value": selected_location
                }

    client.views_update(
        view_id=body["view"]["id"],
        view=modal["view"]
    )

def update_ready_countdown(client, remaining, ts, channel, user_id, original_total_time):
    from sheet import get_runner_capabilities
    runner_capabilities = get_runner_capabilities(user_id)
    real_name = runner_capabilities.get("Name", f"<@{user_id}>")
    pretty_caps = {
        "water": "WATER",
        "drip_coffee": "DRIP COFFEE",
        "espresso_drinks": "ESPRESSO DRINKS",
        "tea": "TEA"
    }
    saved_caps = runner_capabilities.get("Capabilities", [])
    all_options = ["water", "tea", "drip_coffee", "espresso_drinks"]
    can_make = [pretty_caps[c] for c in saved_caps if c in pretty_caps]
    cannot_make = [pretty_caps[c] for c in all_options if c not in saved_caps]
    can_make_str = ", ".join(can_make) if can_make else "NONE"
    cannot_make_str = ", ".join(cannot_make) if cannot_make else "NONE"
    try:
        if remaining <= 0:
            safe_chat_update(
                client,
                channel,
                ts,
                f"<@{user_id}> is ready to deliver — {remaining} minutes left.",
                []
            )
            return

        total_blocks = 20
        filled_blocks = round((remaining / original_total_time) * total_blocks)
        empty_blocks = total_blocks - filled_blocks
        progress_bar = "[" + ("█" * filled_blocks) + ("░" * empty_blocks) + "]"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "```"
                        + "+----------------------------------------+\n"
                        + "|         DRINK RUNNER AVAILABLE         |\n"
                        + "+----------------------------------------+\n"
                        + "\n".join(box_line(label="Runner", value=real_name.upper(), width=40)) + "\n"
                        + "\n".join(box_line(label="CAN MAKE:", value=can_make_str, width=40)) + "\n"
                        + "\n".join(box_line(label="CAN'T MAKE:", value=cannot_make_str, width=40)) + "\n"
                        + "+----------------------------------------+\n"
                        + "\n".join(box_line(text=f"TIME LEFT ON SHIFT: {remaining} MINUTES", width=40, align="center")) + "\n"
                        + "\n".join(box_line(text=progress_bar, width=40, align="center")) + "\n"
                        + "\n".join(box_line(text="------------------------------------", width=40, align="center")) + "\n"
                        + "\n".join(box_line(text="↓ CLICK BELOW TO PLACE AN ORDER ↓", width=40, align="center")) + "\n"
                        + "\n".join(box_line(text="------------------------------------", width=40, align="center")) + "\n"
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
                        "value": json.dumps({"runner_id": user_id})
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
            f"<@{user_id}> is ready to deliver — {remaining} minutes left.",
            blocks
        )

        if remaining > 1:
            import threading
            threading.Timer(60, update_ready_countdown, args=(client, remaining - 1, ts, channel, user_id, original_total_time)).start()
    except Exception as e:
        print("⚠️ Failed to update /ready countdown:", e)

from flask import jsonify

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

def build_order_modal(trigger_id, runner_id=""):
    return {
        "trigger_id": trigger_id,
        "view": {
            "type": "modal",
            "callback_id": "koffee_request_modal",
            "title": {"type": "plain_text", "text": "Place Your Order"},
            "submit": {"type": "plain_text", "text": "Drop It"},
            "close": {"type": "plain_text", "text": "Nevermind"},
            "private_metadata": runner_id,
            "blocks": [
                {
                    "type": "input",
                    "block_id": "drink_category",
                    "label": {"type": "plain_text", "text": "Choose your drink category"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
                        "placeholder": {"type": "plain_text", "text": "Pick your poison"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Water (still/sparkling) — 1 Karma"},
                                "value": "water"
                            },
                            {
                                "text": {"type": "plain_text", "text": "Drip Coffee / Tea — 2 Karma"},
                                "value": "drip"
                            },
                            {
                                "text": {"type": "plain_text", "text": "Espresso Drink (latte, cappuccino) — UNAVAILABLE ☕🚫"},
                                "value": "espresso"
                            }
                        ]
                    }
                },
                {
                    "type": "input",
                    "block_id": "drink_detail",
                    "label": {"type": "plain_text", "text": "What exactly do you want?"},
                    "element": {"type": "plain_text_input", "action_id": "input", "max_length": 30}
                },
                {
                    "type": "section",
                    "block_id": "location",
                    "text": {"type": "mrkdwn", "text": "*Where’s it going?*"},
                    "accessory": {
                        "type": "static_select",
                        "action_id": "location_select",
                        "placeholder": {"type": "plain_text", "text": "Select a location"},
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
                },
                {
                    "type": "section",
                    "block_id": "ascii_map_block",
                    "text": {
                        "type": "mrkdwn",
                        "text": "```" + format_full_map_with_legend(build_mini_map("")) + "```"
                    }
                },
                {
                    "type": "input",
                    "block_id": "gift_to",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Gift to (optional)"},
                    "element": {
                        "type": "users_select",
                        "action_id": "input",
                        "placeholder": {"type": "plain_text", "text": "Choose a coworker"}
                    }
                },
                {
                    "type": "input",
                    "block_id": "notes",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Extra details (if it matters)"},
                    "element": {"type": "plain_text_input", "action_id": "input", "max_length": 30}
                }
            ]
        }
    }

@app.command("/order")
def handle_order(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_order_modal(body["trigger_id"])["view"]
    )

@app.view("koffee_request_modal")
def handle_modal_submission(ack, body, client):
    ack()
    global runner_offer_metadata
    if 'runner_offer_metadata' not in globals():
        print("⚠️ runner_offer_metadata not defined — initializing.")
        runner_offer_metadata = {}
    values = body["view"]["state"]["values"]
    user_id = body["user"]["id"]
    drink_value = values["drink_category"]["input"]["selected_option"]["value"]
    if drink_value == "espresso":
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="🚫 Espresso orders are temporarily unavailable — the machine's down. Choose something else while we fix it up."
        )
        print("❌ Espresso order blocked due to machine downtime.")
        print(f"⚠️ BLOCKED ORDER — {user_id} tried to order espresso while machine is down.")
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
            text="🚫 You don't have enough Koffee Karma to place this order. Deliver drinks to earn more."
        )
        return

    runner_id = body["view"].get("private_metadata", "")
    print(f"🏃 runner_id: {runner_id}")
    order_ts = ""
    order_channel = ""
    if not runner_id:
        posted = client.chat_postMessage(
            channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
            text="New Koffee Karma order posted",
            blocks=[]
        )
        order_ts = posted["ts"]
        order_channel = posted["channel"]
    else:
        # Reuse the existing message posted by /ready
        posted_ready = body.get("view", {}).get("root_view_id")
        order_ts = body.get("container", {}).get("message_ts", "")
        order_channel = body.get("container", {}).get("channel_id", "")
        if not order_channel:
            print("⚠️ order_channel is missing. Trying to fall back from view or other message context.")
            order_channel = os.environ.get("KOFFEE_KARMA_CHANNEL")  # fallback to default channel

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
    full_text = (
        f"💀 NEW DROP // {'FROM <@' + user_id + '> TO <@' + gifted_id + '>' if gifted_id else 'FROM <@' + user_id + '>'}\n"
        f"— — — — — — — — — — — —\n"
        f"DRINK: {drink.upper()}\n"
        f"LOCATION: {location.upper()}\n"
        f"NOTES: {notes.upper() if notes else 'NONE'}\n"
        f"— — — — — — — — — — — —\n"
        f"🎁 {karma_cost} KARMA REWARD"
    )

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
        "status": "pending",
        "bonus_multiplier": "",
        "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_claimed": "",
        "time_delivered": "",
        "remaining_minutes": 10
    }
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
            text="🚨 Modal submitted, but we couldn’t find the original `/ready` message to update. Try again?"
        )
        print("🚨 [MODAL SUBMIT] Fallback failed — cannot update message.")
        return
    if order_ts not in order_extras:
        order_extras[order_ts] = {}
    order_extras[order_ts]["runner_real_name"] = order_data["runner_real_name"]
    
    if gifted_id:
        try:
            recipient_info = slack_client.users_info(user=gifted_id)
            order_data["recipient_real_name"] = recipient_info["user"]["real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch recipient real name for runner-initiated order:", e)
    else:
        order_data["recipient_real_name"] = order_data["requester_real_name"]

        if runner_offer_claims.get(order_data["runner_id"]):
            client.chat_postEphemeral(
                channel=user_id,
                user=user_id,
                text="❌ That runner has already been matched with another order. Try again later."
            )
            return
        runner_offer_claims[order_data["runner_id"]] = user_id
        try:
            client.chat_postMessage(
                channel=order_data["runner_id"],
                text="📬 Someone just responded to your `/ready` post. You’ve got a mission. Scope the thread for details."
            )
        except Exception as e:
            print("⚠️ Failed to notify runner:", e)


    try:
        user_info = slack_client.users_info(user=user_id)
        order_data["requester_real_name"] = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch requester real name:", e)
    # Ensure requester_real_name is added to order_extras early for countdown updates
    if order_ts not in order_extras:
        order_extras[order_ts] = {}
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
                text="🚨 Modal submitted, but we couldn’t find the original `/ready` message to update."
            )
            return
        safe_chat_update(client, order_channel, order_ts, "New Koffee Karma order posted", formatted_blocks)
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
                text="🚨 Modal submitted, but we couldn’t find the original `/ready` message to update."
            )
            return
        safe_chat_update(client, order_channel, order_ts, "New Koffee Karma order posted", formatted_blocks)
@app.command("/runner")
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
        "water": "WATER",
        "drip_coffee": "DRIP COFFEE",
        "espresso_drinks": "ESPRESSO DRINKS",
        "tea": "TEA"
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
        "status": "pending",
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
            "title": {"type": "plain_text", "text": "Runner Availability"},
            "submit": {"type": "plain_text", "text": "Go Live"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "time_available",
                    "label": {"type": "plain_text", "text": "How much time do you have?"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
                        "placeholder": {"type": "plain_text", "text": "Select time"},
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
                    "label": {"type": "plain_text", "text": "Drinks you can make"},
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
                "❌ *Expired.* No one stepped up.",
                [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "❌ *Expired.* No one stepped up."}
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
                    text=f"🌀 Your order expired. {refund_amount} Karma refunded. Balance restored."
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
    from app import wrap_line
    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]
 
    selected = []
    if "capabilities" in values and "input" in values["capabilities"]:
        selected = [opt["value"] for opt in values["capabilities"]["input"].get("selected_options", [])]
 
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
 
    save_runner_capabilities(user_id, real_name, selected)
    from sheet import log_order_to_sheet
    import datetime
    log_order_to_sheet({
        "order_id": f"runner_{user_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initiated_by": "runner",
        "requester_id": user_id,
        "requester_real_name": real_name,
        "runner_id": user_id,
        "runner_name": real_name,
        "status": "runner_available",
        "drink": "",
        "location": "",
        "notes": "",
        "karma_cost": "",
        "bonus_multiplier": "",
        "time_ordered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "time_claimed": "",
        "time_delivered": ""
    })
 
    # post terminal message with the selected time and capabilities
    pretty_caps = {
        "water": "WATER",
        "drip_coffee": "DRIP COFFEE",
        "espresso_drinks": "ESPRESSO DRINKS",
        "tea": "TEA"
    }
    can_make_str = ", ".join([pretty_caps.get(cap, cap.upper()) for cap in selected]) or "NONE"
    all_options = ["water", "tea", "drip_coffee", "espresso_drinks"]
    cannot_make = [pretty_caps[c] for c in all_options if c not in selected]
    cannot_make_str = ", ".join(cannot_make) if cannot_make else "NONE"
    total_blocks = 20
    filled_blocks = total_blocks
    progress_bar = "[" + ("█" * filled_blocks) + ("░" * (total_blocks - filled_blocks)) + "]"
    can_make_line = terminal_box_line(label="CAN MAKE:", value=can_make_str, width=40)
    cant_make_line = terminal_box_line(label="CAN'T MAKE:", value=cannot_make_str, width=40)
 
    text = (
    "```+----------------------------------------+\n"
    + "|         DRINK RUNNER AVAILABLE         |\n"
    + "+----------------------------------------+\n"
    + terminal_box_line(label="Runner", value=real_name.upper(), width=40, align="label") + "\n"
    + "\n".join(wrap_line_runner("CAN MAKE:", can_make_str, width=40)) + "\n"
    + "\n".join(wrap_line_runner("CAN'T MAKE:", cannot_make_str, width=40)) + "\n"
    + "+----------------------------------------+\n"
    + terminal_box_line(text=f"TIME LEFT ON SHIFT: {selected_time} MINUTES", width=40, align="center") + "\n"
    + terminal_box_line(text=progress_bar, width=40, align="center") + "\n"
    + terminal_box_line(text="------------------------------------", width=40, align="center") + "\n"
    + terminal_box_line(text="↓ CLICK BELOW TO PLACE AN ORDER ↓", width=40, align="center") + "\n"
    + terminal_box_line(text="------------------------------------", width=40, align="center") + "\n"
    + "```"
    )
    
    posted_ready = client.chat_postMessage(
        channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
        text=f"🖐️ {real_name.upper()} is *on the clock* as a runner.\n*⏳ {selected_time} minutes left to send them an order.*",
        blocks=[
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
                        "value": json.dumps({"runner_id": user_id})
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
    )
    order_ts = posted_ready["ts"]
    order_channel = posted_ready["channel"]
    global runner_offer_metadata
    if 'runner_offer_metadata' not in globals():
        runner_offer_metadata = {}
    runner_offer_metadata[user_id] = {
        "ts": order_ts,
        "channel": order_channel
    }
    import threading
    threading.Timer(60, update_ready_countdown, args=(client, selected_time - 1, order_ts, order_channel, user_id, selected_time)).start() 

    msg = "✅ Your delivery offer is now live!"
    if caps_changed:
        msg = "✅ Your drink-making capabilities have been saved and your delivery offer is now live!"
    client.chat_postEphemeral(
        channel=user_id,
        user=user_id,
        text=msg
    )


@app.action("cancel_order")
def handle_cancel_order(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    message = body["message"]
    original_text = ""
    for block in message.get("blocks", []):
        if block.get("type") == "section" and isinstance(block.get("text"), dict):
            original_text = block["text"].get("text", "")
            if original_text:
                break

    order_ts = message["ts"]
    extras = order_extras.get(order_ts, {})
    original_user_id = extras.get("requester_id")
    if not original_user_id:
        original_user_id = re.search(r"FROM <@([A-Z0-9]+)>", original_text or "")
        if original_user_id:
            original_user_id = original_user_id.group(1)

    if user_id != original_user_id:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="❌ You can only cancel your own unclaimed order."
        )
        return

    if "Claimed by" in original_text:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="❌ This order has already been claimed and can’t be canceled."
        )
        return

    # Clean up any extras like GIFs or context
    order_ts = message["ts"]
    if order_ts in order_extras:
        gif_ts = order_extras[order_ts].get("gif_ts")
        if gif_ts:
            try:
                client.chat_delete(channel=body["channel"]["id"], ts=gif_ts)
            except Exception as e:
                print("⚠️ Failed to delete gif message:", e)
        del order_extras[order_ts]
    
    # Refund the karma cost to the original user
    karma_cost = extras.get("karma_cost", 1)
    add_karma(user_id, karma_cost)
    print(f"📬 Sending DM to user_id: {user_id} with message: 🌀 Your order was canceled. {karma_cost} Karma refunded. Balance restored.")
    client.chat_postMessage(
        channel=user_id,
        text=f"🌀 Your order was canceled. {karma_cost} Karma refunded. Balance restored."
    )

    # Stop any further scheduled updates by overwriting the original message with only cancellation info.
    import re
    updated_text = re.sub(r"\n*⏳ \*Time left to claim:\*.*", "", original_text)
    updated_text = re.sub(r"\n*⚠️ This mission’s still unclaimed\..*", "", updated_text)
    updated_text = f"{updated_text}\n\n❌ Order canceled by <@{user_id}>."
    from sheet import update_order_status
    update_order_status(order_ts, status="canceled")
    safe_chat_update(
        client,
        body["channel"]["id"],
        order_ts,
        updated_text,
        [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"❌ *Order canceled by <@{user_id}>.*"}
            }
        ]
    )

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=10000)