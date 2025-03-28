from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import random
import requests
import os

order_extras = {}


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
                                "text": {"type": "plain_text", "text": "Espresso Drink (latte, cappuccino) — 3 Karma"},
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
    drink_detail = values["drink_detail"]["input"]["value"]
    drink_map = {
        "water": ("Water (still/sparkling)", 1),
        "drip": ("Drip Coffee / Tea", 2),
        "espresso": ("Espresso Drink", 3)
    }
    drink, karma_cost = drink_map[drink_value]
    if drink_detail:
        drink = f"{drink} - {drink_detail}"
    location = values["location"]["input"]["value"]
    notes = values["notes"]["input"]["value"] if "notes" in values else ""
    gifted_id = values["gift_to"]["input"]["selected_user"] if "gift_to" in values and "input" in values["gift_to"] else None
    user_id = body["user"]["id"]
    
    

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
        "*╯°□°）╯︵ ┻━┻* — Brew rebellion.",
        "*// Brewed + Brutal //*",
        "*Wake. Rage. Repeat.* ☕",
        "*（╯°益°）╯彡┻━┻* — Drink the pain away.",
        "*☠️ No cream. No sugar. Just rage.*",
        "*Deadlines & Drip* ☕",
        "*⛓️ Serve or be served.*",
        "*⚠️ Brew responsibly — or don’t.*",
        "*👀 The grind sees all.*",
        "*🥀 Steam. Spite. Salvation.*",
        "*🖤 Emo espresso drop incoming.*"
    ])
    
    full_text = (
        f"{context_line}\n"
        f"☚️ *New drop {'for <@' + gifted_id + '> from <@' + user_id + '>' if gifted_id else 'from <@' + user_id + '>'}*\n"
        f"• *Drink:* {drink}\n"
        f"• *Drop Spot:* {location}\n"
        f"• *Notes:* {notes or 'None'}\n"
        f"Reward: +{karma_cost} Karma to the delivery punk.\n"
        f"⏳ *Time left to claim:* 10 min"
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
        if "order_extras" not in globals():
            global order_extras
            order_extras = {}
        order_extras[order_ts] = {"gif_ts": gif_ts, "context_line": context_line}
 
    deduct_karma(user_id, karma_cost)

    if gifted_id:
        client.chat_postMessage(
            channel=gifted_id,
            text=f"🎁 You’ve been gifted a drink order by <@{user_id}>. Let the koffee flow."
        )

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
            if order_ts in order_extras:
                for extra_ts in order_extras[order_ts]:
                    client.chat_delete(channel=order_channel, ts=extra_ts)
                del order_extras[order_ts]
        except Exception as e:
            print("⚠️ Failed to expire message:", e)

    threading.Timer(600, cancel_unclaimed_order).start()  # 10 minutes
    # Reminder ping halfway through if still unclaimed
    def reminder_ping():
        try:
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if any(phrase in msg_text for phrase in ["Claimed by", "Expired", "Canceled", "Order canceled by"]):
                    return  # Skip reminder if already handled

                # Append the reminder directly to the original message text
                if "⚠️ This mission’s still unclaimed." not in msg_text:
                    updated_text = f"{msg_text}\n\n⚠️ This mission’s still unclaimed. Someone better step up before it expires… ⏳"
                    
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
    def update_countdown(remaining):
        try:
            # Check if order is still active by inspecting the current message text
            current_message = client.conversations_history(channel=order_channel, latest=order_ts, inclusive=True, limit=1)
            if not current_message.get("messages"):
                return
            msg_text = current_message["messages"][0].get("text", "")
            if any(keyword in msg_text for keyword in [
                "Claimed by", "Expired", "Order canceled by", "❌ Order canceled"
            ]):
                return  # Skip countdown updates if order is no longer active
            if remaining > 0:
                context_line = order_extras.get(order_ts, {}).get("context_line", "")
                reminder_text = ""
                if order_extras.get(order_ts, {}).get("reminder_added"):
                    reminder_text = "\n\n⚠️ This mission’s still unclaimed. Someone better step up before it expires… ⏳"
                updated_text = (
                    f"{context_line}\n"
                f"☚️ *New drop {'for <@' + gifted_id + '> from <@' + user_id + '>' if gifted_id else 'from <@' + user_id + '>'}*\n"
                    f"• *Drink:* {drink}\n"
                    f"• *Drop Spot:* {location}\n"
                    f"• *Notes:* {notes or 'None'}\n"
                    f"Reward: +{karma_cost} Karma to the delivery punk.\n"
                    f"⏳ *Time left to claim:* {remaining} min"
                    f"{reminder_text}"
                )
                client.chat_update(
                    channel=order_channel,
                    ts=order_ts,
                    text=updated_text,
                    blocks=[
                        {"type": "divider"},
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
                if remaining > 1:
                    threading.Timer(60, update_countdown, args=(remaining - 1,)).start()
        except Exception as e:
            print("⚠️ Countdown update failed:", e)

    update_countdown(9)  # Start at 9 since initial message shows 10 min


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

    # Stop any further scheduled updates by overwriting the original message with only cancellation info.
    import re
    updated_text = re.sub(r"\n*⏳ \*Time left to claim:\*.*", "", original_text)
    updated_text = re.sub(r"\n*⚠️ This mission’s still unclaimed\..*", "", updated_text)
    updated_text = f"{updated_text}\n\n❌ Order canceled by <@{user_id}>."
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
    order_text = re.sub(r"\n*⏳ \*Time left to claim:\*.*", "", order_text)
    order_text = re.sub(r"\n*⚠️ This mission’s still unclaimed\..*", "", order_text)
    order_text = re.sub(r"\n*📸 \*Flex the drop\..*", "", order_text)

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"{order_text}\n\n☚️ *Claimed by <@{user_id}>* — don't let us down.",
        blocks=[
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{order_text}\n\n☚️ *Claimed by <@{user_id}>*"}
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

    client.chat_postMessage(
        channel=user_id,
        text="You took the mission. Don't forget to hit 'MARK AS DELIVERED' once the goods are dropped."
    )

import threading

@app.action("mark_delivered")
def handle_mark_delivered(ack, body, client):
    ack()
    print("✅ mark_delivered button clicked")

    try:
        safe_body = copy.deepcopy(body)
        safe_client = client
    except Exception as e:
        print("🚨 Error copying body/client:", repr(e))
        return

    def do_work():
        try:
            print("📦 mark_delivered payload:", safe_body)
            original_message = safe_body.get("message", {})
            order_ts = original_message.get("ts")
            claimer_id = order_extras.get(order_ts, {}).get("claimer_id")

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

            bonus_multiplier = 1
            if random.randint(1, 5) == 1:  # 20% chance
                bonus_multiplier = random.choice([2, 3])
            points = add_karma(claimer_id, bonus_multiplier)
            print(f"☚️ +{bonus_multiplier} point(s) for {claimer_id}. Total: {points}")

            new_text = (
                f"{order_text}\n\n✅ *Delivered.* Respect.\n"
                f"☕️ +{bonus_multiplier} Karma for <@{claimer_id}>. New total: *{points}*."
                "\n\n📸 *Flex the drop.* On mobile? Hit the *`+`* and share a shot of your delivery. Let the people see the brew."
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
            if bonus_multiplier > 1:
                safe_client.chat_postMessage(
                    channel=safe_body["channel"]["id"],
                    text=f"🎉 *Bonus Karma!* <@{claimer_id}> earned *{bonus_multiplier}x* points for this drop. 🔥"
                )

            safe_client.chat_postMessage(
                channel=claimer_id,
                text=f"Mission complete. +1 Koffee Karma. Balance: *{points}*. Stay sharp."
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
        {"type": "section", "text": {"type": "mrkdwn", "text": "*🏴 Koffee Karma Leaderboard* — The bold, the brewed, the brave."}}
    ]
    for i, row in enumerate(leaderboard, start=1):
        user_line = f"{i}. <@{row['Slack ID']}> — *{row['Karma']}* Koffee Karma"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": user_line}})
    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=blocks,
    text="The brave rise. Here's the Koffee Karma leaderboard."
    )


@app.action("*")
def catch_all_actions(ack, body):
    ack()
    print("⚠️ Caught an unhandled action:", body.get("actions", [{}])[0].get("action_id"))

@app.event("message")
def handle_join_message_events(body, say, client, event):
    subtype = event.get("subtype")
    
    if subtype == "channel_join":
        user_id = event.get("user")
        channel_id = event.get("channel")

        print(f"👋 Detected join via channel_join: {user_id} joined {channel_id}")

        from sheet import ensure_user
        was_new = ensure_user(user_id)

        if was_new:
            say(f"👋 <@{user_id}> just entered the Koffee Karma zone. Show no mercy. ☕️")
            client.chat_postMessage(
                channel=user_id,
                text=(
                "Welcome to *Koffee Karma* ☕️💀\n\n"
                    "Here’s how it works:\n"
                    "• `/order` — Request a drink (costs Karma).\n"
                    "• `/karma` — Check your Karma.\n"
                    "• `/leaderboard` — See the legends.\n\n"
                    "You’ve got *3 Karma points* to start. Spend wisely. Earn more by delivering orders.\n"
                    "Let the chaos begin. ⚡️"
                )
            )

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
    flask_app.run(host="0.0.0.0", port=port)
