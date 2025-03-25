import gspread
from google.oauth2.service_account import Credentials

# Connect to the Google Sheet
def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file("coffee-karma-454723-c8fc1078d17e.json", scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open("Coffee Karma").sheet1  # Make sure the name matches your sheet

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