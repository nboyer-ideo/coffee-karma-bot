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
    return gc.open("Koffee Karma").worksheet("Leaderboard")

# Add or update Koffee Karma for a user
def add_karma(user_id, points_to_add=1):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = int(row["Karma"]) + points_to_add
            sheet.update_cell(i + 2, 2, new_total)
            return new_total
    # If user not found, add a new row
    sheet.append_row(["Unknown", points_to_add, user_id])
    return points_to_add

# Deduct Koffee Karma for a user
def deduct_karma(user_id, points_to_deduct=1):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = max(0, int(row["Karma"]) - points_to_deduct)
            sheet.update_cell(i + 2, 2, new_total)
            return new_total
    return 0

# Get current Koffee Karma balance
def get_karma(user_id):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for row in data:
        if row["Slack ID"] == user_id:
            return int(row["Karma"])
    return 0

def get_leaderboard(top_n=5):
    sheet = get_sheet()
    data = sheet.get_all_records()
    # Sort users by "Karma" (ensure header case matches Koffee Karma headers)
    sorted_users = sorted(data, key=lambda x: int(x["Karma"]), reverse=True)
    return sorted_users[:top_n]

def reset_karma_sheet():
    sheet = get_sheet()
    data = sheet.get_all_records()
    for i, row in enumerate(data):
        sheet.update_cell(i + 2, 2, 0)

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
    worksheet = get_sheet().worksheet("Redemption Codes")
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
 
            max_redemptions = int(row.get("Redemptions", 1))
            if len(used_ids) >= max_redemptions:
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
            worksheet.update_cell(i + 2, 3, redemptions_left - 1)  # Decrement redemptions

            # Check for Value column to determine points to award (customizable per row)
            try:
                points = int(row.get("Value", 1))
            except ValueError:
                points = 1  # fallback if value is not a number

            add_karma(user_id, points)
            return f"success:{points}"
    return False
