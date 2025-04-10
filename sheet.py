import os
import json
import gspread
from google.oauth2.service_account import Credentials
import datetime

from io import StringIO

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

def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDS_JSON", "")
    if not creds_json:
        raise Exception("Missing GOOGLE_CREDS_JSON environment variable.")

    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open("Koffee Karma")



# Add or update Koffee Karma for a user
def add_karma(user_id, points_to_add=1):
    print(f"📈 Adding {points_to_add} karma to {user_id}")
    worksheet = get_sheet().worksheet("Player Data")
    print("🧮 Leaderboard worksheet loaded.")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = int(row["Karma"]) + points_to_add
            print(f"📈 Updating karma for {user_id} to {new_total}")
            worksheet.update_cell(i + 2, 3, new_total)
            worksheet.update_cell(i + 2, 4, get_title(new_total))
            print("✅ Karma updated in sheet.")
            return new_total
    else:
        print("⚠️ User not found in sheet. Appending new row.")
    worksheet.append_row([user_id, "Unknown", points_to_add, get_title(points_to_add)])
    return points_to_add

# Deduct Koffee Karma for a user
def deduct_karma(user_id, points_to_deduct=1):
    print(f"📉 Deducting {points_to_deduct} karma from {user_id}")
    worksheet = get_sheet().worksheet("Player Data")
    print("📉 Leaderboard worksheet loaded for deduction.")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = max(0, int(row["Karma"]) - points_to_deduct)
            print(f"📉 Deducting karma for {user_id} to {new_total}")
            worksheet.update_cell(i + 2, 3, new_total)
            worksheet.update_cell(i + 2, 4, get_title(new_total))
            print("✅ Karma updated in sheet.")
            return new_total
    else:
        print("⚠️ User not found when deducting karma.")
    return 0

# Get current Koffee Karma balance
def get_karma(user_id):
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for row in data:
        if row["Slack ID"] == user_id:
            return int(row.get("Karma", 0))
    return 0

def get_leaderboard(top_n=5):
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    # Sort users by "Karma" (ensure header case matches Koffee Karma headers)
    sorted_users = sorted(data, key=lambda x: int(x.get("Karma", 0)), reverse=True)
    return sorted_users[:top_n]

def reset_karma_sheet():
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        worksheet.update_cell(i + 2, 3, 0)

def ensure_user(user_id):

    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for row in data:
        if row.get("Slack ID") == user_id:
            return False  # Already exists

    user_info = slack_client.users_info(user=user_id)
    real_name = user_info["user"]["real_name"]
    worksheet.append_row([user_id, real_name, 3, get_title(3)])
    return True

def mark_code_redeemed(code, user_id):
    sheet = get_sheet()
    worksheet = sheet.worksheet("Redemption Codes")
    data = worksheet.get_all_records(head=1)
    for i, row in enumerate(data):
        if row["Code"] == code:
            # Check if the code is expired
            if row.get("Expires"):
                try:
                    expiry_date = datetime.datetime.strptime(row["Expires"], "%Y-%m-%d")
                    if expiry_date < datetime.datetime.now():
                        from slack_sdk import WebClient
                        slack_token = os.environ.get("SLACK_BOT_TOKEN")
                        slack_client = WebClient(token=slack_token)
                        slack_client.chat_postMessage(channel=user_id, text="§ CODE EXPIRED. NO KARMA GRANTED.")
                        return "expired"
                except ValueError:
                    pass  # ignore bad date formats
 
            # Check how many people have already redeemed this code
            used_ids = set()
            for r in data:
                if r["Code"] == code and r.get("Slack ID"):
                    used_ids.add(r["Slack ID"])
            if user_id in used_ids:
                from slack_sdk import WebClient
                slack_token = os.environ.get("SLACK_BOT_TOKEN")
                slack_client = WebClient(token=slack_token)
                slack_client.chat_postMessage(channel=user_id, text="§ CODE ALREADY USED. NO KARMA GRANTED.")
                return "already_used"
 
            try:
                points = int(row.get("Value", 1))
            except ValueError:
                points = 1

            try:
                max_redemptions = int(row.get("Redemptions", 1))
            except ValueError:
                max_redemptions = 1

            redemptions_left = max_redemptions - len([r for r in data if r["Code"] == code and r.get("Slack ID")])
            if redemptions_left <= 0:
                from slack_sdk import WebClient
                slack_token = os.environ.get("SLACK_BOT_TOKEN")
                slack_client = WebClient(token=slack_token)
                slack_client.chat_postMessage(channel=user_id, text="§ CODE LIMIT REACHED. NO KARMA GRANTED.")
                return "limit_reached"
 
            from slack_sdk import WebClient
            slack_token = os.environ.get("SLACK_BOT_TOKEN")
            slack_client = WebClient(token=slack_token)
            user_info = slack_client.users_info(user=user_id)
            real_name = user_info["user"]["real_name"]
 
            # Update row with redemption info
            worksheet.update_cell(i + 2, 5, True)  # Redeemed
            worksheet.update_cell(i + 2, 6, real_name)  # Redeemed By
            worksheet.update_cell(i + 2, 7, user_id)  # Slack ID
            worksheet.update_cell(i + 2, 8, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))  # Timestamp
            # Ensure bonus_multiplier is stored as a plain number (1, 2, or 3) without emojis,
            # in case it is used elsewhere in the code.
            bonus_multiplier = row.get("Bonus Multiplier", "1")
            try:
                bonus_multiplier = int(bonus_multiplier)
            except ValueError:
                bonus_multiplier = 1
 
            # Award points
            try:
                points = int(row.get("Value", 1))
            except ValueError:
                points = 1
 
            add_karma(user_id, points)
            slack_client.chat_postMessage(
                channel=user_id,
                text=f"¤ CODE REDEEMED. +{points} KARMA ADDED TO YOUR BALANCE."
            )
            return f"success:{points}"
    return False

