"""
Basic Cloud Functions for Minnesota Immunization Pipeline Demo
Demonstrates the pattern: External API -> Cloud Storage
"""

import json
import os
import base64
from datetime import datetime

# Handle imports gracefully for local testing
try:
    import requests
    from google.cloud import storage
    import functions_framework
except ImportError as e:
    print(f"Import warning: {e} - some functionality may not work in local testing")


def get_storage_client():
    """Get Google Cloud Storage client"""
    return storage.Client()


def upload_to_storage(bucket_name: str, blob_name: str, data: str):
    """Upload data to Google Cloud Storage"""
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type='text/plain')
    print(f"Uploaded to gs://{bucket_name}/{blob_name}")


def upload_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Monday scheduler)
    Simulates uploading student data to external system (Wikipedia search)
    """
    print("🚀 Upload function triggered!")
    print(f"Event: {event}")
    print(f"Context: {context}")
    
    # Get bucket name from environment
    bucket_name = os.environ.get('DATA_BUCKET')
    if not bucket_name:
        bucket_name = "mn-immun-bd9001-immunization-data"  # fallback for testing
        print(f"Using fallback bucket: {bucket_name}")
    
    # Simulate fetching student data (in real world: read from CSV, query database, etc.)
    students = [
        {"id": "12345", "name": "Student A", "grade": "K"},
        {"id": "67890", "name": "Student B", "grade": "1"},
    ]
    
    # Simulate uploading to external system (AISR)
    # For demo: search Wikipedia for immunization info
    search_results = []
    
    for student in students:
        try:
            # Wikipedia API search for immunization info
            response = requests.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/Vaccination",
                timeout=10
            )
            response.raise_for_status()
            
            wiki_data = response.json()
            search_results.append({
                "student_id": student["id"],
                "query_time": datetime.now().isoformat(),
                "external_response": {
                    "title": wiki_data.get("title"),
                    "extract": wiki_data.get("extract", "")[:200] + "..."
                }
            })
            print(f"✅ Processed student {student['id']}")
            
        except Exception as e:
            print(f"❌ Error processing student {student['id']}: {e}")
            search_results.append({
                "student_id": student["id"],
                "error": str(e),
                "query_time": datetime.now().isoformat()
            })
    
    # Store upload results in Cloud Storage
    upload_data = {
        "upload_time": datetime.now().isoformat(),
        "students_processed": len(students),
        "results": search_results,
        "status": "completed"
    }
    
    filename = f"uploads/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_upload_results.json"
    upload_to_storage(bucket_name, filename, json.dumps(upload_data, indent=2))
    
    print(f"📤 Upload completed: {len(students)} students processed")
    return {"status": "success", "students_processed": len(students)}


def download_handler(event, context):
    """
    Cloud Function triggered by Pub/Sub (Wednesday scheduler)
    Simulates downloading vaccination results from external system
    """
    print("📥 Download function triggered!")
    print(f"Event: {event}")
    print(f"Context: {context}")
    
    # Get bucket name from environment
    bucket_name = os.environ.get('DATA_BUCKET')
    if not bucket_name:
        bucket_name = "mn-immun-bd9001-immunization-data"  # fallback for testing
        print(f"Using fallback bucket: {bucket_name}")
    
    # Simulate downloading vaccination records from external system
    # For demo: get different Wikipedia content
    vaccination_records = []
    
    topics = ["Immunization", "Vaccine", "Public_health"]
    
    for topic in topics:
        try:
            response = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{topic}",
                timeout=10
            )
            response.raise_for_status()
            
            wiki_data = response.json()
            vaccination_records.append({
                "student_id": f"demo_{topic.lower()}",
                "vaccination_date": datetime.now().isoformat(),
                "vaccine_info": {
                    "source": wiki_data.get("title"),
                    "description": wiki_data.get("extract", "")[:150] + "...",
                    "url": wiki_data.get("content_urls", {}).get("desktop", {}).get("page", "")
                }
            })
            print(f"✅ Downloaded info for {topic}")
            
        except Exception as e:
            print(f"❌ Error downloading {topic}: {e}")
    
    # Transform data (in real world: convert AISR format to Infinite Campus CSV)
    transformed_records = []
    for record in vaccination_records:
        transformed_records.append({
            "StudentID": record["student_id"],
            "VaccinationDate": record["vaccination_date"],
            "VaccineType": record["vaccine_info"]["source"],
            "Notes": record["vaccine_info"]["description"],
            "DataSource": "Demo Wikipedia API"
        })
    
    # Store download and transformation results
    download_data = {
        "download_time": datetime.now().isoformat(),
        "records_downloaded": len(vaccination_records),
        "records_transformed": len(transformed_records),
        "raw_records": vaccination_records,
        "transformed_records": transformed_records,
        "status": "completed"
    }
    
    # Store both raw and transformed data
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    # Raw download data
    raw_filename = f"downloads/{timestamp}_raw_vaccination_data.json"
    upload_to_storage(bucket_name, raw_filename, json.dumps(download_data, indent=2))
    
    # Transformed CSV-like data (what would go to school district)
    csv_data = "StudentID,VaccinationDate,VaccineType,Notes,DataSource\n"
    for record in transformed_records:
        csv_data += f"{record['StudentID']},{record['VaccinationDate']},{record['VaccineType']},\"{record['Notes']}\",{record['DataSource']}\n"
    
    csv_filename = f"output/{timestamp}_school_district_vaccination_records.csv"
    upload_to_storage(bucket_name, csv_filename, csv_data)
    
    print(f"📥 Download completed: {len(vaccination_records)} records processed")
    return {
        "status": "success", 
        "records_downloaded": len(vaccination_records),
        "records_transformed": len(transformed_records)
    }


if __name__ == "__main__":
    # For local testing
    print("🧪 Testing functions locally...")
    
    # Mock event and context
    mock_event = {"data": "eyJhY3Rpb24iOiAidGVzdCJ9"}  # base64 encoded test data
    mock_context = type('MockContext', (), {'timestamp': '2023-01-01T00:00:00Z'})()
    
    # Test upload function
    print("\n--- Testing Upload Function ---")
    try:
        result = upload_handler(mock_event, mock_context)
        print(f"Upload result: {result}")
    except Exception as e:
        print(f"Upload test failed: {e}")
    
    print("\n--- Testing Download Function ---") 
    try:
        result = download_handler(mock_event, mock_context)
        print(f"Download result: {result}")
    except Exception as e:
        print(f"Download test failed: {e}")
    
    print("\n✅ Local testing completed!")