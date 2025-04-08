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



from sheet import add_karma, get_karma, get_leaderboard, ensure_user, deduct_karma
 
def wrap_line(label, value, width=50):
    if not label and value:
        centered = value.upper().center(width - 4)
        return [f"| {centered} |"]
    label = label.lstrip()
    # Pad label to fixed width for alignment; using fixed column start for values
    label = label.rstrip(":")
    full = f"{label.upper():<11}{value}".upper()
    full = strip_formatting(full).replace("|", "")  # remove stray pipe characters
    max_content = width - 4  # leave 1 space padding on both sides for proper border alignment
    words = full.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line + (" " if current_line else "") + word) <= max_content:
            current_line += (" " if current_line else "") + word
        else:
            padding = max_content - len(current_line)
            lines.append(f"| {current_line}{' ' * padding} |")
            current_line = word
    if current_line:
        padding = max_content - len(current_line)
        lines.append(f"| {current_line}{' ' * padding} |")
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
        import datetime
        order_data = {
            "order_id": order_ts,
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
        print(f"🧪 Names Debug — requester: {order_data['requester_real_name']}, recipient: {order_data['recipient_real_name']}")
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

        if not current_message["messages"]:
            print("❌ No messages found for countdown update")
            return

        original_text = current_message["messages"][0].get("text", "")
        print(f"📝 Original message text (repr): {repr(original_text)}")
        print(f"📤 Sending updated Slack message with remaining_minutes = {remaining}")

        print("📤 Sending updated message to Slack regardless of text match")
        print(f"🧾 Updated blocks:\n{updated_blocks}")
        print(f"🧪 Sending to Slack with FROM: {order_data.get('requester_real_name')} TO: {order_data.get('recipient_real_name')}")
        client.chat_update(
            channel=order_channel,
            ts=order_ts,
            text=original_text,
            blocks=updated_blocks
        )
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
        import traceback
        traceback.print_exc()
        print(f"🚨 Countdown exception traceback printed above for order {order_ts}")
        print(f"🚨 update_countdown FAILED: {e}")

def update_ready_countdown(client, remaining, ts, channel, user_id):
    try:
        if remaining <= 0:
            client.chat_update(
                channel=channel,
                ts=ts,
                text=f"❌ Offer expired. <@{user_id}> is no longer available.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"❌ Offer expired. <@{user_id}> is no longer available."
                        }
                    }
                ]
            )
            return

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🖐️ <@{user_id}> is *ready to deliver* a drink.\n*⏳ {remaining} minutes left to send them an order.*"
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

        client.chat_update(
            channel=channel,
            ts=ts,
            text=f"<@{user_id}> is ready to deliver — {remaining} minutes left.",
            blocks=blocks
        )

        import threading
        threading.Timer(60, update_ready_countdown, args=(client, remaining - 1, ts, channel, user_id)).start()

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
                    "type": "input",
                    "block_id": "location",
                    "label": {"type": "plain_text", "text": "Where’s it going?"},
                    "element": {
                        "type": "static_select",
                        "action_id": "input",
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
        "espresso": 3
    }
    karma_cost = drink_map[drink_value]
    drink = drink_detail
    location = values["location"]["input"]["selected_option"]["value"]
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
    if not runner_id:
        posted = client.chat_postMessage(
            channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
            text="New Koffee Karma order posted",
            blocks=[]
        )
        order_ts = posted["ts"]
        order_channel = posted["channel"]

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

    import datetime
    # Ensure runner_id is defined to prevent NameError when building order_data
    runner_id = body["view"].get("private_metadata", "")
    order_data = {
        "order_id": order_ts,
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
    if order_data["runner_id"]:
        gifted_id = gifted_id or ""
        try:
            runner_info = slack_client.users_info(user=order_data["runner_id"])
            order_data["runner_name"] = runner_info["user"]["real_name"]
            order_data["runner_real_name"] = runner_info["user"]["real_name"]
            order_data["claimed_by"] = order_data["runner_real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch runner real name:", e)
    if order_ts not in order_extras:
        order_extras[order_ts] = {}
    order_extras[order_ts]["runner_real_name"] = order_data["runner_real_name"]
    if order_data["runner_id"]:
        try:
            requester_info = slack_client.users_info(user=user_id)
            order_data["requester_real_name"] = requester_info["user"]["real_name"]
            order_data["claimed_by"] = order_data["runner_real_name"]
        except Exception as e:
            print("⚠️ Failed to fetch requester real name for runner-initiated order:", e)

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

    # The following block has been commented out to keep the /ready message clean.
    # if runner_id:
    #     order_data["claimed_by"] = order_data.get("runner_name") or runner_id
    #     order_data["runner_real_name"] = order_data.get("runner_real_name") or order_data.get("runner_name")
    #     order_data["runner_karma"] = get_karma(runner_id)
    #     formatted_blocks = format_order_message(order_data)
    #     client.chat_update(
    #         channel=order_channel,
    #         ts=order_ts,
    #         text="New Koffee Karma order posted",
    #         blocks=formatted_blocks
    #     )
    #     return

    from slack_sdk import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)
    
    try:
        user_info = slack_client.users_info(user=user_id)
        order_data["requester_real_name"] = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch requester real name:", e)
    
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
        client.chat_update(
            channel=order_channel,
            ts=order_ts,  # reuse the original /ready message timestamp
            text="☕ Order claimed and posted.",
            blocks=formatted_blocks
        )
        return
    else:
        formatted_blocks = format_order_message(order_data)
        client.chat_update(
            channel=order_channel,
            ts=order_ts,
            text="New Koffee Karma order posted",
            blocks=formatted_blocks
        )
