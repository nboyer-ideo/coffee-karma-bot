from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import schedule
import time
import random
import requests
import os
import copy

order_extras = {}
countdown_timers = {}  # order_ts -> remaining minutes
countdown_timers = {}


def get_punk_gif():
    api_key = os.environ.get("GIPHY_API_KEY")  # You’ll need to get one from Giphy
    if not api_key:
        return None

    query = random.choice(["punk", "sarcastic", "grunge", "rebel", "dark humor", "eyeroll", "anarchy"])
    url = f"https://api.giphy.com/v1/gifs/search?api_key={api_key}&q={query}&limit=20&offset=0&rating=pg-13&lang=en"

    try:
        response = requests.get(url)
        data = response.json()
        if data["data"]:
            gif_url = random.choice(data["data"])["images"]["downsized"]["url"]
            return gif_url
    except Exception as e:
        print("⚠️ Giphy API error:", e)
        return None

    return None

from sheet import add_karma, get_karma, get_leaderboard, ensure_user, deduct_karma

# Load secrets from .env
from dotenv import load_dotenv
load_dotenv()

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET")
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

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

@app.command("/order")
def handle_order(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "koffee_request_modal",
            "title": {"type": "plain_text", "text": "Place Your Order"},
            "submit": {"type": "plain_text", "text": "Drop It"},
            "close": {"type": "plain_text", "text": "Nevermind"},
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
                    "element": {"type": "plain_text_input", "action_id": "input"}
                },
                {
                    "type": "input",
                    "block_id": "location",
                    "label": {"type": "plain_text", "text": "Where’s it going?"},
                    "element": {"type": "plain_text_input", "action_id": "input"}
                },
                {
                    "type": "input",
                    "block_id": "gift_to",
                    "optional": True,
                    "label": { "type": "plain_text", "text": "Gift to (optional)" },
                    "element": {
                        "type": "users_select",
                        "action_id": "input",
                        "placeholder": { "type": "plain_text", "text": "Choose a coworker" }
                    }
                },
                {
                    "type": "input",
                    "block_id": "notes",
                    "optional": True,
                    "label": {"type": "plain_text", "text": "Extra details (if it matters)"},
                    "element": {"type": "plain_text_input", "action_id": "input"}
                }
            ]
        }
    )

