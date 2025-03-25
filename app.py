from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from flask import Flask, request
import os
import random

CELEBRATION_GIFS = [
    "https://media.giphy.com/media/3o6ZtpxSZbQRRnwCKQ/giphy.gif",
    "https://media.giphy.com/media/111ebonMs90YLu/giphy.gif",
    "https://media.giphy.com/media/1Ai5Yzm5FCOgM/giphy.gif",
    "https://media.giphy.com/media/3o6Zt8MgUuvSbkZYWc/giphy.gif",
    "https://media.giphy.com/media/3o7abldj0b3rxrZUxW/giphy.gif",
    "https://media.giphy.com/media/5xaOcLGvzHxDKjufnLW/giphy.gif",
    "https://media.giphy.com/media/l0MYEqEzwMWFCg8rm/giphy.gif",
    "https://media.giphy.com/media/3o7TKu8RvQuomFfUUU/giphy.gif"
]

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
            "callback_id": "coffee_request_modal",
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

@app.view("coffee_request_modal")
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
            text="🚫 You don't have enough Coffee Karma to place an order. Deliver drinks to earn more."
        )
        return

    posted = client.chat_postMessage(
        channel="#coffee-karma-sf",
        text=f"☚️ New drop from <@{gifted_id or user_id}>\n• *Drink:* {drink}\n• *Drop Spot:* {location}\n• *Notes:* {notes or 'None'}\n\nCost: {karma_cost} Karma. Claim it. Make it. Deliver it.\n⏳ *Time left to claim:* 10 min",
        blocks=[
            {
                "type": "divider"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": random.choice([
                            "⚡ Another one in the queue...",
                            "💀 A fresh order just dropped.",
                            "☕ New round. Who’s got the grind?",
                            "🔥 Brew alert. Who’s stepping up?",
                            "🚨 Another caffeine cry for help."
                        ])
                    }
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"☚️ *New drop from <@{gifted_id or user_id}>*\n• *Drink:* {drink}\n• *Drop Spot:* {location}\n• *Notes:* {notes or 'None'}\n⏳ *Time left to claim:* 10 min\n\n📸 *Flex the drop.* On mobile? Hit the *`+`* and share a shot of your delivery. Let the people see the brew."}
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

    deduct_karma(user_id, karma_cost)

    if gifted_id:
        client.chat_postMessage(
            channel=gifted_id,
            text=f"🎁 You’ve been gifted a drink order by <@{user_id}>. Let the coffee flow."
        )

    # Start countdown timer for order expiration
    import threading
    def cancel_unclaimed_order():
        try:
            client.chat_update(
                channel=posted["channel"],
                ts=posted["ts"],
                text=f"{posted['text']}\n\n❌ This order expired. No one claimed it in time.",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"{posted['text']}\n\n❌ *Expired.* No one stepped up."}
                    }
                ]
            )
        except Exception as e:
            print("⚠️ Failed to expire message:", e)

    threading.Timer(600, cancel_unclaimed_order).start()  # 10 minutes
    # Reminder ping halfway through if still unclaimed
    def reminder_ping():
        try:
            current_message = client.conversations_history(channel=posted["channel"], latest=posted["ts"], inclusive=True, limit=1)
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if "Claimed by" in msg_text or "Expired" in msg_text or "Canceled" in msg_text:
                    return  # Skip reminder if already handled

                # Append the reminder directly to the original message text
                if "⚠️ This mission’s still unclaimed." not in msg_text:
                    updated_text = f"{msg_text}\n\n⚠️ This mission’s still unclaimed. Someone better step up before it expires… ⏳"
                    
                    client.chat_update(
                        channel=posted["channel"],
                        ts=posted["ts"],
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
            current_message = client.conversations_history(channel=posted["channel"], latest=posted["ts"], inclusive=True, limit=1)
            if current_message["messages"]:
                msg_text = current_message["messages"][0].get("text", "")
                if "Claimed by" in msg_text or "Expired" in msg_text:
                    return  # Order no longer actionable
            if remaining > 0:
                updated_text = f"☚️ New drop from <@{gifted_id or user_id}>\n• *Drink:* {drink}\n• *Drop Spot:* {location}\n• *Notes:* {notes or 'None'}\n⏳ *Time left to claim:* {remaining} min"
                client.chat_update(
                    channel=posted["channel"],
                    ts=posted["ts"],
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
                threading.Timer(60, update_countdown, args=(remaining - 1,)).start()
        except Exception as e:
            print("⚠️ Countdown update failed:", e)

    update_countdown(9)  # Start at 9 since initial message shows 10 min

    # Occasionally inject some visual spice
    if random.randint(1, 2) == 1:  # 50% chance
        extras = [
            {
                "type": "image",
                "image_url": random.choice([
                    "https://media.giphy.com/media/3oriO0OEd9QIDdllqo/giphy.gif",
                    "https://media.giphy.com/media/3o7qE1YN7aBOFPRw8E/giphy.gif",
                    "https://media.giphy.com/media/l0MYEqEzwMWFCg8rm/giphy.gif",
                    "https://media.giphy.com/media/xT0GqeSlGSRQut4C2Q/giphy.gif"
                ]),
                "alt_text": "coffee chaos"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": random.choice([
                            "```\n  ☕\n (╯°□°）╯︵ ┻━┻\n```",
                            "```\n  //\\ ☠️ \n c''☕️\n```",
                            "```\nIDE☕O forever.\n// brewed + brutal //\n```",
                            "> *Drink deep, punk. Coffee waits for no one.*"
                        ])
                    }
                ]
            }
        ]
        for block in extras:
            client.chat_postMessage(
                channel="#coffee-karma-sf",
                blocks=[block],
                text="Coffee chaos drop"
            )