@app.command("/ready")
def handle_ready_command(ack, body, client):
    ack()
    user_id = body["user_id"]
    location = ""
    notes = ""
    karma_cost = ""
    posted_ready = client.chat_postMessage(
        channel=os.environ.get("KOFFEE_KARMA_CHANNEL"),
        text=f"🖐️ <@{user_id}> is *ready to deliver* a drink.\n*⏳ 10 minutes left to send them an order.*",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🖐️ <@{user_id}> is *ready to deliver* a drink.\n*⏳ 10 minutes left to send them an order.*"
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
    )
    order_ts = posted_ready["ts"]
    order_channel = posted_ready["channel"]
    runner_offer_claims[user_id] = None  # Mark this runner as available and unclaimed
    print(f"🆕 Runner offer posted by {user_id} — awaiting match.")
    drink = ""
    location = ""
    notes = ""
    karma_cost = ""
 
    
    
    # Log order with "time_ordered" as the timestamp key
    from sheet import log_order_to_sheet
    import datetime
    gifted_id = None
    order_data = {
        "order_id": order_ts,
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
    log_order_to_sheet(order_data)

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
            client.chat_update(
                channel=order_channel,
                ts=order_ts,
                text="❌ *Expired.* No one stepped up.",
                blocks=[
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

            client.chat_update(
                channel=order_channel,
                ts=order_ts,
                text=msg_text,
                blocks=updated_blocks
            )
        except Exception as e:
            print("⚠️ Reminder ping failed:", e)

    print("🔔 Timer started for reminder_ping (300s)")
    threading.Timer(300, reminder_ping, args=(order_ts, order_channel)).start()  # 5-minute reminder


    print("🔁 Kicking off countdown now...")
    print("🚀 Starting countdown thread via update_countdown() in handle_modal_submission")
    order_extras[order_ts] = {
        "active": True,
        "claimed": False,
        "requester_real_name": order_data["requester_real_name"],
        "recipient_real_name": order_data["recipient_real_name"],
        "requester_id": user_id,
        "location": location,
        "notes": notes,
        "karma_cost": karma_cost,
    }
    update_ready_countdown(client, 10, order_ts, order_channel, user_id)


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
    client.chat_update(
        channel=body["channel"]["id"],
        ts=order_ts,
        text=updated_text,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"❌ *Order canceled by <@{user_id}>.*"}
            }
        ]
    )
    return

@app.action("cancel_ready_offer")
def handle_cancel_ready_offer(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    ts = body["message"]["ts"]
    channel_id = body["channel"]["id"]

    # Overwrite the message with cancellation confirmation
    client.chat_update(
        channel=channel_id,
        ts=ts,
        text=f"❌ Offer canceled by <@{user_id}>.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ *Offer canceled by <@{user_id}>.*"
                }
            }
        ]
    )

    # Remove the runner's offer from the claims dictionary
    if user_id in runner_offer_claims:
        del runner_offer_claims[user_id]

