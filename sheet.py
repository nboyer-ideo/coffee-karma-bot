import gspread
from google.oauth2.service_account import Credentials
import datetime

# Connect to the Koffee Karma Google Sheet
import os
import json
from io import StringIO

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    creds_info = json.loads(os.environ["GOOGLE_CREDS_JSON"])
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    
    gc = gspread.authorize(creds)
    return gc.open("Koffee Karma")

# Add or update Koffee Karma for a user
def add_karma(user_id, points_to_add=1):
    worksheet = get_sheet().worksheet("Leaderboard")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = int(row["Karma"]) + points_to_add
                worksheet.update_cell(i + 2, 2, new_total)
            return new_total
    # If user not found, add a new row
    worksheet.append_row(["Unknown", points_to_add, user_id])
    return points_to_add

# Deduct Koffee Karma for a user
def deduct_karma(user_id, points_to_deduct=1):
    worksheet = get_sheet().worksheet("Leaderboard")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = max(0, int(row["Karma"]) - points_to_deduct)
                worksheet.update_cell(i + 2, 2, new_total)
            return new_total
    return 0

# Get current Koffee Karma balance
def get_karma(user_id):
    worksheet = get_sheet().worksheet("Leaderboard")
    data = worksheet.get_all_records()
    for row in data:
        if row["Slack ID"] == user_id:
            return int(row["Karma"])
    return 0

def get_leaderboard(top_n=5):
    worksheet = get_sheet().worksheet("Leaderboard")
    data = worksheet.get_all_records()
    # Sort users by "Karma" (ensure header case matches Koffee Karma headers)
    sorted_users = sorted(data, key=lambda x: int(x["Karma"]), reverse=True)
    return sorted_users[:top_n]

def reset_karma_sheet():
    worksheet = get_sheet().worksheet("Leaderboard")
    data = worksheet.get_all_records()
    for i, row in enumerate(data):
        worksheet.update_cell(i + 2, 2, 0)

def ensure_user(user_id):
    from slack_sdk import WebClient
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    slack_client = WebClient(token=slack_token)

    sheet = get_sheet()
    data = sheet.get_all_records()
    for row in data:
        if row.get("Slack ID") == user_id:
            return False  # Already exists

    user_info = slack_client.users_info(user=user_id)
    real_name = user_info["user"]["real_name"]
    sheet.append_row([real_name, 3, user_id])
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
                        return "expired"
                except ValueError:
                    pass  # ignore bad date formats
 
            # Check how many people have already redeemed this code
            used_ids = set()
            for r in data:
                if r["Code"] == code and r.get("Slack ID"):
                    used_ids.add(r["Slack ID"])
            if user_id in used_ids:
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
 
            # Award points
            try:
                points = int(row.get("Value", 1))
            except ValueError:
                points = 1
 
            add_karma(user_id, points)
            return f"success:{points}"
    return False

def log_order_to_sheet(order_data):
    try:
        sheet = get_sheet()
    worksheet = sheet.worksheet("Order Log")  # Headers: Order ID, Timestamp, Requester ID, Requester Name, Claimer ID, Claimer Name, Recipient ID, Recipient Name, Drink, Location, Notes, Karma Cost, Status, Bonus Multiplier, Ordered Time, Claimed Time, Delivered Time
        worksheet.append_row([
            order_data.get("order_id", ""),
            order_data.get("timestamp", ""),
            order_data.get("requester_id", ""),
            order_data.get("requester_real_name", ""),
            order_data.get("claimer_id", ""),
            order_data.get("claimer_real_name", ""),
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
    except Exception as e:
        print("⚠️ Failed to log order to sheet:", e)

def update_order_status(order_id, status=None, claimer_id=None, claimer_name=None, bonus_multiplier=None, claimed_time=None, delivered_time=None, requester_name=None, recipient_name=None):
    try:
        sheet = get_sheet()
        worksheet = sheet.worksheet("Order Log")
        data = worksheet.get_all_records()
        for i, row in enumerate(data):
            if row.get("Order ID") == order_id:
                if status is not None:
                    worksheet.update_cell(i + 2, 13, status)
                if claimer_id is not None:
                    worksheet.update_cell(i + 2, 5, claimer_id)
                if claimer_name is not None:
                    worksheet.update_cell(i + 2, 6, claimer_name)
                if bonus_multiplier is not None:
                    worksheet.update_cell(i + 2, 14, bonus_multiplier)
                if claimed_time is not None:
                    worksheet.update_cell(i + 2, 15, claimed_time)
                if delivered_time is not None:
                    worksheet.update_cell(i + 2, 16, delivered_time)
                if requester_name is not None:
                    worksheet.update_cell(i + 2, 4, requester_name)
                if recipient_name is not None:
                    worksheet.update_cell(i + 2, 8, recipient_name)
                return True
    except Exception as e:
        print("⚠️ Failed to update order status:", e)
    return False