@app.action("cancel_order")
def handle_cancel_order(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    message = body["message"]
    original_text = message["blocks"][0]["text"]["text"] if message["blocks"] else ""

    if f"<@{user_id}>" not in original_text:
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

    client.chat_update(
        channel=body["channel"]["id"],
        ts=message["ts"],
        text=f"{original_text}\n\n❌ Order canceled by <@{user_id}>.",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{original_text}\n\n❌ *Canceled by <@{user_id}>.*"}
            }
        ]
    )

@app.action("claim_order")
def handle_claim_order(ack, body, client, say):
    ack()
    user_id = body["user"]["id"]
    original_message = body["message"]
    order_text = original_message["blocks"][0]["text"]["text"]
    # Remove "Time left to claim" if it's still there
    if "⏳ *Time left to claim:*" in order_text:
        order_text = order_text.split("⏳ *Time left to claim:*")[0].strip()
    if "⚠️ This mission’s still unclaimed." in order_text:
        order_text = order_text.split("⚠️ This mission’s still unclaimed.")[0].strip()

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"{order_text}\n\n☚️ *Claimed by <@{user_id}>* — don't let us down.",
        blocks=[
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
import copy

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

            claimer_id = safe_body.get("user", {}).get("id")
            original_message = safe_body.get("message", {})
            order_text = original_message.get("blocks", [{}])[0].get("text", {}).get("text", "??")

            if not claimer_id:
                print("🚨 No claimer_id found.")
                return

            points = add_karma(claimer_id, 1)
            print(f"☚️ +1 point for {claimer_id}. Total: {points}")

            safe_client.chat_update(
                channel=safe_body["channel"]["id"],
                ts=original_message["ts"],
                text=f"{order_text}\n\n✅ Claimed by <@{claimer_id}> and *delivered*. Respect earned.",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{order_text}\n\n✅ *Delivered by <@{claimer_id}>* — Respect."
                        }
                    }
                ]
            )

            safe_client.chat_postMessage(
                channel=claimer_id,
                text=f"Mission complete. +1 Coffee Karma. Balance: *{points}*. Stay sharp."
            )


            # Occasionally drop some visual grit after completion
            if random.randint(1, 4) == 1:  # 25% chance
                extras = [
                    {
                        "type": "image",
                        "image_url": random.choice([
                            "https://media.giphy.com/media/xT0GqeSlGSRQut4C2Q/giphy.gif",
                            "https://media.giphy.com/media/3o7qE1YN7aBOFPRw8E/giphy.gif",
                            "https://media.giphy.com/media/3oriO0OEd9QIDdllqo/giphy.gif"
                        ]),
                        "alt_text": "gritty coffee punk"
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": random.choice([
                                    "```\n☠️ Job done. Brew dropped.\n```",
                                    "```\n+1 Karma. No mercy.\n```",
                                    "> *Finished like a legend.*"
                                ])
                            }
                        ]
                    }
                ]
                for block in extras:
                    safe_client.chat_postMessage(
                        channel=safe_body["channel"]["id"],
                        blocks=[block],
                        text="Post-delivery drop"
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
        text=f"☚️ You've got *{points} Coffee Karma* — keep the chaos brewing."
    )

@app.command("/leaderboard")
def handle_leaderboard_command(ack, body, client):
    ack()
    leaderboard = get_leaderboard()
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*🏴 Coffee Karma Leaderboard* — The bold, the brewed, the brave."}}
    ]
    for i, row in enumerate(leaderboard, start=1):
        user_line = f"{i}. <@{row['user_id']}> — *{row['points']}* pts"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": user_line}})
    client.chat_postMessage(
        channel=body["channel_id"],
        blocks=blocks,
        text="The brave rise. Here's the Coffee Karma leaderboard."
    )

import os

@app.action("*")
def catch_all_actions(ack, body):
    ack()
    print("⚠️ Caught an unhandled action:", body.get("actions", [{}])[0].get("action_id"))

@app.event("member_joined_channel")
def welcome_new_user(event, client):
    user_id = event.get("user")
    channel_id = event.get("channel")

    # Give them their 3 starter points (only if new)
    was_new = ensure_user(user_id)

    if was_new:
        # Public welcome shoutout
        client.chat_postMessage(
            channel=channel_id,
            text=f"👋 <@{user_id}> just entered the Coffee Karma zone. Show no mercy. ☕️"
        )

        # DM the new user with instructions
        client.chat_postMessage(
            channel=user_id,
            text=(
                "Welcome to *Coffee Karma* ☕️💀\n\n"
                "Here’s how it works:\n"
                "• `/order` — Request a drink (costs Karma).\n"
                "• `/karma` — Check your Karma.\n"
                "• `/leaderboard` — See the legends.\n\n"
                "You’ve got *3 Karma points* to start. Spend wisely. Earn more by delivering orders.\n"
                "Let the chaos begin. ⚡️"
            )
        )

import datetime
import schedule
import time

def reset_leaderboard():
    from sheet import reset_karma_sheet
    print("🔁 Resetting leaderboard...")
    reset_karma_sheet()

def start_scheduler():
    schedule.every().monday.at("07:00").do(reset_leaderboard)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=start_scheduler, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)