@app.action("open_order_modal_for_runner")
def handle_order_modal_for_runner(ack, body, client):
    ack()
    trigger_id = body["trigger_id"]
    action_value = body["actions"][0]["value"]
    try:
        runner_data = json.loads(action_value)
        runner_id = runner_data.get("runner_id", "")
    except Exception as e:
        print("⚠️ Failed to parse runner ID from action value:", e)
        runner_id = ""
    client.views_open(
        trigger_id=trigger_id,
        view=build_order_modal(trigger_id, runner_id)["view"]
    )

@app.action("claim_order")
def handle_claim_order(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    # Prevent users from claiming their own orders, except for admin
    ADMIN_IDS = {"U02EY5S5J0M"}
    extras = order_extras.get(body["message"]["ts"], {})
    requester_id = extras.get("requester_id")
    if requester_id == user_id and user_id not in ADMIN_IDS:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="🚫 You can’t claim your own drop. Wait for someone else to step up."
        )
        return
    original_message = body["message"]
    order_text = ""
    for block in original_message.get("blocks", []):
        if block.get("type") == "section" and "text" in block:
            order_text = block["text"].get("text", "")
            break
    import re
    print("🔍 Before removing time line:", order_text)
    order_text = re.sub(r"\n*⏳ \*Time left to claim:\*.*(?:\n)?", "", order_text, flags=re.MULTILINE)
    print("✅ After removing time line:", order_text)
    order_text = re.sub(r"\n*⚠️ This mission’s still unclaimed\..*", "", order_text, flags=re.MULTILINE)
    order_text = re.sub(r"\n*📸 \*Flex the drop\..*", "", order_text, flags=re.MULTILINE)
    
    order_ts = body["message"]["ts"]
    # Pull values from order_extras instead of parsing the message text
    extras = order_extras.get(order_ts, {})
    drink = extras.get("drink", "")
    if not drink:
        # Attempt to extract the drink from the order text if not already set
        order_text = ""
        for block in body["message"].get("blocks", []):
            if block.get("type") == "section" and "text" in block:
                order_text = block["text"].get("text", "")
                break
        import re
        match = re.search(r"\| DRINK :\s+(\S+)", order_text)
        if match:
            drink = match.group(1).strip()
    location = extras.get("location", "")
    notes = extras.get("notes", "")
    karma_cost = extras.get("karma_cost", 1)
    if order_ts not in order_extras:
        order_extras[order_ts] = {"runner_id": None, "active": True, "claimed": False}
        order_extras[order_ts]["location"] = location
        order_extras[order_ts]["notes"] = notes
    order_extras[order_ts]["runner_id"] = user_id
    order_extras[order_ts]["drink"] = drink
    order_extras[order_ts]["karma_cost"] = karma_cost
    order_extras[order_ts]["active"] = False
    order_extras[order_ts]["claimed"] = True
    
    from sheet import update_order_status
    from slack_sdk import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)
    
    # Fetch runner's real name
    runner_name = ""
    try:
        user_info = slack_client.users_info(user=user_id)
        runner_name = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch runner real name for update:", e)
    order_extras[order_ts]["runner_real_name"] = runner_name
    
    update_order_status(
        order_id=order_ts,
        status="claimed",
        runner_id=user_id,
        runner_name=runner_name,
        claimed_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    gifted_id = None
    # Removed recipient_id initialization to avoid unbound variable issues
    match = re.search(r"FROM <@([A-Z0-9]+)>", order_text)
    if match:
        requester_id = match.group(1)
    else:
        requester_id = user_id  # fallback if not found
    order_extras[order_ts]["recipient_id"] = gifted_id if gifted_id else user_id
    order_extras[order_ts]["requester_id"] = requester_id
    order_extras[order_ts]["drink"] = drink
    order_extras[order_ts]["karma_cost"] = karma_cost
    order_data = {
        "order_id": order_ts,
        "requester_real_name": order_extras.get(order_ts, {}).get("requester_real_name"),
        "recipient_real_name": order_extras.get(order_ts, {}).get("recipient_real_name"),
        "recipient_id": order_extras.get(order_ts, {}).get("recipient_id", user_id),
        "drink": extras.get("drink", ""),
        "location": extras.get("location", ""),
        "notes": extras.get("notes", ""),
        "karma_cost": karma_cost,
        "runner_karma": get_karma(user_id),
        "runner_name": runner_name,
        "runner_real_name": "",
        "claimed_by": runner_name,
        "requester_id": requester_id,
        "bonus_multiplier": "",
        "channel_id": body["channel"]["id"],
    }
    print("🔍 order_extras for this order:")
    for k, v in order_extras.get(order_ts, {}).items():
        print(f"  {k}: {v}")
    updated_blocks = format_order_message(order_data)
    print("📤 Blocks being sent to Slack:")
    import pprint
    pprint.pprint(updated_blocks)
    try:
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=updated_blocks
        )
        print("✅ Slack message successfully updated.")
    except Exception as e:
        print("🚨 Failed to update Slack message:", e)

    print(f"📬 Sending DM to runner (user_id: {user_id}) with message: You took the mission. Don't forget to hit 'MARK AS DELIVERED' once the goods are dropped.")
    client.chat_postMessage(
        channel=user_id,
        text="You took the mission. Don't forget to hit 'MARK AS DELIVERED' once the goods are dropped."
    )
    if requester_id:
        print(f"📬 Sending DM to requester (user_id: {requester_id}) with message: ☕️ Your order was claimed by <@{user_id}>. Hold tight — delivery is on the way.")
        client.chat_postMessage(
            channel=requester_id,
            text=f"☕️ Your order was claimed by <@{user_id}>. Hold tight — delivery is on the way."
        )
    def send_completion_reminder():
        try:
            # Fetch the latest version of the message to check if it's already marked as delivered
            current_message = client.conversations_history(channel=body["channel"]["id"], latest=body["message"]["ts"], inclusive=True, limit=1)
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if re.search(r"drop completed", msg_text, re.IGNORECASE):
                    return  # Already completed
            print(f"📬 Sending DM to runner (user_id: {user_id}) with message: ⏰ Heads-up: Your claimed order is still marked as undelivered. Don’t forget to hit *MARK AS DELIVERED* once it’s done!")
            client.chat_postMessage(
                channel=user_id,
                text="⏰ Heads-up: Your claimed order is still marked as undelivered. Don’t forget to hit *MARK AS DELIVERED* once it’s done!"
            )
        except Exception as e:
            print("⚠️ Failed to send completion reminder:", e)

    import threading
    threading.Timer(900, send_completion_reminder).start()  # 15 minutes