@app.view("koffee_request_modal")
def handle_modal_submission(ack, body, client):
    ack()
    values = body["view"]["state"]["values"]
    drink_value = values["drink_category"]["input"]["selected_option"]["value"]
    user_id = body["user"]["id"]
    if drink_value == "espresso":
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="🚫 Espresso orders are temporarily unavailable — the machine's down. Choose something else while we fix it up."
        )
        return
    drink_detail = values["drink_detail"]["input"]["value"]
    drink_map = {
        "water": 1,
        "drip": 2,
        "espresso": 3
    }
    karma_cost = drink_map[drink_value]
    drink = drink_detail
    location = values["location"]["input"]["value"]
    notes = values["notes"]["input"]["value"] if "notes" in values else ""
    gifted_id = values["gift_to"]["input"]["selected_user"] if "gift_to" in values and "input" in values["gift_to"] else None
    
    

    points = get_karma(user_id)
    if points < karma_cost:
        client.chat_postEphemeral(
            channel=user_id,
            user=user_id,
            text="🚫 You don't have enough Koffee Karma to place this order. Deliver drinks to earn more."
        )
        return

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
        f"— — — — — — — — — — — —\n\n"
        f"🎁 {karma_cost} KARMA REWARD\n"
        f"⏳ 10 MINUTES TO CLAIM OR IT DIES"
    )

    posted = client.chat_postMessage(
        channel="#koffee-karma-sf",
        text=full_text,
        blocks=[
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": full_text}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "CLAIM THIS MISSION"},
                        "value": f"{user_id}|{drink}|{location}",
                        "action_id": "claim_order"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "CANCEL"},
                        "style": "danger",
                        "value": f"cancel|{user_id}|{drink_value}",
                        "action_id": "cancel_order"
                    }
                ]
            }
        ]
    )
    order_ts = posted["ts"]
    order_channel = posted["channel"]
 
    # Post punk GIF and track its timestamp
    gif_ts = None
    gif_url = get_punk_gif()
    if gif_url:
        try:
            gif_message = client.chat_postMessage(
                channel=order_channel,
                blocks=[{
                    "type": "image",
                    "image_url": gif_url,
                    "alt_text": "coffee gif"
                }],
                text="Grit drop"
            )
            gif_ts = gif_message["ts"]
        except Exception as e:
            print("⚠️ Failed to post gif:", e)
 
    if order_ts and gif_ts:
        global order_extras
        if order_ts not in order_extras:
            order_extras[order_ts] = {}
        order_extras[order_ts].update({
            "gif_ts": gif_ts,
            "context_line": context_line,
            "claimer_id": None,
            "active": True
        })
        order_extras[order_ts]["base_text"] = full_text.replace(f"⏳ 10 MINUTES TO CLAIM OR IT DIES", "").strip()
 
    deduct_karma(user_id, karma_cost)

    if gifted_id:
        client.chat_postMessage(
            channel=gifted_id,
            text=f"🎁 You’ve been gifted a drink order by <@{user_id}>. Let the koffee flow."
        )

    # Log order with "time_ordered" as the timestamp key
    from sheet import log_order_to_sheet
    import datetime
    order_data = {
        "order_id": order_ts,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "requester_id": user_id,
        "requester_real_name": "",
        "claimer_id": "",
        "claimer_real_name": "",
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
        "time_delivered": ""
    }
    log_order_to_sheet(order_data)

    # Start countdown timer for order expiration
    import threading
    def cancel_unclaimed_order():
        try:
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if current_message["messages"]:
                current_text = current_message["messages"][0].get("text", "")
                if any(phrase in current_text for phrase in ["Canceled", "Claimed", "Order canceled by", "❌ Order canceled"]):
                    return  # Skip if canceled or claimed
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

    threading.Timer(600, cancel_unclaimed_order).start()  # 10 minutes
    # Reminder ping halfway through if still unclaimed
    def reminder_ping():
        try:
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if order_extras.get(order_ts, {}).get("claimed", False):
                print(f"🔕 Skipping reminder — order {order_ts} already claimed.")
                return
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if any(phrase in msg_text for phrase in ["Claimed by", "Expired", "Canceled", "Order canceled by"]):
                    return  # Skip reminder if already handled

                # Append the reminder directly to the original message text
                if "⚠️ This mission’s still unclaimed." not in msg_text:
                    updated_text = f"{msg_text}\n\n*⚠️ STILL UNCLAIMED — CLOCK'S TICKING ⏳*\n> STEP UP OR STAND DOWN. 5 MINUTES LEFT TO CLAIM."
                    
                    order_extras[order_ts]["reminder_added"] = True
                    
                    client.chat_update(
                        channel=order_channel,
                        ts=order_ts,
                        text=updated_text,
                        blocks=[
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": updated_text}
                            },
                            {
                                "type": "actions",
                                "elements": [
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": "CLAIM THIS MISSION"},
                                        "value": f"{user_id}|{drink}|{location}",
                                        "action_id": "claim_order"
                                    },
                                    {
                                        "type": "button",
                                        "text": {"type": "plain_text", "text": "CANCEL"},
                                        "style": "danger",
                                        "value": f"cancel|{user_id}|{drink_value}",
                                        "action_id": "cancel_order"
                                    }
                                ]
                            }
                        ]
                    )
        except Exception as e:
            print("⚠️ Reminder ping failed:", e)

    threading.Timer(300, reminder_ping).start()  # 5-minute reminder

    # Start live countdown updates for order expiration
    def update_countdown(remaining, order_ts, order_channel, user_id, gifted_id, drink, location, notes, karma_cost):
        print(f"⏱️ Starting countdown update. Remaining: {remaining} for order {order_ts}")
    try:
        if order_extras.get(order_ts, {}).get("claimed", False):
            return
        if not order_extras.get(order_ts, {}).get("active", True):
            return

        base_text = order_extras[order_ts].get("base_text", "")
        new_text = f"{base_text}\n\n⏳ {remaining} MINUTES TO CLAIM OR IT DIES"
        client.chat_update(
            channel=order_channel,
            ts=order_ts,
            text=new_text,
            blocks=[
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": new_text}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "CLAIM THIS MISSION"},
                            "value": f"{user_id}|{drink}|{location}",
                            "action_id": "claim_order"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "CANCEL"},
                            "style": "danger",
                            "value": f"cancel|{user_id}|{drink}",
                            "action_id": "cancel_order"
                        }
                    ]
                }
            ]
        )
        if not base_text:
            print("⚠️ No base_text found for countdown.")
            return
        if remaining > 1:
            import threading
            threading.Timer(60, update_countdown, args=(
                remaining - 1, order_ts, order_channel,
                user_id, gifted_id, drink, location, notes, karma_cost
            )).start()
    except Exception as e:
        print("⚠️ Error in countdown update:", e)

    new_text = f"{base_text}\n\n⏳ {remaining} MINUTES TO CLAIM OR IT DIES"
    client.chat_update(
        channel=order_channel,
        ts=order_ts,
        text=new_text,
        blocks=[
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": new_text}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "CLAIM THIS MISSION"},
                        "value": f"{user_id}|{drink}|{location}",
                        "action_id": "claim_order"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "CANCEL"},
                        "style": "danger",
                        "value": f"cancel|{user_id}|{drink}",
                        "action_id": "cancel_order"
                    }
                ]
            }
        ]
    )
    if remaining > 1:
        import threading
        threading.Timer(60, update_countdown, args=(
            remaining - 1, order_ts, order_channel,
            user_id, gifted_id, drink, location, notes, karma_cost
        )).start()


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

    # Extract the original_user_id from the cancel button's value
    original_user_id = None
    for action in body.get("actions", []):
        if action.get("action_id") == "cancel_order":
            value_parts = action.get("value", "").split("|")
            if len(value_parts) >= 2:
                original_user_id = value_parts[1]
                break

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
    karma_cost = 1  # Default in case it can't be determined
    if "Water" in original_text:
        karma_cost = 1
    elif "Drip" in original_text:
        karma_cost = 2
    elif "Espresso" in original_text:
        karma_cost = 3
    add_karma(user_id, karma_cost)
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

