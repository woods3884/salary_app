
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

def upload_pdf_to_drive(buffer, filename, drive_folder_id=None):
    credentials = service_account.Credentials.from_service_account_file(
        'service_account.json',
        scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=credentials)

    file_metadata = {'name': filename}
    if drive_folder_id:
        file_metadata['parents'] = [drive_folder_id]

    media = MediaIoBaseUpload(buffer, mimetype='application/pdf')
    uploaded = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return uploaded.get('id')