import threading

@app.action("mark_delivered")
def handle_mark_delivered(ack, body, client):
    ack()
    print("🛠️ handle_mark_delivered triggered")
    print("🛠️ Payload:", body)
    print("✅ mark_delivered button clicked")

    try:
        safe_body = copy.deepcopy(body)
        safe_client = client
    except Exception as e:
        print("🚨 Error copying body/client:", repr(e))
        return

    def do_work():
        import re
        try:
            print("📦 mark_delivered payload:", safe_body)
            original_message = safe_body.get("message", {})
            order_ts = original_message.get("ts")
            runner_id = order_extras.get(order_ts, {}).get("runner_id")
            runner_name = order_extras.get(order_ts, {}).get("runner_real_name", "")
            if not runner_id:
                print("⚠️ runner_id missing for order_ts", order_ts)
            location = order_extras.get(order_ts, {}).get("location", "")
            notes = order_extras.get(order_ts, {}).get("notes", "")
            karma_cost = order_extras.get(order_ts, {}).get("karma_cost", 1)

            deliverer_id = safe_body.get("user", {}).get("id")
            text_blocks = original_message.get("blocks", [])
            requester_id = order_extras.get(order_ts, {}).get("requester_id")
            recipient_id = order_extras.get(order_ts, {}).get("recipient_id")

            if not runner_id or (deliverer_id != runner_id and deliverer_id != recipient_id):
                safe_client.chat_postEphemeral(
                    channel=safe_body["channel"]["id"],
                    user=deliverer_id,
                    text="❌ Only the recipient or the delivery punk can mark this complete."
                )
                return
            order_text = ""
            for block in original_message.get("blocks", []):
                if block.get("type") == "section" and "text" in block:
                    order_text = block["text"].get("text", "")
                    break
            import re
            order_text = re.sub(r"\n*⏳ \*Time left to claim:\*.*", "", order_text)
            order_text = re.sub(r"\n*⚠️ This mission’s still unclaimed\..*", "", order_text)
            order_text = re.sub(r"\n*📸 \*Flex the drop\..*", "", order_text)

            # Removed redundant check since runner_id is now validated above

            bonus_multiplier = order_extras.get(order_ts, {}).get("bonus_multiplier", 1)
            runner_name = order_extras.get(order_ts, {}).get("runner_real_name", "")
            points = add_karma(runner_id, bonus_multiplier)
            print(f"☚️ +{bonus_multiplier} point(s) for {runner_id}. Total: {points}")

            # Debug: Print order_extras for current order_ts
            print("🧪 DEBUG — order_extras[order_ts]:")
            for k, v in order_extras.get(order_ts, {}).items():
                print(f"{k}: {v}")

            new_text = (
                f"{order_text}\n\n✅ *DROP COMPLETED*\n"
                f"💥 <@{runner_id}> EARNED +{bonus_multiplier} KARMA (TOTAL: *{points}*)"
            )
            drink = order_extras.get(order_ts, {}).get("drink", "")

            order_data = {
                "order_id": order_ts,
                "delivered_by": runner_name,
                "requester_id": requester_id,
                "requester_real_name": order_extras.get(order_ts, {}).get("requester_real_name", ""),
                "recipient_real_name": order_extras.get(order_ts, {}).get("recipient_real_name", ""),
                "runner_real_name": order_extras.get(order_ts, {}).get("runner_real_name", ""),
                "runner_id": runner_id,
                "runner_name": runner_name,
                "claimed_by": runner_name,
                "runner_karma": get_karma(runner_id),
                "recipient_id": recipient_id,
                "drink": drink,
                "location": location,
                "notes": notes,
                "karma_cost": karma_cost,
                "bonus_multiplier": bonus_multiplier,
                "status": "delivered",
                "time_delivered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            # Debug: Print order_data before formatting message
            print("🧪 DEBUG — order_data being passed to format_order_message:")
            for k, v in order_data.items():
                print(f"{k}: {v}")
            updated_blocks = format_order_message(order_data)
            print("🧪 DEBUG — Updated blocks after mark_delivered formatting:")
            import pprint
            pprint.pprint(updated_blocks)

            safe_client.chat_update(
                channel=safe_body["channel"]["id"],
                ts=original_message["ts"],
                text=new_text,
                blocks=updated_blocks
            )
            safe_client.chat_postMessage(
                channel=safe_body["channel"]["id"],
                thread_ts=original_message["ts"],
                text=":camera_with_flash: Flex the drop. On mobile? Hit the *`+`* and share a shot of your delivery.\nDon’t forget to *check the box* to share it to #koffee-karma-sf. Let the people see what you dropped."
            )
            if bonus_multiplier > 1:
                safe_client.chat_postMessage(
                    channel=safe_body["channel"]["id"],
                    text=f"🎉 *Bonus Karma!* <@{runner_id}> earned *{bonus_multiplier}x* points for this drop. 🔥"
                )

            print(f"📬 Sending DM to runner (runner_id: {runner_id}) with message: Mission complete. +1 Koffee Karma. Balance: *{points}*. Stay sharp.")
            safe_client.chat_postMessage(
                channel=runner_id,
                text=f"Mission complete. +1 Koffee Karma. Balance: *{points}*. Stay sharp."
            )



            from sheet import update_order_status
            update_order_status(
                order_id=order_ts,
                status="delivered",
                delivered_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                bonus_multiplier=bonus_multiplier
            )
            print("📨 Attempting to update Slack message with updated_blocks")
            print("✅ All steps completed successfully")

        except Exception as e:
            print("🚨 Error in mark_delivered thread:", repr(e))

    threading.Thread(target=do_work).start()

@app.command("/karma")
def handle_karma_command(ack, body, client):
    ack()
    user_id = body["user_id"]
    points = get_karma(user_id)
    def get_title(karma):
        if karma >= 20:
            return "CAFE SHADE MYSTIC"
        elif karma >= 16:
            return "ORDER ORACLE"
        elif karma >= 12:
            return "STEAM WHISPERER"
        elif karma >= 8:
            return "FOAM SCRYER"
        elif karma >= 5:
            return "KEEPER OF THE DRIP"
        elif karma >= 3:
            return "BEAN SEEKER"
        elif karma >= 1:
            return "THE INITIATE"
        else:
            return "THE PARCHED"

    title = get_title(points)
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        text=f"☚️ You've got *{points} Koffee Karma* — title: *{title}*. Keep the chaos brewing."
    )

