from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GoogleSheetsConnector:
    def __init__(self, credentials: Credentials):
        self.sheets = build("sheets", "v4", credentials=credentials)

    def get_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        result = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        ).execute()
        return result.get("values", [])

    def update_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[str]],
    ) -> dict:
        body = {"values": values}
        return self.sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()

    def append_values(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: list[list[str]],
    ) -> dict:
        body = {"values": values}
        return self.sheets.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()

    def create_spreadsheet(self, title: str) -> dict:
        body = {"properties": {"title": title}}
        return self.sheets.spreadsheets().create(
            body=body,
            fields="spreadsheetId,spreadsheetUrl",
        ).execute()
