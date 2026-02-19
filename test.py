from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/documents"]
SERVICE_ACCOUNT_FILE = "service_account.json"

credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('docs', 'v1', credentials=credentials)

DOC_ID = "10C13XOhmesLbimd-HB4FjJR1dB6yJmFvu2hF5nDuS7o"  # remplace par ton doc id réel

doc = service.documents().get(documentId=DOC_ID).execute()
print("Titre du doc :", doc.get("title"))