@app.command("/leaderboard")
def handle_leaderboard_command(ack, body, client):
    ack()
    leaderboard = get_leaderboard()
 
    def get_title(karma):
        if karma >= 20:
            return "CAFE SHADE MYSTIC"
        elif karma >= 16:
            return "ORDER ORACLE"
        elif karma >= 12:
            return "STEAM WHISPERER"
        elif karma >= 8:
            return "FOAM SCRYER"
        elif karma >= 5:
            return "KEEPER OF THE DRIP"
        elif karma >= 3:
            return "BEAN SEEKER"
        elif karma >= 1:
            return "THE INITIATE"
        else:
            return "THE PARCHED"
 
    header = "+===================[ THE BREW SCROLL ]===================+"
    title = "| RANK |        NAME        | KARMA |         TITLE       |"
    divider = "|------|--------------------|-------|---------------------|"
    footer = "+=========================================================+"
    commands = "|      /ORDER     /KARMA     /LEADERBOARD     /REDEEM     |"
 
    lines = [header, title, divider]
    for i, row in enumerate(leaderboard, start=1):
        rank = str(i).center(6)
        name = (" " + row['Name'].upper()).ljust(20)[:20]
        karma = str(row['Karma']).center(7)
        title_str = (" " + get_title(row['Karma'])).ljust(21)[:21]
        lines.append(f"|{rank}|{name}|{karma}|{title_str}|")
    lines.append(footer)
    lines.append(commands)
    lines.append(footer)
 
    leaderboard_text = "```" + "\n".join(lines) + "```"
 
    client.chat_postMessage(
        channel=body["channel_id"],
        text="Koffee Karma Leaderboard",
        blocks=[{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": leaderboard_text
            }
        }]
    )

