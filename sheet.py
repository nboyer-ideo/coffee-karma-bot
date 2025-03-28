import gspread
from google.oauth2.service_account import Credentials

# Connect to the Google Sheet
import os
import json
from io import StringIO
import gspread
from google.oauth2.service_account import Credentials

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # Load the service account JSON from an environment variable
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise Exception("Missing GOOGLE_CREDS_JSON environment variable")
    
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    gc = gspread.authorize(creds)
    return gc.open("Coffee Karma").sheet1

# Add or update points for a user
def add_karma(user_id, points_to_add=1):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = int(row["Points"]) + points_to_add
            sheet.update_cell(i + 2, 2, new_total)
            return new_total
    # If user not found, add a new row
    sheet.append_row(["Unknown", points_to_add, user_id])
    return points_to_add

# Deduct points for a user
def deduct_karma(user_id, points_to_deduct=1):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for i, row in enumerate(data):
        if row["Slack ID"] == user_id:
            new_total = max(0, int(row["Points"]) - points_to_deduct)
            sheet.update_cell(i + 2, 2, new_total)
            return new_total
    return 0

# Get current balance
def get_karma(user_id):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for row in data:
        if row["Slack ID"] == user_id:
            return int(row["Points"])
    return 0

def get_leaderboard(top_n=5):
    sheet = get_sheet()
    data = sheet.get_all_records()
    sorted_users = sorted(data, key=lambda x: int(x["points"]), reverse=True)
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