@app.action("claim_order")
def handle_claim_order(ack, body, client):
    ack()
    user_id = body["user"]["id"]
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
    
    print("🔍 Order text before chat_update:", order_text)
    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"{order_text}\n\n☚️ CLAIMED BY <@{user_id}>",
        blocks=[
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{order_text}\n\n☚️ CLAIMED BY <@{user_id}>"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "MARK AS DELIVERED"},
                        "style": "primary",
                        "value": f"{user_id}",
                        "action_id": "mark_delivered"
                    }
                ]
            }
        ]
    )
    order_ts = body["message"]["ts"]
    order_extras[order_ts]["claimer_id"] = user_id
    order_extras[order_ts]["active"] = False
    order_extras[order_ts]["claimed"] = True
    
    from sheet import update_order_status
    from slack_sdk import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)
    
    # Fetch claimer's real name
    claimer_name = ""
    try:
        user_info = slack_client.users_info(user=user_id)
        claimer_name = user_info["user"]["real_name"]
    except Exception as e:
        print("⚠️ Failed to fetch claimer real name for update:", e)
    
    update_order_status(
        order_id=order_ts,
        status="claimed",
        claimer_id=user_id,
        claimer_name=claimer_name,
        claimed_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    client.chat_postMessage(
        channel=user_id,
        text="You took the mission. Don't forget to hit 'MARK AS DELIVERED' once the goods are dropped."
    )
    def send_completion_reminder():
        try:
            # Fetch the latest version of the message to check if it's already marked as delivered
            current_message = client.conversations_history(channel=body["channel"]["id"], latest=body["message"]["ts"], inclusive=True, limit=1)
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if "Delivered." in msg_text:
                    return  # Already completed
            client.chat_postMessage(
                channel=user_id,
                text="⏰ Heads-up: Your claimed order is still marked as undelivered. Don’t forget to hit *MARK AS DELIVERED* once it’s done!"
            )
        except Exception as e:
            print("⚠️ Failed to send completion reminder:", e)

    import threading
    threading.Timer(900, send_completion_reminder).start()  # 15 minutes
    # Notify the requester that their drink was claimed
    requester_id = None
    for block in original_message.get("blocks", []):
        if block.get("type") == "section":
            text = block.get("text", {}).get("text", "")
            import re
            print("🔍 Trying to extract requester_id from text:", text)
            match = re.search(r"(?:FOR <@.+?> FROM <@([A-Z0-9]+)>|FROM <@([A-Z0-9]+)>)", text.upper())
            if match:
                requester_id = match.group(1) or match.group(2)
                break

    if not requester_id:
        requester_id = original_message.get("user")
        print("⚠️ Fallback: using message['user'] as requester_id:", requester_id)

    client.chat_postMessage(
        channel=requester_id,
        text=f"☕️ Your order was claimed by <@{user_id}>. Hold tight — delivery is on the way."
    )

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
            claimer_id = order_extras.get(order_ts, {}).get("claimer_id")
            if not claimer_id:
                print("⚠️ claimer_id missing for order_ts", order_ts)

            deliverer_id = safe_body.get("user", {}).get("id")
            recipient_id = None
            text_blocks = original_message.get("blocks", [])
            for block in text_blocks:
                if block.get("type") == "section":
                    text = block.get("text", {}).get("text", "")
                    if "New drop for <@" in text:
                        import re
                        match = re.search(r"New drop for <@([A-Z0-9]+)>", text)
                        if match:
                            recipient_id = match.group(1)
                        break
            # Treat sender as recipient if no gift recipient was included
            if not recipient_id:
                for block in text_blocks:
                    if block.get("type") == "section":
                        text = block.get("text", {}).get("text", "")
                        match = re.search(r"New drop from <@([A-Z0-9]+)>", text)
                        if match:
                            recipient_id = match.group(1)
                            break

            if not claimer_id or (deliverer_id != claimer_id and deliverer_id != recipient_id):
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

            # Removed redundant check since claimer_id is now validated above

            # Prevent bonus if claimer is also the original requester
            if claimer_id == recipient_id:
                bonus_multiplier = 1
            else:
                bonus_multiplier = 1
                if random.randint(1, 5) == 1:  # 20% chance
                    bonus_multiplier = random.choice([2, 3])
            points = add_karma(claimer_id, bonus_multiplier)
            print(f"☚️ +{bonus_multiplier} point(s) for {claimer_id}. Total: {points}")

            new_text = (
                f"{order_text}\n\n✅ *DROP COMPLETED*\n"
                f"💥 <@{claimer_id}> EARNED +{bonus_multiplier} KARMA (TOTAL: *{points}*)"
            )

            safe_client.chat_update(
                channel=safe_body["channel"]["id"],
                ts=original_message["ts"],
                text=new_text,
                blocks=[
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": new_text
                        }
                    }
                ]
            )
            safe_client.chat_postMessage(
                channel=safe_body["channel"]["id"],
                thread_ts=original_message["ts"],
                text=":camera_with_flash: Flex the drop. On mobile? Hit the *`+`* and share a shot of your delivery.\nDon’t forget to *check the box* to share it to #koffee-karma-sf. Let the people see what you dropped."
            )
            if bonus_multiplier > 1:
                safe_client.chat_postMessage(
                    channel=safe_body["channel"]["id"],
                    text=f"🎉 *Bonus Karma!* <@{claimer_id}> earned *{bonus_multiplier}x* points for this drop. 🔥"
                )

            safe_client.chat_postMessage(
                channel=claimer_id,
                text=f"Mission complete. +1 Koffee Karma. Balance: *{points}*. Stay sharp."
            )



            from sheet import update_order_status
            update_order_status(
                order_id=order_ts,
                status="delivered",
                delivered_time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                bonus_multiplier=bonus_multiplier
            )
            print("✅ All steps completed successfully")

        except Exception as e:
            print("🚨 Error in mark_delivered thread:", repr(e))

    threading.Thread(target=do_work).start()

@app.command("/karma")
def handle_karma_command(ack, body, client):
    ack()
    user_id = body["user_id"]
    points = get_karma(user_id)
    client.chat_postEphemeral(
        channel=body["channel_id"],
        user=user_id,
        text=f"☚️ You've got *{points} Koffee Karma* — keep the chaos brewing."
    )

@app.command("/leaderboard")
def handle_leaderboard_command(ack, body, client):
    ack()
    leaderboard = get_leaderboard()
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*🏆 Koffee Karma Leaderboard* — The bold, the brewed, the brave."}}
    ]
    for i, row in enumerate(leaderboard, start=1):
        user_line = f"{i}. <@{row['Slack ID']}> — *{row['Karma']}* karma"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": user_line}})
    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=blocks,
    text="The brave rise. Here's the Koffee Karma leaderboard."
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
                    "• `/leaderboard` — See the legends.\n\n"
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

import datetime

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    import threading
    
    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    threading.Thread(target=run_schedule, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=port, threaded=True)