@app.command("/redeem")
def handle_redeem_code(ack, body, client):
    ack()
    user_id = body["user_id"]
    text = body.get("text", "").strip().upper()

    if not text:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text="❗ Usage: `/redeem YOURCODE123`"
        )
        return

    from sheet import mark_code_redeemed
    success = mark_code_redeemed(text, user_id)

    if isinstance(success, str) and success.startswith("success:"):
        points = success.split(":")[1]
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text=f"✅ Code `{text}` redeemed. +{points} Karma awarded."
        )
    elif success == "already_used":
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text=f"🚫 You've already redeemed code `{text}`."
        )
    elif success == "expired":
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text=f"⌛ Code `{text}` is expired and no longer valid."
        )
    elif success == "limit_reached":
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text=f"🚫 Code `{text}` has reached its redemption limit."
        )
    else:
        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text=f"🚫 Invalid or unknown code: `{text}`"
        )


@app.action("*")
def catch_all_actions(ack, body):
    ack()
    print("⚠️ Caught an unhandled action:", body.get("actions", [{}])[0].get("action_id"))

@app.event("message")
def handle_join_message_events(body, say, client, event):
    subtype = event.get("subtype")
    
    # Disabled to prevent duplicate welcome messages
    # if subtype == "channel_join":
    #     user_id = event.get("user")
    #     channel_id = event.get("channel")
    # 
    #     print(f"👋 Detected join via channel_join: {user_id} joined {channel_id}")
    # 
    #     from sheet import ensure_user
    #     was_new = ensure_user(user_id)
    # 
    #     if was_new:
    #         say(f"👋 <@{user_id}> just entered the Koffee Karma zone. Show no mercy. ☕️")
    #         client.chat_postMessage(
    #             channel=user_id,
    #             text=(
    #             "Welcome to *Koffee Karma* ☕️💀\n\n"
    #                 "Here’s how it works:\n"
    #                 "• `/order` — Request a drink (costs Karma).\n"
    #                 "• `/karma` — Check your Karma.\n"
    #                 "• `/leaderboard` — See the legends.\n\n"
    #                 "You’ve got *3 Karma points* to start. Spend wisely. Earn more by delivering orders.\n"
    #                 "Let the chaos begin. ⚡️"
    #             )
    #         )