def log_order_to_sheet(order_data):
    print("🟡 Starting log_order_to_sheet")
    # Only log initial orders (status 'pending'); skip updates for claimed or delivered orders.
    if order_data.get("status", "pending") != "pending":
        print("ℹ️ Order status is not pending; skipping initial logging.")
        return

    try:
        sheet = get_sheet()
        print("📝 Logging order data:", order_data)
        worksheet = sheet.worksheet("Order Log")  # Headers: Order ID, Timestamp, Requester ID, Requester Name, Runner ID, Runner Name, Recipient ID, Recipient Name, Drink, Location, Notes, Karma Cost, Status, Bonus Multiplier, Ordered Time, Claimed Time, Delivered Time
        print("📒 Retrieved Order Log worksheet successfully.")
        print("🧾 Order Log worksheet loaded. Attempting to append row.")
        print("✅ Accessed Order Log worksheet")
        from slack_sdk import WebClient
        slack_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_client = WebClient(token=slack_token)
        if not order_data.get("requester_real_name"):
            try:
                user_info = slack_client.users_info(user=order_data["requester_id"])
                order_data["requester_real_name"] = user_info["user"]["real_name"]
            except Exception as e:
                print("⚠️ Failed to fetch requester real name:", e)

        if not order_data.get("recipient_real_name") and order_data.get("recipient_id"):
            try:
                recipient_info = slack_client.users_info(user=order_data["recipient_id"])
                order_data["recipient_real_name"] = recipient_info["user"]["real_name"]
            except Exception as e:
                print("⚠️ Failed to fetch recipient real name:", e)

        if not order_data.get("runner_real_name") and order_data.get("runner_id"):
            try:
                runner_info = slack_client.users_info(user=order_data["runner_id"])
                order_data["runner_real_name"] = runner_info["user"]["real_name"]
            except Exception as e:
                print("⚠️ Failed to fetch runner real name:", e)

        try:
            worksheet.append_row([
                order_data.get("order_id", ""),
                order_data.get("timestamp", ""),
                "runner" if order_data.get("runner_id") else "requester",
                order_data.get("requester_id", ""),
                order_data.get("requester_real_name", ""),
                order_data.get("runner_id", ""),
                order_data.get("runner_name", ""),
                order_data.get("recipient_id", ""),
                order_data.get("recipient_real_name", ""),
                order_data.get("drink", ""),
                order_data.get("location", ""),
                order_data.get("notes", ""),
                order_data.get("karma_cost", ""),
                order_data.get("status", ""),
                order_data.get("bonus_multiplier", ""),
                order_data.get("time_ordered", ""),
                order_data.get("time_claimed", ""),
                order_data.get("time_delivered", "")
            ])
            print("✅ Order successfully appended to sheet")
        except Exception as log_error:
            print("🚨 Error appending order to sheet:", log_error)
    except Exception as e:
        print("⚠️ Failed to log order to sheet:", e)

