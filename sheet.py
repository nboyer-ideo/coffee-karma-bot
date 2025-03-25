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
        if row["user_id"] == user_id:
            new_total = int(row["points"]) + points_to_add
            sheet.update_cell(i + 2, 2, new_total)
            return new_total
    # If user not found, add a new row
    sheet.append_row([user_id, points_to_add])
    return points_to_add

# Get current balance
def get_karma(user_id):
    sheet = get_sheet()
    data = sheet.get_all_records()
    for row in data:
        if row["user_id"] == user_id:
            return int(row["points"])
    return 0

def get_leaderboard(top_n=5):
    sheet = get_sheet()
    data = sheet.get_all_records()
    sorted_users = sorted(data, key=lambda x: int(x["points"]), reverse=True)
    return sorted_users[:top_n]