@app.event("team_join")
def handle_team_join(event, client):
    user_id = event.get("user", {}).get("id")
    if not user_id:
        return

    try:
        was_new = ensure_user(user_id)
        if was_new:
            welcome_lines = [
                f"👋 <@{user_id}> just entered the Koffee Karma zone. Show no mercy. ☕️",
                f"☕️ <@{user_id}> just logged on to the brew grid.",
                f"🔥 <@{user_id}> joined. Time to stir some espresso-fueled chaos.",
                f"📦 <@{user_id}> has checked in. Deliveries won't deliver themselves.",
                f"💀 <@{user_id}> is here. Hope they're ready for the grind.",
                f"⚡️ <@{user_id}> appeared. Let's get volatile.",
                f"🥶 <@{user_id}> dropped in cold. Let’s heat things up.",
                f"🚨 <@{user_id}> joined the rebellion. Brew responsibly.",
                f"🌀 <@{user_id}> warped into the zone. Coffee protocol initiated.",
                f"🧃 <@{user_id}> arrived thirsty. You know what to do."
            ]
            client.chat_postMessage(
                channel=user_id,
                text=random.choice(welcome_lines)
            )
    except Exception as e:
        print("⚠️ Failed to initialize user on team_join:", e)

@app.event("member_joined_channel")
def handle_member_joined_channel(event, client, logger):
    logger.info(f"📥 Received member_joined_channel event: {event}")

    user_id = event.get("user")
    channel_id = event.get("channel")

    if not user_id or not channel_id:
        logger.info("⚠️ Missing user or channel in member_joined_channel event")
        return

    from sheet import ensure_user
    ensure_user(user_id)  # Still make sure they’re initialized, but ignore return value

    try:
        welcome_lines = [
            f"👋 <@{user_id}> just entered the Koffee Karma zone. Show no mercy. ☕️\nType `/order`, `/karma`, or `/leaderboard` to survive the grind.",
            f"☕️ <@{user_id}> just logged on to the brew grid.\nType `/order`, `/karma`, or `/leaderboard` to power up.",
            f"🔥 <@{user_id}> joined. Time to stir some espresso-fueled chaos.\nTry `/order`, `/karma`, or `/leaderboard` to get in the flow.",
            f"📦 <@{user_id}> has checked in. Deliveries won't deliver themselves.\nHit `/order`, `/karma`, or `/leaderboard` to jump in.",
            f"💀 <@{user_id}> is here. Hope they're ready for the grind.\nStart with `/order`, `/karma`, or `/leaderboard`.",
            f"⚡️ <@{user_id}> appeared. Let's get volatile.\nHit `/order`, `/karma`, or `/leaderboard` to get started.",
            f"🥶 <@{user_id}> dropped in cold. Let’s heat things up.\nType `/order`, `/karma`, or `/leaderboard` to thaw out.",
            f"🚨 <@{user_id}> joined the rebellion. Brew responsibly.\nUse `/order`, `/karma`, or `/leaderboard` to stir things up.",
            f"🌀 <@{user_id}> warped into the zone. Coffee protocol initiated.\nEngage with `/order`, `/karma`, or `/leaderboard`.",
            f"🧃 <@{user_id}> arrived thirsty. You know what to do.\nTry `/order`, `/karma`, or `/leaderboard` to start the drip."
        ]
        client.chat_postMessage(
            channel=channel_id,
            text=random.choice(welcome_lines)
        )
        client.chat_postMessage(
            channel=user_id,
            text=(
                "Welcome to *Koffee Karma* ☕️💀\n\n"
                "Here’s how it works:\n"
                "• `/order` — Request a drink (costs Karma).\n"
                "• `/karma` — Check your Karma.\n"
                "• `/leaderboard` — See the legends.\n"
                "• `/redeem` — Redeem a code for bonus Karma.\n\n"
                "You’ve got *3 Koffee Karma* to start. Spend wisely. Earn more by delivering orders.\n"
                "Let the chaos begin. ⚡️"
            )
        )
    except Exception as e:
        logger.error("⚠️ Failed to send welcome messages: %s", e)

@app.event("*")
def catch_all_events(event, logger, next):
    logger.info(f"🌀 CATCH-ALL EVENT: {event}")
    next()  # Allow other event handlers to continue processing


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    import threading
    
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    threading.Thread(target=run_schedule, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=port, threaded=True)
@app.action("cancel_ready_offer")
def handle_cancel_ready_offer(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    offer_user_id = body["actions"][0]["value"]
    if user_id != offer_user_id:
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=user_id,
            text="❌ Only the runner who posted this offer can cancel it."
        )
        return
    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"❌ Offer canceled by <@{user_id}>.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ Offer canceled by <@{user_id}>."
                }
            }
        ]
    )