def update_order_status(order_id, status=None, runner_id=None, runner_name=None, bonus_multiplier=None, claimed_time=None, delivered_time=None, requester_name=None, recipient_name=None):
    try:
        sheet = get_sheet()
        worksheet = sheet.worksheet("Order Log")
        data = worksheet.get_all_records()
        for i, row in enumerate(data):
            if str(row.get("Order ID")) == str(order_id):
                if status is not None:
                    worksheet.update_cell(i + 2, 14, status)
                if runner_id is not None:
                    worksheet.update_cell(i + 2, 6, runner_id)  # Runner ID
                    if runner_name is not None:
                        worksheet.update_cell(i + 2, 7, runner_name)  # Runner Name
                        worksheet.update_cell(i + 2, 6, runner_id)  # Runner ID (redundantly ensure it's also set correctly here)
                if bonus_multiplier is not None:
                    bonus_multiplier = int(bonus_multiplier) if str(bonus_multiplier).isdigit() else 1
                    worksheet.update_cell(i + 2, 15, str(bonus_multiplier))
                if claimed_time is not None:
                    worksheet.update_cell(i + 2, 17, claimed_time)
                if delivered_time is not None:
                    worksheet.update_cell(i + 2, 18, delivered_time)
                if requester_name is not None:
                    worksheet.update_cell(i + 2, 5, requester_name)
                if recipient_name is not None:
                    worksheet.update_cell(i + 2, 9, recipient_name)
                return True
    except Exception as e:
        print("⚠️ Failed to update order status:", e)
    return False

def refresh_titles():
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        current_karma = int(row.get("Karma", 0))
        current_title = get_title(current_karma)
        worksheet.update_cell(i + 2, 4, current_title)
    print("✅ All titles refreshed based on current Karma.")

def get_runner_capabilities(user_id):
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for row in data:
        if row.get("Slack ID") == user_id:
            capabilities_raw = row.get("Capabilities", "")
            if not capabilities_raw or not isinstance(capabilities_raw, str):
                capabilities_raw = "[]"
            if capabilities_raw is None or not str(capabilities_raw).strip():
                return {"Capabilities": []}
            try:
                row["Capabilities"] = json.loads(capabilities_raw)
            except json.JSONDecodeError:
                row["Capabilities"] = []
            row["Capabilities"] = row.get("Capabilities", [])
            if row["Capabilities"] is None:
                row["Capabilities"] = []
            print(f"✅ Found runner capabilities for {user_id}: {row}")
            if "Name" not in row or not row["Name"]:
                row["Name"] = f"<@{user_id}>"
            return row
    print(f"❌ No runner capabilities found for {user_id}")
    print(f"📭 Returning default capabilities for {user_id}")
    return {"Name": f"<@{user_id}>", "Capabilities": []}

def save_runner_capabilities(user_id, name, capabilities):
    worksheet = get_sheet().worksheet("Player Data")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        if row.get("Slack ID") == user_id:
            worksheet.update_cell(i + 2, 2, name)
            worksheet.update_cell(i + 2, 5, json.dumps(capabilities))
            return
    worksheet.append_row([user_id, name, 3, get_title(3), json.dumps(capabilities)])

def fetch_order_data(order_id):
    try:
        sheet = get_sheet()
        worksheet = sheet.worksheet("Order Log")
        data = worksheet.get_all_records()
        for row in data:
            if str(row.get("Order ID", "")).strip() == str(order_id).strip():
                return {
                    "order_id": row.get("Order ID", ""),
                    "timestamp": row.get("Timestamp", ""),
                    "initiated_by": row.get("Initiated By", ""),
                    "requester_id": row.get("Requester ID", ""),
                    "requester_real_name": row.get("Requester Name", ""),
                    "runner_id": row.get("Runner ID", ""),
                    "runner_name": row.get("Runner Name", ""),
                    "recipient_id": row.get("Recipient ID", ""),
                    "recipient_real_name": row.get("Recipient Name", ""),
                    "drink": row.get("Drink", ""),
                    "location": row.get("Location", ""),
                    "notes": row.get("Notes", ""),
                    "karma_cost": int(row.get("Karma Cost", 1)),
                    "status": row.get("Status", ""),
                    "bonus_multiplier": row.get("Bonus Multiplier", ""),
                    "time_ordered": row.get("Ordered Time", ""),
                    "time_claimed": row.get("Claimed Time", ""),
                "time_delivered": row.get("Delivered Time", ""),
                "claimed_by": row.get("Runner Name", ""),
            }
    except Exception as e:
        print(f"⚠️ Failed to fetch order data from sheet for order_id {order_id}:", e)
    return {}

