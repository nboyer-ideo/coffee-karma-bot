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

from sheet import add_karma, get_karma, get_leaderboard

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
    if request.is_json:
        if "challenge" in request.json:
            return jsonify({"challenge": request.json["challenge"]})
        return handler.handle(request)
    else:
        return handler.handle(request)

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
                    "block_id": "drink_type",
                    "label": {"type": "plain_text", "text": "What's the brew?"},
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
    drink = values["drink_type"]["input"]["value"]
    location = values["location"]["input"]["value"]
    notes = values["notes"]["input"]["value"] if "notes" in values else ""
    user_id = body["user"]["id"]

    client.chat_postMessage(
        channel="#coffee-karma-sf",
        text=f"☚️ New mission from <@{user_id}>\n• *Drink:* {drink}\n• *Drop Spot:* {location}\n• *Notes:* {notes or 'None'}\n\nClaim it. Make it. Deliver it.",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"☚️ *New drop from <@{user_id}>*\n• *Drink:* {drink}\n• *Drop Spot:* {location}\n• *Notes:* {notes or 'None'}"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "CLAIM THIS MISSION"},
                        "value": f"{user_id}|{drink}|{location}",
                        "action_id": "claim_order"
                    }
                ]
            }
        ]
    )

@app.action("claim_order")
def handle_claim_order(ack, body, client, say):
    ack()
    user_id = body["user"]["id"]
    original_message = body["message"]
    order_text = original_message["blocks"][0]["text"]["text"]

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

    safe_body = copy.deepcopy(body)
    safe_client = client

    def do_work():
        try:
            claimer_id = safe_body["user"]["id"]
            original_message = safe_body["message"]
            order_text = original_message["blocks"][0]["text"]["text"]

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

            celebration_gif = random.choice(CELEBRATION_GIFS)

            safe_client.chat_postMessage(
                channel=claimer_id,
                blocks=[
                    {
                        "type": "image",
                        "image_url": celebration_gif,
                        "alt_text": "coffee celebration"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Mission complete. +1 *Coffee Karma*. Total: *{points}* ☕"
                        }
                    }
                ],
                text="Delivery complete."
            )

        except Exception as e:
            print("🚨 Error in mark_delivered thread:", e)

    threading.Thread(target=do_work).start()

    client.chat_postMessage(
        channel=body["channel"]["id"],
        text="📸 Time to flex that delivery.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "📸 *Flex the drop.*\n"
                        "On mobile? Hit the *`+`* and share a shot of your delivery. Let's see the goods."
                    )
                }
            }
        ]
    )

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    flask_app.run(host="0.0.0.0", port=port)
